"""Tests for the market scanner title parser."""

from src.agent.scanner import parse_listing_title_regex


def test_parse_full_title():
    title = "2018 Panini Prizm Luka Doncic PSA 10 Silver #280 Rookie RC"
    result = parse_listing_title_regex(title)
    assert result["year"] == 2018
    assert result["brand"] == "Panini"
    assert result["set_name"] == "Prizm"
    assert result["grade"] == 10
    assert result["variation"] == "Silver"


def test_parse_minimal_title():
    title = "LeBron James basketball card"
    result = parse_listing_title_regex(title)
    assert result["player"] is not None
    assert result["year"] is None
    assert result["grade"] is None


def test_parse_bgs_grade():
    title = "2019 Panini Select Ja Morant BGS 9.5 Rookie"
    result = parse_listing_title_regex(title)
    assert result["grade"] == 9.5
    assert result["year"] == 2019


def test_parse_multiple_brands():
    title = "2003 Topps Chrome LeBron James PSA 9"
    result = parse_listing_title_regex(title)
    assert result["brand"] == "Topps"
    assert result["set_name"] == "Chrome"
    assert result["grade"] == 9
    assert result["year"] == 2003


def test_parse_variation_detection():
    title = "2020 Panini Prizm Anthony Edwards Gold PSA 10"
    result = parse_listing_title_regex(title)
    assert result["variation"] == "Gold"


def test_parse_no_grade():
    title = "2018 Panini Prizm Luka Doncic Silver #280 Rookie"
    result = parse_listing_title_regex(title)
    assert result["grade"] is None
    assert result["set_name"] == "Prizm"


def test_parse_sgc_grade():
    title = "2019 Mosaic Ja Morant SGC 10 Rookie"
    result = parse_listing_title_regex(title)
    assert result["grade"] == 10
    assert result["set_name"] == "Mosaic"
