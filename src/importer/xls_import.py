"""Import cards from CSV/Excel spreadsheet files."""

import csv
import re
from datetime import datetime
from pathlib import Path

from src.models.database import get_session, init_db
from src.models.card import Card, CardStatus


# Flexible column name matching
COLUMN_MAP = {
    "player": ["player", "player name", "name", "player_name", "athlete"],
    "year": ["year", "card year", "card_year", "yr"],
    "brand": ["brand", "manufacturer", "company"],
    "set_name": ["set", "set name", "set_name", "product", "card set"],
    "card_number": ["card number", "card_number", "number", "card #", "#", "card_no"],
    "variation": ["variation", "parallel", "variant", "color", "insert"],
    "sport": ["sport", "category"],
    "grade": ["grade", "psa grade", "bgs grade", "sgc grade", "psa", "bgs", "sgc"],
    "grading_company": ["grading company", "grading_company", "grader", "slab"],
    "cert_number": ["cert", "cert number", "cert_number", "certification", "cert_no", "psa cert"],
    "purchase_price": ["price", "purchase price", "purchase_price", "cost", "paid", "amount"],
    "purchase_date": ["date", "purchase date", "purchase_date", "bought", "date purchased"],
    "purchase_source": ["source", "purchase source", "purchase_source", "bought from", "seller", "platform"],
    "notes": ["notes", "note", "comments", "memo"],
}


def _match_column(header: str) -> str | None:
    """Match a spreadsheet column header to a known field name."""
    header_lower = header.strip().lower()
    for field, aliases in COLUMN_MAP.items():
        if header_lower in aliases:
            return field
    return None


def _parse_price(value: str | float | int) -> float | None:
    """Parse a price value, handling $, commas, etc."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.]", "", str(value))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _parse_date(value) -> datetime | None:
    """Parse a date value from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_grade(value) -> float | None:
    """Parse a grade value."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        # Try extracting number from string like "PSA 10"
        match = re.search(r"(\d+\.?\d*)", str(value))
        return float(match.group(1)) if match else None


def import_from_csv(file_path: str, default_sport: str = "basketball") -> dict:
    """Import cards from a CSV file.

    Returns dict with: imported (count), skipped (count), errors (list)
    """
    path = Path(file_path)
    if not path.exists():
        return {"imported": 0, "skipped": 0, "errors": [f"File not found: {file_path}"]}

    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    return _import_rows(rows, default_sport)


def import_from_excel(file_path: str, default_sport: str = "basketball") -> dict:
    """Import cards from an Excel (.xls/.xlsx) file.

    Returns dict with: imported (count), skipped (count), errors (list)
    """
    path = Path(file_path)
    if not path.exists():
        return {"imported": 0, "skipped": 0, "errors": [f"File not found: {file_path}"]}

    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        ws = wb.active

        rows_iter = ws.iter_rows(values_only=False)
        header_row = next(rows_iter)
        headers = [cell.value or "" for cell in header_row]

        rows = []
        for row in rows_iter:
            row_dict = {}
            for i, cell in enumerate(row):
                if i < len(headers):
                    row_dict[headers[i]] = cell.value
            rows.append(row_dict)

        wb.close()
    except ImportError:
        return {"imported": 0, "skipped": 0, "errors": ["openpyxl not installed. Run: pip install openpyxl"]}

    return _import_rows(rows, default_sport)


def import_file(file_path: str, default_sport: str = "basketball") -> dict:
    """Auto-detect file format and import."""
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext == ".csv":
        return import_from_csv(file_path, default_sport)
    elif ext in (".xls", ".xlsx"):
        return import_from_excel(file_path, default_sport)
    else:
        return {"imported": 0, "skipped": 0, "errors": [f"Unsupported file format: {ext}"]}


def _import_rows(rows: list[dict], default_sport: str) -> dict:
    """Process rows and import into database."""
    init_db()
    session = get_session()
    imported = 0
    skipped = 0
    errors = []

    try:
        for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
            try:
                # Map column names
                mapped = {}
                for raw_key, value in row.items():
                    if raw_key is None:
                        continue
                    field = _match_column(str(raw_key))
                    if field:
                        mapped[field] = value

                player = mapped.get("player")
                if not player or str(player).strip() == "":
                    skipped += 1
                    continue

                # Check for duplicate by cert number
                cert = mapped.get("cert_number")
                if cert:
                    existing = session.query(Card).filter_by(cert_number=str(cert)).first()
                    if existing:
                        skipped += 1
                        continue

                grade = _parse_grade(mapped.get("grade"))
                card = Card(
                    player=str(player).strip(),
                    year=int(mapped["year"]) if mapped.get("year") else None,
                    brand=str(mapped["brand"]).strip() if mapped.get("brand") else None,
                    set_name=str(mapped["set_name"]).strip() if mapped.get("set_name") else None,
                    card_number=str(mapped["card_number"]).strip() if mapped.get("card_number") else None,
                    variation=str(mapped["variation"]).strip() if mapped.get("variation") else None,
                    sport=str(mapped.get("sport", default_sport)).strip(),
                    graded=grade is not None,
                    grade=grade,
                    grading_company=str(mapped["grading_company"]).strip() if mapped.get("grading_company") else ("PSA" if grade else None),
                    cert_number=str(cert).strip() if cert else None,
                    purchase_price=_parse_price(mapped.get("purchase_price")),
                    purchase_date=_parse_date(mapped.get("purchase_date")),
                    purchase_source=str(mapped["purchase_source"]).strip() if mapped.get("purchase_source") else None,
                    status=CardStatus.IN_COLLECTION,
                    notes=str(mapped["notes"]).strip() if mapped.get("notes") else None,
                )
                session.add(card)
                imported += 1

            except Exception as e:
                errors.append(f"Row {i}: {str(e)}")

        session.commit()
    except Exception as e:
        session.rollback()
        errors.append(f"Database error: {str(e)}")
    finally:
        session.close()

    return {"imported": imported, "skipped": skipped, "errors": errors}
