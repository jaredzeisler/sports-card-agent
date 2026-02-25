"""Pricing engine that aggregates multiple data sources into a fair market value."""


EBAY_SELLER_FEE_RATE = 0.1625  # ~16.25% total eBay + PayPal fees


def calculate_fmv(
    cardladder_fmv: float | None = None,
    ebay_sold_prices: list[float] | None = None,
    cardladder_confidence: float = 0,
) -> dict:
    """Calculate a weighted fair market value from multiple sources.

    Returns dict with: fmv, confidence, sources_used, ebay_median, cardladder_fmv
    """
    sources_used = 0
    weighted_sum = 0.0
    total_weight = 0.0

    # CardLadder FMV (weighted by their confidence)
    cl_weight = 0.0
    if cardladder_fmv and cardladder_fmv > 0:
        cl_weight = 0.6 * max(cardladder_confidence / 100, 0.3)
        weighted_sum += cardladder_fmv * cl_weight
        total_weight += cl_weight
        sources_used += 1

    # eBay sold comps median
    ebay_median = None
    ebay_weight = 0.0
    if ebay_sold_prices and len(ebay_sold_prices) >= 3:
        sorted_prices = sorted(ebay_sold_prices)
        mid = len(sorted_prices) // 2
        ebay_median = (
            sorted_prices[mid]
            if len(sorted_prices) % 2 == 1
            else (sorted_prices[mid - 1] + sorted_prices[mid]) / 2
        )
        # More comps = more confidence in eBay data
        comp_factor = min(len(ebay_sold_prices) / 20, 1.0)
        ebay_weight = 0.4 + (0.2 * comp_factor)
        weighted_sum += ebay_median * ebay_weight
        total_weight += ebay_weight
        sources_used += 1

    if total_weight == 0:
        return {
            "fmv": cardladder_fmv or 0,
            "confidence": 10,
            "sources_used": 0,
            "ebay_median": None,
            "cardladder_fmv": cardladder_fmv,
        }

    fmv = weighted_sum / total_weight

    # Confidence: higher when sources agree and more data is available
    confidence = min(sources_used * 30 + (cardladder_confidence * 0.4), 100)
    if ebay_median and cardladder_fmv and sources_used == 2:
        divergence = abs(ebay_median - cardladder_fmv) / max(ebay_median, cardladder_fmv)
        if divergence < 0.1:
            confidence = min(confidence + 15, 100)
        elif divergence > 0.3:
            confidence = max(confidence - 15, 10)

    return {
        "fmv": round(fmv, 2),
        "confidence": round(confidence, 1),
        "sources_used": sources_used,
        "ebay_median": round(ebay_median, 2) if ebay_median else None,
        "cardladder_fmv": cardladder_fmv,
    }


def calculate_net_profit(sell_price: float, buy_price: float, fee_rate: float = EBAY_SELLER_FEE_RATE) -> dict:
    """Calculate net profit after fees."""
    fees = sell_price * fee_rate
    net = sell_price - fees - buy_price
    margin = (net / buy_price * 100) if buy_price > 0 else 0
    return {
        "gross": sell_price - buy_price,
        "fees": round(fees, 2),
        "net": round(net, 2),
        "margin_pct": round(margin, 1),
    }
