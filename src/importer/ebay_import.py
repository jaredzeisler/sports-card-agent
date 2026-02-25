"""Import purchase history from eBay orders (API or CSV export)."""

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

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


def _parse_ebay_price(value: str) -> float | None:
    """Parse a price value from eBay CSV, handling $, commas, etc."""
    if not value:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(value))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _parse_ebay_date(value: str) -> datetime | None:
    """Parse a date from eBay CSV export (various formats)."""
    if not value or not value.strip():
        return None
    formats = [
        "%b %d, %Y",                  # Dec 31, 2025
        "%b-%d-%y", "%b-%d-%Y",       # Jan-15-25, Jan-15-2025
        "%m/%d/%Y", "%m/%d/%y",       # 01/15/2025, 01/15/25
        "%Y-%m-%d",                    # 2025-01-15
        "%d-%b-%Y", "%d-%b-%y",       # 15-Jan-2025
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _read_ebay_rows(file_path: str) -> list[dict]:
    """Read rows from an eBay export file (CSV, XLS, or XLSX)."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in (".xls", ".xlsx"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        rows = []
        for ws in wb.worksheets:
            rows_iter = ws.iter_rows(values_only=False)
            header_row = next(rows_iter, None)
            if header_row is None:
                continue
            headers = [str(cell.value or "").strip() for cell in header_row]
            for row in rows_iter:
                row_dict = {}
                for i, cell in enumerate(row):
                    if i < len(headers):
                        row_dict[headers[i]] = cell.value if cell.value is not None else ""
                rows.append(row_dict)
        wb.close()
        return rows

    # Default: CSV (also handles .tsv)
    with open(path, "r", encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        reader = csv.DictReader(f, dialect=dialect)
        if reader.fieldnames:
            reader.fieldnames = [h.strip() for h in reader.fieldnames]
        return list(reader)


def import_ebay_csv(file_path: str) -> dict:
    """Import cards from an eBay purchase history export (CSV, XLS, or XLSX).

    Expected columns: OrderNumber, OrderDate, ItemID, Seller, ItemName,
    ItemPrice, Currency, Quantity, OrderTotal, OrderNotes, TrackingNumber,
    Image URL, View Order Detail

    Returns dict with: imported (count), skipped (count), errors (list)
    """
    path = Path(file_path)
    if not path.exists():
        return {"imported": 0, "skipped": 0, "errors": [f"File not found: {file_path}"]}

    try:
        rows = _read_ebay_rows(file_path)
    except ImportError:
        return {"imported": 0, "skipped": 0, "errors": ["openpyxl not installed. Run: pip install openpyxl"]}
    except Exception as e:
        return {"imported": 0, "skipped": 0, "errors": [f"Failed to read file: {str(e)}"]}

    init_db()
    session = get_session()
    imported = 0
    skipped = 0
    errors = []

    try:
        for row_num, row in enumerate(rows, start=2):
            try:
                title = str(row.get("ItemName") or row.get("Item Name") or "").strip()
                item_id = str(row.get("ItemID") or row.get("Item ID") or "").strip()
                price_str = row.get("ItemPrice") or row.get("Item Price") or ""
                order_date_str = str(row.get("OrderDate") or row.get("Order Date") or "")
                order_number = str(row.get("OrderNumber") or row.get("Order Number") or "").strip()
                seller = str(row.get("Seller") or "").strip()

                price = _parse_ebay_price(price_str)
                if not title or not price or price <= 0:
                    skipped += 1
                    continue

                # Dedup by eBay item ID
                if item_id:
                    existing = session.query(Card).filter_by(ebay_item_id=item_id).first()
                    if existing:
                        skipped += 1
                        continue

                # Parse the listing title for card details
                parsed = parse_listing_title(title)

                purchase_date = _parse_ebay_date(order_date_str)

                card = Card(
                    player=parsed.get("player") or title[:100],
                    year=parsed.get("year"),
                    brand=parsed.get("brand"),
                    set_name=parsed.get("set_name"),
                    sport=parsed.get("sport") or "basketball",
                    graded=parsed.get("grade") is not None,
                    grade=parsed.get("grade"),
                    grading_company="PSA" if parsed.get("grade") else None,
                    variation=parsed.get("variation"),
                    purchase_price=price,
                    purchase_date=purchase_date or datetime.now(timezone.utc),
                    purchase_source="ebay",
                    status=CardStatus.IN_COLLECTION,
                    ebay_item_id=item_id or None,
                    notes=f"Imported from eBay (order {order_number}, seller: {seller})",
                )
                session.add(card)
                session.flush()

                txn = Transaction(
                    card_id=card.id,
                    transaction_type=TransactionType.BUY,
                    price=price,
                    platform="ebay",
                    ebay_order_id=order_number or None,
                )
                session.add(txn)
                imported += 1

            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")

        session.commit()
    except Exception as e:
        session.rollback()
        errors.append(f"Import error: {str(e)}")
    finally:
        session.close()

    return {"imported": imported, "skipped": skipped, "errors": errors}
