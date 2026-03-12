"""Core trading agent — orchestrates scanning, buying, selling, and approvals."""

from datetime import datetime, timezone, timedelta

from config.settings import get_settings
from src.api.ebay import EbayClient
from src.agent.scanner import MarketScanner
from src.models.database import get_session
from src.models.card import (
    Card, Transaction, Listing, ApprovalRequest,
    CardStatus, TransactionType, ApprovalStatus,
)
from src.notifications.notifier import (
    notify_deal_found, notify_trade_executed, notify_approval_needed, notify_error,
)


class TradingAgent:
    """The brain of the sports card trading operation."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.ebay = EbayClient(self.settings)
        self.scanner = MarketScanner(settings=self.settings)

    def run_scan(self, dry_run: bool = True) -> list[dict]:
        """Scan the market and act on deals found."""
        deals = self.scanner.scan(dry_run=dry_run)
        session = get_session()

        try:
            for deal in deals:
                if deal["action"] == "buy":
                    self._handle_buy_deal(deal, session, dry_run)
                elif deal["action"] == "hold":
                    notify_deal_found(
                        deal["player"], deal["price"], deal["fmv"], deal["score"],
                        url=deal.get("listing_url"),
                    )
        finally:
            session.close()

        return deals

    def _handle_buy_deal(self, deal: dict, session, dry_run: bool):
        """Handle a deal recommended for buying."""
        price = deal["price"]

        # Check portfolio limits
        total_invested = self._get_total_invested(session)
        if total_invested + price > self.settings.max_portfolio_value:
            notify_error(
                "Portfolio limit",
                f"Would exceed max portfolio value (${self.settings.max_portfolio_value})",
            )
            return

        if price > self.settings.max_single_card:
            notify_error(
                "Single card limit",
                f"${price} exceeds max single card (${self.settings.max_single_card})",
            )
            return

        if price <= self.settings.auto_buy_limit:
            # Auto-execute
            if dry_run:
                notify_deal_found(
                    deal["player"], price, deal["fmv"], deal["score"],
                    url=deal.get("listing_url"),
                )
                return
            self._execute_buy(deal, session)
        else:
            # Needs approval
            self._create_approval(deal, session)

    def _execute_buy(self, deal: dict, session):
        """Execute an actual purchase on eBay."""
        try:
            order = self.ebay.place_order(deal["item_id"])

            # Create card record
            card = Card(
                player=deal["player"],
                year=deal["parsed"].get("year"),
                brand=deal["parsed"].get("brand"),
                set_name=deal["parsed"].get("set_name"),
                sport=deal["parsed"].get("sport", "basketball"),
                graded=deal["parsed"].get("grade") is not None,
                grade=deal["parsed"].get("grade"),
                grading_company="PSA" if deal["parsed"].get("grade") else None,
                purchase_price=deal["price"],
                purchase_date=datetime.now(timezone.utc),
                purchase_source="ebay",
                status=CardStatus.IN_COLLECTION,
                current_fmv=deal["fmv"],
                fmv_updated_at=datetime.now(timezone.utc),
                ebay_item_id=deal["item_id"],
            )
            session.add(card)
            session.flush()

            # Create transaction record
            txn = Transaction(
                card_id=card.id,
                transaction_type=TransactionType.BUY,
                price=deal["price"],
                platform="ebay",
                ebay_order_id=order.get("purchaseOrderId"),
            )
            session.add(txn)

            # Mark listing as purchased
            listing = session.query(Listing).filter_by(id=deal["listing_id"]).first()
            if listing:
                listing.purchased = True

            session.commit()
            notify_trade_executed("buy", deal["player"], deal["price"])

        except Exception as e:
            session.rollback()
            notify_error("Buy execution", str(e))

    def _execute_sell(self, card: Card, target_price: float, session):
        """List a card for sale on eBay."""
        try:
            title = f"{card.year} {card.brand} {card.set_name} {card.player}"
            if card.graded:
                title += f" PSA {int(card.grade)}"

            result = self.ebay.create_listing(
                title=title,
                description=f"Authenticated {card.grading_company} {card.grade} grade card.",
                price=target_price,
                sku=f"card-{card.id}",
            )

            card.status = CardStatus.LISTED
            txn = Transaction(
                card_id=card.id,
                transaction_type=TransactionType.SELL,
                price=target_price,
                fees=round(target_price * 0.1625, 2),
                platform="ebay",
            )
            session.add(txn)
            session.commit()
            notify_trade_executed("sell", card.player, target_price)

        except Exception as e:
            session.rollback()
            notify_error("Sell execution", str(e))

    def _create_approval(self, deal: dict, session):
        """Create an approval request for a trade above the auto-buy limit."""
        approval = ApprovalRequest(
            listing_id=deal["listing_id"],
            action="buy",
            price=deal["price"],
            estimated_fmv=deal["fmv"],
            estimated_profit=deal["estimated_profit"],
            reason="; ".join(deal["reasons"]),
            status=ApprovalStatus.PENDING,
        )
        session.add(approval)
        session.commit()
        notify_approval_needed(deal["player"], deal["price"], deal["fmv"], url=deal.get("listing_url"))

    def execute_approval(self, approval_id: int) -> bool:
        """Execute a previously approved trade."""
        session = get_session()
        try:
            approval = session.query(ApprovalRequest).filter_by(id=approval_id).first()
            if not approval or approval.status != ApprovalStatus.PENDING:
                return False

            approval.status = ApprovalStatus.APPROVED
            approval.resolved_at = datetime.now(timezone.utc)

            if approval.action == "buy" and approval.listing_id:
                listing = session.query(Listing).filter_by(id=approval.listing_id).first()
                if listing and not listing.purchased:
                    deal = {
                        "listing_id": listing.id,
                        "item_id": listing.ebay_item_id,
                        "player": listing.player or "Unknown",
                        "price": listing.price,
                        "fmv": listing.estimated_fmv or 0,
                        "parsed": {
                            "year": listing.year,
                            "brand": listing.brand,
                            "set_name": listing.set_name,
                            "grade": listing.grade,
                            "sport": listing.sport,
                        },
                    }
                    self._execute_buy(deal, session)

            elif approval.action == "sell" and approval.card_id:
                card = session.query(Card).filter_by(id=approval.card_id).first()
                if card:
                    self._execute_sell(card, approval.price, session)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            notify_error("Approval execution", str(e))
            return False
        finally:
            session.close()

    def reject_approval(self, approval_id: int) -> bool:
        """Reject a pending approval."""
        session = get_session()
        try:
            approval = session.query(ApprovalRequest).filter_by(id=approval_id).first()
            if not approval or approval.status != ApprovalStatus.PENDING:
                return False
            approval.status = ApprovalStatus.REJECTED
            approval.resolved_at = datetime.now(timezone.utc)
            session.commit()
            return True
        finally:
            session.close()

    def clean_expired_approvals(self, max_age_hours: int = 24):
        """Expire old approval requests."""
        session = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            expired = (
                session.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                    ApprovalRequest.created_at < cutoff,
                )
                .all()
            )
            for a in expired:
                a.status = ApprovalStatus.EXPIRED
                a.resolved_at = datetime.now(timezone.utc)
            session.commit()
            return len(expired)
        finally:
            session.close()

    def _get_total_invested(self, session) -> float:
        """Get total amount currently invested in cards."""
        cards = (
            session.query(Card)
            .filter(Card.status == CardStatus.IN_COLLECTION)
            .all()
        )
        return sum(c.purchase_price or 0 for c in cards)
