"""Tests for pricing engine using CardLadder recent sales data."""

from src.engine.pricing import calculate_fmv, calculate_net_profit


def test_fmv_cardladder_only():
    result = calculate_fmv(cardladder_fmv=100.0, cardladder_confidence=80)
    assert result["fmv"] > 0
    assert result["sources_used"] == 1
    assert result["cardladder_fmv"] == 100.0


def test_fmv_with_30d_average():
    result = calculate_fmv(
        cardladder_fmv=100.0,
        cardladder_confidence=80,
        avg_30d=98.0,
    )
    assert result["fmv"] > 0
    assert result["sources_used"] == 2
    assert result["avg_30d"] == 98.0


def test_fmv_all_sales_sources():
    result = calculate_fmv(
        cardladder_fmv=100.0,
        cardladder_confidence=80,
        avg_30d=98.0,
        avg_90d=95.0,
    )
    assert result["fmv"] > 0
    assert result["sources_used"] == 3
    assert result["confidence"] > 50
    assert result["avg_30d"] == 98.0
    assert result["avg_90d"] == 95.0


def test_fmv_no_data():
    result = calculate_fmv()
    assert result["fmv"] == 0
    assert result["confidence"] == 10


def test_fmv_close_fmv_and_30d_boosts_confidence():
    """When FMV and 30d average are within 10%, confidence gets a boost."""
    result = calculate_fmv(
        cardladder_fmv=100.0,
        avg_30d=98.0,
        cardladder_confidence=80,
    )
    assert result["confidence"] > 60


def test_fmv_divergent_fmv_and_30d_lowers_confidence():
    """When FMV and 30d average diverge >30%, confidence is penalized."""
    result = calculate_fmv(
        cardladder_fmv=100.0,
        avg_30d=60.0,
        cardladder_confidence=80,
    )
    # Should still have positive confidence but lower than close agreement
    close_result = calculate_fmv(
        cardladder_fmv=100.0,
        avg_30d=98.0,
        cardladder_confidence=80,
    )
    assert result["confidence"] < close_result["confidence"]


def test_fmv_only_averages_no_fmv():
    """Should still produce a value from 30d/90d averages alone."""
    result = calculate_fmv(avg_30d=100.0, avg_90d=95.0)
    assert result["fmv"] > 0
    assert result["sources_used"] == 2
    assert result["cardladder_fmv"] is None


def test_net_profit_calculation():
    result = calculate_net_profit(sell_price=100, buy_price=50)
    assert result["net"] > 0
    assert result["fees"] > 0
    assert result["margin_pct"] > 0
    assert result["gross"] == 50


def test_net_profit_loss():
    result = calculate_net_profit(sell_price=40, buy_price=50)
    assert result["net"] < 0
    assert result["margin_pct"] < 0


def test_net_profit_zero_buy():
    result = calculate_net_profit(sell_price=100, buy_price=0)
    assert result["margin_pct"] == 0
