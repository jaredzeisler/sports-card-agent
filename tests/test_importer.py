"""Tests for the XLS/CSV importer."""

import csv
import os
import pytest
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base
from src.importer.xls_import import (
    import_from_csv, _match_column, _parse_price, _parse_date, _parse_grade,
)


def test_match_column_exact():
    assert _match_column("player") == "player"
    assert _match_column("Player") == "player"


def test_match_column_alias():
    assert _match_column("Player Name") == "player"
    assert _match_column("card year") == "year"
    assert _match_column("PSA") == "grade"


def test_match_column_unknown():
    assert _match_column("foobar") is None


def test_parse_price_string():
    assert _parse_price("$150.00") == 150.0
    assert _parse_price("$1,500.00") == 1500.0
    assert _parse_price("50") == 50.0


def test_parse_price_numeric():
    assert _parse_price(150.0) == 150.0
    assert _parse_price(50) == 50.0


def test_parse_price_none():
    assert _parse_price(None) is None
    assert _parse_price("") is None


def test_parse_date_formats():
    d = _parse_date("2024-01-15")
    assert d is not None
    assert d.year == 2024
    d2 = _parse_date("01/15/2024")
    assert d2 is not None
    assert d2.month == 1


def test_parse_date_none():
    assert _parse_date(None) is None
    assert _parse_date("not a date") is None


def test_parse_grade_numeric():
    assert _parse_grade(10) == 10.0
    assert _parse_grade(9.5) == 9.5


def test_parse_grade_string():
    assert _parse_grade("PSA 10") == 10.0
    assert _parse_grade("10") == 10.0


def test_parse_grade_none():
    assert _parse_grade(None) is None


@pytest.fixture
def temp_csv():
    """Create a temporary CSV file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Player", "Year", "Brand", "Set", "Grade", "Price", "Cert"])
        writer.writerow(["Luka Doncic", "2018", "Panini", "Prizm", "10", "$150.00", "12345678"])
        writer.writerow(["LeBron James", "2003", "Topps", "Chrome", "9", "$5,000.00", "87654321"])
        writer.writerow(["", "", "", "", "", "", ""])  # Empty row — should be skipped
        path = f.name
    yield path
    os.unlink(path)


def test_import_csv(temp_csv, monkeypatch):
    # Monkeypatch to use in-memory DB
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    import src.importer.xls_import as mod
    monkeypatch.setattr(mod, "init_db", lambda: engine)
    monkeypatch.setattr(mod, "get_session", lambda: Session())

    result = import_from_csv(temp_csv)
    assert result["imported"] == 2
    assert result["skipped"] == 1  # Empty row
    assert len(result["errors"]) == 0


def test_import_missing_file():
    result = import_from_csv("/nonexistent/file.csv")
    assert result["imported"] == 0
    assert "File not found" in result["errors"][0]
