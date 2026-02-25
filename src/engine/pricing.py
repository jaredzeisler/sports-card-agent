"""Pricing engine using CardLadder recent sales data for fair market value."""


EBAY_SELLER_FEE_RATE = 0.1625  # ~16.25% total eBay + PayPal fees


def calculate_fmv(
    cardladder_fmv: float | None = None,
    cardladder_confidence: float = 0,
    avg_30d: float | None = None,
    avg_90d: float | None = None,
) -> dict:
    """Calculate fair market value from CardLadder recent sales data.

    Uses CardLadder's FMV (based on actual completed sales) as the primary
    value, cross-validated against their 30-day and 90-day sales averages.

    Returns dict with: fmv, confidence, sources_used, avg_30d, avg_90d, cardladder_fmv
    """
    sources_used = 0
    weighted_sum = 0.0
    total_weight = 0.0

    # CardLadder FMV — primary source (based on recent completed sales)
    if cardladder_fmv and cardladder_fmv > 0:
        cl_weight = 0.6 * max(cardladder_confidence / 100, 0.3)
        weighted_sum += cardladder_fmv * cl_weight
        total_weight += cl_weight
        sources_used += 1

    # CardLadder 30-day sales average — secondary validation
    if avg_30d and avg_30d > 0:
        avg30_weight = 0.3
        weighted_sum += avg_30d * avg30_weight
        total_weight += avg30_weight
        sources_used += 1

    # CardLadder 90-day sales average — tertiary/trend context
    if avg_90d and avg_90d > 0:
        avg90_weight = 0.1
        weighted_sum += avg_90d * avg90_weight
        total_weight += avg90_weight
        sources_used += 1

    if total_weight == 0:
        return {
            "fmv": cardladder_fmv or 0,
            "confidence": 10,
            "sources_used": 0,
            "avg_30d": avg_30d,
            "avg_90d": avg_90d,
            "cardladder_fmv": cardladder_fmv,
        }

    fmv = weighted_sum / total_weight

    # Confidence: higher when sales data points agree
    confidence = min(sources_used * 20 + (cardladder_confidence * 0.5), 100)

    # Boost confidence when FMV and 30d average are close (consistent recent sales)
    if cardladder_fmv and avg_30d and cardladder_fmv > 0:
        divergence = abs(avg_30d - cardladder_fmv) / max(avg_30d, cardladder_fmv)
        if divergence < 0.1:
            confidence = min(confidence + 15, 100)
        elif divergence > 0.3:
            confidence = max(confidence - 15, 10)

    return {
        "fmv": round(fmv, 2),
        "confidence": round(confidence, 1),
        "sources_used": sources_used,
        "avg_30d": round(avg_30d, 2) if avg_30d else None,
        "avg_90d": round(avg_90d, 2) if avg_90d else None,
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
