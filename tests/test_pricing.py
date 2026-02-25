"""Tests for pricing engine."""

from src.engine.pricing import calculate_fmv, calculate_net_profit


def test_fmv_cardladder_only():
    result = calculate_fmv(cardladder_fmv=100.0, cardladder_confidence=80)
    assert result["fmv"] > 0
    assert result["sources_used"] == 1
    assert result["cardladder_fmv"] == 100.0


def test_fmv_ebay_only():
    prices = [90, 95, 100, 105, 110]
    result = calculate_fmv(ebay_sold_prices=prices)
    assert result["fmv"] > 0
    assert result["sources_used"] == 1
    assert result["ebay_median"] == 100


def test_fmv_both_sources():
    result = calculate_fmv(
        cardladder_fmv=100.0,
        ebay_sold_prices=[90, 95, 100, 105, 110],
        cardladder_confidence=80,
    )
    assert result["fmv"] > 0
    assert result["sources_used"] == 2
    assert result["confidence"] > 50


def test_fmv_no_data():
    result = calculate_fmv()
    assert result["fmv"] == 0
    assert result["confidence"] == 10


def test_fmv_too_few_ebay_comps():
    result = calculate_fmv(ebay_sold_prices=[100, 200])
    assert result["ebay_median"] is None
    assert result["sources_used"] == 0


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


def test_fmv_high_divergence_lowers_confidence():
    result = calculate_fmv(
        cardladder_fmv=100.0,
        ebay_sold_prices=[50, 55, 60, 65, 70],  # Much lower than CL
        cardladder_confidence=80,
    )
    assert result["sources_used"] == 2


def test_fmv_low_divergence_raises_confidence():
    result = calculate_fmv(
        cardladder_fmv=100.0,
        ebay_sold_prices=[98, 99, 100, 101, 102],  # Very close to CL
        cardladder_confidence=80,
    )
    assert result["confidence"] > 60
