"""Autobidder — monitors auctions and places FMV-capped bids.

Workflow:
  1. Load saved search criteria from DB
  2. For each search: find matching auctions on Fanatics/eBay
  3. For each auction: look up card FMV, calculate max bid
  4. If current price is below max bid, place a proxy bid
  5. Track all bids in the auction_bids table
  6. Repeat on a configurable interval

Tier pricing:
  - Top 25 players: bid up to 80% of FMV (all-in including buyer's premium)
  - Everyone else: bid up to 60% of FMV (all-in)
"""

import time
from datetime import datetime, timezone

from config.settings import get_settings
from src.models.database import get_session, init_db
from src.models.bid import AuctionBid, BidSearchCriteria, BidStatus
from src.engine.bid_engine import calculate_max_bid, should_bid, is_tier1_player
from src.notifications.notifier import notify_error


class Autobidder:
    """Orchestrates auction monitoring and bidding across platforms."""

    def __init__(self, settings=None, headless: bool = True):
        self.settings = settings or get_settings()
        self.headless = headless
        self._fanatics = None
        self._ebay = None

    def _get_fanatics(self):
        if not self._fanatics:
            from src.api.fanatics import FanaticsClient
            self._fanatics = FanaticsClient(self.settings, headless=self.headless)
        return self._fanatics

    def _get_ebay(self):
        if not self._ebay:
            from src.api.ebay import EbayClient
            self._ebay = EbayClient(self.settings)
        return self._ebay

    def _get_fmv(self, player: str, year: int | None, brand: str | None,
                 set_name: str | None, grade: float | None,
                 sport: str = "basketball") -> float | None:
        """Look up FMV using the pricing waterfall."""
        from src.engine.fmv_update import get_card_fmv
        result = get_card_fmv(
            player=player, year=year, brand=brand,
            set_name=set_name, grade=grade, sport=sport,
        )
        if result and result.get("fmv", 0) > 0:
            return result["fmv"]
        return None

    # ── Search & Bid Flow ───────────────────────────────────────────

    def run_once(self, dry_run: bool = True) -> dict:
        """Run one pass: search all criteria, evaluate, bid.

        Returns dict with: searched, auctions_found, bids_placed,
        bids_skipped, errors
        """
        init_db()
        session = get_session()
        stats = {
            "searched": 0,
            "auctions_found": 0,
            "bids_placed": 0,
            "bids_skipped": 0,
            "errors": [],
        }

        try:
            criteria = (
                session.query(BidSearchCriteria)
                .filter(BidSearchCriteria.enabled == True)
                .all()
            )
            if not criteria:
                print("No search criteria configured. Use 'cardagent autobid add-search' to add some.")
                return stats

            print(f"Processing {len(criteria)} saved searches...")

            for crit in criteria:
                try:
                    self._process_search(crit, session, dry_run, stats)
                    crit.last_run_at = datetime.now(timezone.utc)
                    session.commit()
                except Exception as e:
                    stats["errors"].append(f"{crit.platform}:{crit.query} — {e}")
                    print(f"  ERROR: {e}")
                    session.rollback()

                stats["searched"] += 1

        finally:
            session.close()
            # Close Fanatics browser if it was used
            if self._fanatics:
                import asyncio
                asyncio.run(self._fanatics.close())

        return stats

    def _process_search(self, crit: BidSearchCriteria, session, dry_run: bool, stats: dict):
        """Process a single search criteria — find auctions and bid."""
        print(f"\n  [{crit.platform.upper()}] Searching: {crit.query}")

        if crit.platform == "fanatics":
            auctions = self._search_fanatics(crit)
        elif crit.platform == "ebay":
            auctions = self._search_ebay(crit)
        else:
            print(f"    Unknown platform: {crit.platform}")
            return

        print(f"    Found {len(auctions)} auctions")
        stats["auctions_found"] += len(auctions)

        for auction in auctions:
            self._evaluate_and_bid(auction, crit, session, dry_run, stats)

    def _search_fanatics(self, crit: BidSearchCriteria) -> list[dict]:
        """Search Fanatics Collect for matching auctions."""
        import asyncio
        client = self._get_fanatics()

        async def _search():
            logged_in = await client.login()
            if not logged_in:
                raise RuntimeError("Failed to log in to Fanatics Collect")
            return await client.search_auctions(crit.query)

        return asyncio.run(_search())

    def _search_ebay(self, crit: BidSearchCriteria) -> list[dict]:
        """Search eBay for matching auction listings."""
        client = self._get_ebay()
        results = client.search_auctions(
            query=crit.query,
            max_price=crit.hard_cap,
            limit=50,
        )
        # Normalize to common format
        for r in results:
            r["auction_id"] = r.get("item_id", "")
            r["auction_url"] = r.get("auction_url", "")
        return results

    def _evaluate_and_bid(
        self, auction: dict, crit: BidSearchCriteria,
        session, dry_run: bool, stats: dict,
    ):
        """Evaluate a single auction and decide whether to bid."""
        auction_id = auction.get("auction_id", "")
        title = auction.get("title", "")
        current_price = auction.get("current_price", 0)
        platform = crit.platform

        # Check if we already have a bid record for this auction
        existing = (
            session.query(AuctionBid)
            .filter_by(platform=platform, auction_id=auction_id)
            .first()
        )

        # Skip if already won, lost, or skipped
        if existing and existing.status in (
            BidStatus.WON, BidStatus.LOST, BidStatus.SKIPPED
        ):
            return

        # Determine player name (from criteria or title)
        player = crit.player or self._extract_player_from_title(title)
        if not player:
            return

        # Look up FMV
        fmv = self._get_fmv(
            player=player,
            year=crit.year,
            brand=crit.brand,
            set_name=crit.set_name,
            grade=crit.min_grade,
            sport=crit.sport or "basketball",
        )

        if not fmv:
            print(f"    {title[:50]:50s} — no FMV, skipping")
            stats["bids_skipped"] += 1
            return

        # Calculate max bid
        decision = should_bid(
            current_price=current_price,
            fmv=fmv,
            player_name=player,
            platform=platform,
            hard_cap=crit.hard_cap or self.settings.autobid_hard_cap,
        )

        bid_calc = calculate_max_bid(
            fmv=fmv,
            player_name=player,
            platform=platform,
            override_pct=crit.override_fmv_pct,
        )

        if not decision["bid"]:
            print(f"    {title[:50]:50s} — SKIP: {decision['reason']}")
            # Record as skipped
            if not existing:
                bid_record = AuctionBid(
                    platform=platform,
                    auction_id=auction_id,
                    auction_url=auction.get("auction_url", ""),
                    title=title,
                    player=player,
                    year=crit.year,
                    brand=crit.brand,
                    set_name=crit.set_name,
                    grade=crit.min_grade,
                    sport=crit.sport,
                    fmv=fmv,
                    fmv_pct=bid_calc["fmv_pct"],
                    tier=bid_calc["tier"],
                    max_hammer_bid=bid_calc["max_hammer"],
                    max_all_in=bid_calc["max_all_in"],
                    buyers_premium_rate=bid_calc["buyers_premium_rate"],
                    current_price=current_price,
                    status=BidStatus.SKIPPED,
                    search_query=crit.query,
                    notes=decision["reason"],
                )
                session.add(bid_record)
                session.commit()
            stats["bids_skipped"] += 1
            return

        # Place the bid
        max_bid = decision["max_hammer"]
        print(
            f"    {title[:50]:50s} — BID ${max_bid:.2f} "
            f"(current ${current_price:.2f}, FMV ${fmv:.2f}, {bid_calc['tier']})"
        )

        if dry_run:
            print(f"      [DRY RUN] Would bid ${max_bid:.2f}")
            stats["bids_placed"] += 1
        else:
            result = self._place_bid(platform, auction, max_bid)
            if result["success"]:
                print(f"      BID PLACED: {result['message']}")
                stats["bids_placed"] += 1
            else:
                print(f"      BID FAILED: {result['message']}")
                stats["errors"].append(f"{title[:40]}: {result['message']}")

        # Record/update bid
        if existing:
            existing.current_price = current_price
            existing.our_max_bid = max_bid
            existing.bid_count += 1
            existing.last_bid_at = datetime.now(timezone.utc)
            existing.status = BidStatus.BID_PLACED if not dry_run else BidStatus.WATCHING
            existing.fmv = fmv
        else:
            bid_record = AuctionBid(
                platform=platform,
                auction_id=auction_id,
                auction_url=auction.get("auction_url", ""),
                title=title,
                player=player,
                year=crit.year,
                brand=crit.brand,
                set_name=crit.set_name,
                grade=crit.min_grade,
                sport=crit.sport,
                fmv=fmv,
                fmv_pct=bid_calc["fmv_pct"],
                tier=bid_calc["tier"],
                max_hammer_bid=bid_calc["max_hammer"],
                max_all_in=bid_calc["max_all_in"],
                buyers_premium_rate=bid_calc["buyers_premium_rate"],
                current_price=current_price,
                our_max_bid=max_bid,
                bid_count=1 if not dry_run else 0,
                status=BidStatus.BID_PLACED if not dry_run else BidStatus.WATCHING,
                last_bid_at=datetime.now(timezone.utc) if not dry_run else None,
                search_query=crit.query,
                notes=decision["reason"],
            )
            session.add(bid_record)

        session.commit()

    def _place_bid(self, platform: str, auction: dict, max_bid: float) -> dict:
        """Place a bid on the appropriate platform."""
        if platform == "fanatics":
            import asyncio
            client = self._get_fanatics()
            return asyncio.run(
                client.place_bid(auction["auction_url"], max_bid)
            )
        elif platform == "ebay":
            client = self._get_ebay()
            return client.place_proxy_bid(auction["auction_id"], max_bid)
        else:
            return {"success": False, "message": f"Unknown platform: {platform}"}

    # ── Continuous Mode ─────────────────────────────────────────────

    def run_continuous(self, dry_run: bool = True, interval: int | None = None):
        """Run the autobidder in a loop.

        Args:
            dry_run: If True, don't actually place bids
            interval: Seconds between runs (default from settings)
        """
        interval = interval or self.settings.autobid_poll_interval
        print(f"Autobidder starting — polling every {interval}s")
        if dry_run:
            print("DRY RUN mode — no real bids will be placed")
        print()

        try:
            while True:
                try:
                    stats = self.run_once(dry_run=dry_run)
                    print(
                        f"\n  Pass complete: {stats['auctions_found']} auctions, "
                        f"{stats['bids_placed']} bids, {stats['bids_skipped']} skipped"
                    )
                    if stats["errors"]:
                        print(f"  Errors: {len(stats['errors'])}")
                except Exception as e:
                    print(f"\n  ERROR in autobidder pass: {e}")
                    notify_error("Autobidder", str(e))

                print(f"\n  Sleeping {interval}s...")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nAutobidder stopped.")

    # ── Bid Status Check ────────────────────────────────────────────

    def check_bid_status(self) -> list[dict]:
        """Check status of all active bids and update records."""
        init_db()
        session = get_session()
        results = []

        try:
            active_bids = (
                session.query(AuctionBid)
                .filter(AuctionBid.status.in_([
                    BidStatus.BID_PLACED,
                    BidStatus.WINNING,
                    BidStatus.OUTBID,
                ]))
                .all()
            )

            for bid in active_bids:
                if bid.platform == "ebay":
                    status = self._get_ebay().get_bidding_status(bid.auction_id)
                    if status:
                        bid.current_price = status["current_price"]
                        if status.get("auction_status") == "ENDED":
                            bid.status = BidStatus.WON if status["high_bidder"] else BidStatus.LOST
                            if bid.status == BidStatus.WON:
                                bid.winning_price = status["current_price"]
                        elif status["high_bidder"]:
                            bid.status = BidStatus.WINNING
                        else:
                            bid.status = BidStatus.OUTBID

                results.append({
                    "platform": bid.platform,
                    "title": bid.title,
                    "status": bid.status.value,
                    "current_price": bid.current_price,
                    "our_max_bid": bid.our_max_bid,
                    "fmv": bid.fmv,
                })

            session.commit()
        finally:
            session.close()

        return results

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_player_from_title(title: str) -> str | None:
        """Best-effort player name extraction from an auction title.

        Falls back to None if we can't confidently extract a name.
        This is used when the search criteria doesn't specify a player.
        """
        # Common patterns: "2024 Panini Prizm LeBron James #1 PSA 10"
        # For now, return None — the search criteria should specify the player
        return None
