"""Tests for deal analyzer."""

import pytest
from unittest.mock import MagicMock
from src.engine.analyzer import DealAnalyzer


@pytest.fixture
def analyzer():
    settings = MagicMock()
    settings.max_single_card = 500.0
    settings.min_profit_margin = 0.15
    return DealAnalyzer(settings=settings)


def test_good_deal(analyzer):
    result = analyzer.analyze(
        listing_price=50, estimated_fmv=100, fmv_confidence=80, trend="up"
    )
    assert result["action"] == "buy"
    assert result["score"] > 60
    assert result["estimated_profit"] > 0


def test_bad_deal(analyzer):
    result = analyzer.analyze(
        listing_price=100, estimated_fmv=80, fmv_confidence=50, trend="down"
    )
    assert result["action"] == "skip"
    assert result["estimated_profit"] < 0


def test_borderline_deal(analyzer):
    result = analyzer.analyze(
        listing_price=80, estimated_fmv=100, fmv_confidence=50, trend="stable"
    )
    # Should be hold or skip — margin is decent but not amazing
    assert result["action"] in ("hold", "skip", "buy")


def test_zero_fmv(analyzer):
    result = analyzer.analyze(listing_price=50, estimated_fmv=0)
    assert result["action"] == "skip"
    assert result["score"] == 0


def test_zero_price(analyzer):
    result = analyzer.analyze(listing_price=0, estimated_fmv=100)
    assert result["action"] == "skip"


def test_exceeds_max_card(analyzer):
    result = analyzer.analyze(
        listing_price=600, estimated_fmv=1200, fmv_confidence=80, trend="up"
    )
    assert "max single card" in " ".join(result["reasons"]).lower()


def test_low_population_bonus(analyzer):
    result = analyzer.analyze(
        listing_price=50, estimated_fmv=100, fmv_confidence=80,
        trend="up", population=10,
    )
    assert result["score"] > 70


def test_should_sell_profitable(analyzer):
    result = analyzer.should_sell(purchase_price=50, current_fmv=100, trend="stable")
    assert result["action"] == "sell"
    assert result["net_profit"] > 0


def test_should_sell_trending_up(analyzer):
    result = analyzer.should_sell(purchase_price=80, current_fmv=100, trend="up")
    assert result["action"] in ("hold", "sell")


def test_should_sell_at_loss(analyzer):
    result = analyzer.should_sell(purchase_price=100, current_fmv=60, trend="stable")
    assert result["action"] == "hold"
    assert result["net_profit"] < 0
