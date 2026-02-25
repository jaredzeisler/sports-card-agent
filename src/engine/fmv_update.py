"""Batch FMV update for all cards in inventory.

Pricing waterfall:
  1. SportsCardsPro — real eBay sold prices by exact grade (best)
  2. Card Hedge comps — time-weighted eBay sold prices
  3. eBay Browse API — active listing median, discounted 10%
"""

import time
from datetime import datetime, timezone

from src.models.database import get_session, init_db
from src.models.card import Card
from src.engine.pricing import get_ebay_market_price, calculate_fmv
from config.settings import get_settings


def _try_sportscardspro(card, settings) -> dict | None:
    """Try SportsCardsPro for real sold-price FMV by grade."""
    if not settings.sportscardspro_api_key:
        return None

    from src.api.sportscardspro import SportsCardsProClient
    client = SportsCardsProClient(settings)
    result = client.get_fmv(
        player=card.player,
        year=card.year,
        brand=card.brand,
        set_name=card.set_name,
        grade=card.grade,
        grading_company=card.grading_company,
        card_number=card.card_number,
        variation=card.variation,
    )
    if result and result.get("fmv") and result["fmv"] > 0:
        vol = result.get("sales_volume", 0)
        confidence = min(40 + vol * 0.5, 95) if vol else 50
        return {
            "fmv": result["fmv"],
            "confidence": confidence,
            "source": "sportscardspro",
            "num_comps": vol,
            "detail": f"${result['fmv']:.2f} ({result['grade_used']}, {vol} sales) — {result['product_name']}",
            "product_id": result.get("product_id"),
        }
    return None


def _try_cardhedge(card, settings) -> dict | None:
    """Try Card Hedge API for time-weighted sold comps."""
    if not settings.cardhedge_api_key:
        return None

    from src.api.cardhedge import CardHedgeClient
    client = CardHedgeClient(settings)
    result = client.get_fmv(
        player=card.player,
        year=card.year,
        brand=card.brand,
        set_name=card.set_name,
        grade=card.grade,
        sport=card.sport or "basketball",
    )
    if result and result.get("fmv") and result["fmv"] > 0:
        return {
            "fmv": result["fmv"],
            "confidence": min(result.get("num_comps", 0) * 15, 95),
            "source": "cardhedge",
            "num_comps": result.get("num_comps", 0),
            "detail": f"${result['fmv']:.2f} ({result.get('num_comps', 0)} comps, ${result.get('low', 0):.2f}-${result.get('high', 0):.2f})",
        }
    return None


def _try_ebay(card, settings) -> dict | None:
    """Try eBay active listings (last resort — asking prices discounted 10%)."""
    if not settings.ebay_app_id:
        return None

    market = get_ebay_market_price(
        player=card.player,
        year=card.year,
        brand=card.brand,
        set_name=card.set_name,
        grade=card.grade,
        grading_company=card.grading_company,
        sport=card.sport or "basketball",
    )
    if not market:
        market = get_ebay_market_price(
            player=card.player,
            grade=card.grade,
            grading_company=card.grading_company,
        )
    if not market:
        return None

    result = calculate_fmv(
        ebay_price=market["fmv"],
        ebay_confidence=market["confidence"],
    )
    if result["fmv"] <= 0:
        return None

    return {
        "fmv": result["fmv"],
        "confidence": result["confidence"],
        "source": "ebay_active",
        "num_comps": market["num_listings"],
        "detail": f"${result['fmv']:.2f} ({market['num_listings']} listings, -10% discount)",
    }


def update_all_fmv(
    dry_run: bool = False,
    delay: float = 1.0,
    source: str = "auto",
) -> dict:
    """Update FMV for all cards in the database.

    Args:
        dry_run: If True, don't write to DB
        delay: Seconds between API calls (rate limiting)
        source: "auto" (SportsCardsPro -> CardHedge -> eBay),
                "sportscardspro", "cardhedge", or "ebay"

    Returns dict with: updated, skipped, no_data, errors, by_source
    """
    init_db()
    settings = get_settings()
    session = get_session()
    updated = 0
    skipped = 0
    no_data = 0
    errors = []
    by_source = {}

    try:
        cards = session.query(Card).order_by(Card.id).all()
        cards = [c for c in cards if not (c.notes and "[NOT A CARD]" in c.notes)]
        total = len(cards)

        sources_label = source
        if source == "auto":
            parts = []
            if settings.sportscardspro_api_key:
                parts.append("SportsCardsPro")
            if settings.cardhedge_api_key:
                parts.append("Card Hedge")
            if settings.ebay_app_id:
                parts.append("eBay")
            sources_label = " -> ".join(parts) if parts else "no API keys configured"

        print(f"Pricing {total} cards...")
        print(f"  Source: {sources_label}")
        print(f"  Rate limit: {delay}s between calls")
        if dry_run:
            print(f"  DRY RUN — no DB writes")
        print()

        for i, card in enumerate(cards):
            label = f"  [{i+1}/{total}] {card.player[:35]:35s}"
            print(label, end=" ", flush=True)

            try:
                result = None

                if source in ("auto", "sportscardspro"):
                    result = _try_sportscardspro(card, settings)

                if not result and source in ("auto", "cardhedge"):
                    result = _try_cardhedge(card, settings)

                if not result and source in ("auto", "ebay"):
                    result = _try_ebay(card, settings)

                if not result:
                    print("-- no data")
                    no_data += 1
                    time.sleep(delay)
                    continue

                fmv = result["fmv"]
                paid = card.purchase_price or 0
                diff = fmv - paid
                diff_pct = (diff / paid * 100) if paid > 0 else 0
                arrow = "+" if diff >= 0 else ""

                src = result["source"]
                by_source[src] = by_source.get(src, 0) + 1

                print(f"{result['detail']}")

                if not dry_run:
                    card.current_fmv = fmv
                    card.fmv_updated_at = datetime.now(timezone.utc)
                    session.commit()

                updated += 1

            except Exception as e:
                print(f"ERROR: {e}")
                errors.append(f"Card {card.id} ({card.player}): {e}")

            time.sleep(delay)

        print(f"\n{'='*60}")
        print(f"Done: {updated} updated, {no_data} no data, {len(errors)} errors")
        if by_source:
            print(f"Sources: {by_source}")

    finally:
        session.close()

    return {
        "updated": updated,
        "skipped": skipped,
        "no_data": no_data,
        "errors": errors,
        "by_source": by_source,
    }
