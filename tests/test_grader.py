"""Tests for the card grading assessment engine."""

from src.engine.grader import (
    _parse_grading_response,
    _parse_number,
    PSA_SCALE,
    BGS_SCALE,
)


def test_parse_number_integer():
    assert _parse_number("8") == 8.0


def test_parse_number_decimal():
    assert _parse_number("9.5") == 9.5


def test_parse_number_with_text():
    assert _parse_number("About 8 out of 10") == 8.0


def test_parse_number_none():
    assert _parse_number("no number here") is None


def test_parse_grading_response_full():
    text = """PLAYER: Jayson Tatum
YEAR: 2017
BRAND: Topps
SET: Chrome
VARIATION: Orange Refractor
SERIAL: 04/25
CENTERING: 8
CORNERS: 9
EDGES: 8.5
SURFACE: 9
PSA_ESTIMATE: 9
BGS_ESTIMATE: 9.0
NOTES: Well-centered card with sharp corners."""

    result = _parse_grading_response(text)

    assert result["card"]["player"] == "Jayson Tatum"
    assert result["card"]["year"] == 2017
    assert result["card"]["brand"] == "Topps"
    assert result["card"]["set_name"] == "Chrome"
    assert result["card"]["variation"] == "Orange Refractor"
    assert result["card"]["serial"] == "04/25"
    assert result["sub_grades"]["centering"] == 8.0
    assert result["sub_grades"]["corners"] == 9.0
    assert result["sub_grades"]["edges"] == 8.5
    assert result["sub_grades"]["surface"] == 9.0
    assert result["psa_estimate"] == 9.0
    assert result["psa_label"] == "MINT"
    assert result["bgs_estimate"] == 9.0
    assert result["bgs_label"] == "Mint"
    assert "sharp corners" in result["notes"]


def test_parse_grading_response_gem_mint():
    text = """PLAYER: LeBron James
YEAR: 2003
BRAND: Topps
SET: Chrome
VARIATION: NONE
SERIAL: NONE
CENTERING: 10
CORNERS: 10
EDGES: 10
SURFACE: 10
PSA_ESTIMATE: 10
BGS_ESTIMATE: 10
NOTES: Perfect card in all respects."""

    result = _parse_grading_response(text)

    assert result["psa_estimate"] == 10.0
    assert result["psa_label"] == "GEM-MT (Gem Mint)"
    assert result["bgs_estimate"] == 10.0
    assert result["bgs_label"] == "Pristine"


def test_parse_grading_response_no_variation():
    text = """PLAYER: Luka Doncic
YEAR: 2018
BRAND: Panini
SET: Prizm
VARIATION: NONE
SERIAL: NONE
CENTERING: 7
CORNERS: 8
EDGES: 7
SURFACE: 8
PSA_ESTIMATE: 7
BGS_ESTIMATE: 7.5
NOTES: Centering slightly off."""

    result = _parse_grading_response(text)

    assert "variation" not in result["card"]
    assert "serial" not in result["card"]
    assert result["psa_estimate"] == 7.0
    assert result["psa_label"] == "NM (Near Mint)"
    assert result["bgs_estimate"] == 7.5
    assert result["bgs_label"] == "NM+"


def test_parse_grading_response_unknown_year():
    text = """PLAYER: Test Player
YEAR: UNKNOWN
BRAND: Panini
SET: Prizm
VARIATION: NONE
SERIAL: NONE
CENTERING: 8
CORNERS: 8
EDGES: 8
SURFACE: 8
PSA_ESTIMATE: 8
BGS_ESTIMATE: 8.0
NOTES: Year not visible."""

    result = _parse_grading_response(text)

    assert "year" not in result["card"]


def test_psa_scale_coverage():
    """Ensure PSA scale covers grades 1-10."""
    for grade in range(1, 11):
        assert grade in PSA_SCALE


def test_bgs_scale_has_half_grades():
    """BGS should include half-point grades."""
    assert 9.5 in BGS_SCALE
    assert 8.5 in BGS_SCALE
    assert 7.5 in BGS_SCALE


def test_assess_grade_no_api_key():
    """assess_grade returns None when no API key is configured."""
    from unittest.mock import patch, MagicMock

    mock_settings = MagicMock()
    mock_settings.anthropic_api_key = ""

    from src.engine.grader import assess_grade
    result = assess_grade("/fake/path.jpg", settings=mock_settings)
    assert result is None
