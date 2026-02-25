"""Import purchase history from eBay orders."""

from datetime import datetime, timezone

from config.settings import get_settings
from src.api.ebay import EbayClient
from src.agent.scanner import parse_listing_title
from src.models.database import get_session, init_db
from src.models.card import Card, Transaction, CardStatus, TransactionType


def import_ebay_purchases(days: int = 365) -> dict:
    """Fetch eBay purchase history and import as cards.

    Returns dict with: imported (count), skipped (count), errors (list)
    """
    settings = get_settings()
    if not settings.ebay_user_token:
        return {"imported": 0, "skipped": 0, "errors": ["EBAY_USER_TOKEN not set in .env"]}

    ebay = EbayClient(settings)
    init_db()
    session = get_session()
    imported = 0
    skipped = 0
    errors = []

    try:
        orders = ebay.get_orders(days=days)

        for order in orders:
            try:
                for item in order.get("lineItems", []):
                    title = item.get("title", "")
                    price = float(item.get("lineItemCost", {}).get("value", 0))
                    item_id = item.get("itemId", "")

                    if not title or price <= 0:
                        skipped += 1
                        continue

                    # Check if already imported by eBay item ID
                    existing = session.query(Card).filter_by(ebay_item_id=item_id).first()
                    if existing:
                        skipped += 1
                        continue

                    # Parse listing title
                    parsed = parse_listing_title(title)

                    card = Card(
                        player=parsed.get("player") or title[:100],
                        year=parsed.get("year"),
                        brand=parsed.get("brand"),
                        set_name=parsed.get("set_name"),
                        sport=parsed.get("sport", "basketball"),
                        graded=parsed.get("grade") is not None,
                        grade=parsed.get("grade"),
                        grading_company="PSA" if parsed.get("grade") else None,
                        variation=parsed.get("variation"),
                        purchase_price=price,
                        purchase_date=datetime.now(timezone.utc),
                        purchase_source="ebay",
                        status=CardStatus.IN_COLLECTION,
                        ebay_item_id=item_id,
                        notes=f"Auto-imported from eBay order",
                    )
                    session.add(card)
                    session.flush()

                    txn = Transaction(
                        card_id=card.id,
                        transaction_type=TransactionType.BUY,
                        price=price,
                        platform="ebay",
                        ebay_order_id=order.get("orderId"),
                    )
                    session.add(txn)
                    imported += 1

            except Exception as e:
                errors.append(f"Order {order.get('orderId', '?')}: {str(e)}")

        session.commit()
    except Exception as e:
        session.rollback()
        errors.append(f"eBay API error: {str(e)}")
    finally:
        session.close()

    return {"imported": imported, "skipped": skipped, "errors": errors}
