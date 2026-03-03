"""Pricing engine for fair market value.

Pricing waterfall (best to worst):
  1. SportsCardsPro — real eBay sold prices by exact grade (best)
  2. CardLadder — FMV + 30d/90d averages from recent sales
  3. Card Hedge comps — time-weighted eBay sold prices (when key is approved)
  4. eBay Browse API — active listing median, discounted 10% (last resort)
"""

import statistics

from src.api.ebay import EbayClient
from config.settings import get_settings

EBAY_SELLER_FEE_RATE = 0.1625  # ~16.25% total eBay + PayPal fees


def _build_search_query(
    player: str,
    year: int | None = None,
    brand: str | None = None,
    set_name: str | None = None,
    grade: float | None = None,
    grading_company: str | None = None,
) -> str:
    """Build an eBay search query from card attributes."""
    parts = []
    if year:
        parts.append(str(year))
    parts.append(player)
    if brand:
        parts.append(brand)
    if set_name:
        parts.append(set_name)
    if grade:
        company = grading_company or "PSA"
        grade_int = int(grade) if grade == int(grade) else grade
        parts.append(f"{company} {grade_int}")
    return " ".join(parts)


def get_ebay_market_price(
    player: str,
    year: int | None = None,
    brand: str | None = None,
    set_name: str | None = None,
    grade: float | None = None,
    grading_company: str | None = None,
    sport: str = "basketball",
) -> dict | None:
    """Get market price from eBay active listings (fallback source).

    Returns dict with: fmv, high, low, median, num_listings, confidence, query
    """
    query = _build_search_query(player, year, brand, set_name, grade, grading_company)

    settings = get_settings()
    ebay = EbayClient(settings)

    try:
        listings = ebay.search_listings(query, limit=50)
    except Exception:
        return None

    if not listings:
        return None

    prices = []
    for item in listings:
        price_info = item.get("price", {})
        try:
            p = float(price_info.get("value", 0))
            if p > 0:
                prices.append(p)
        except (ValueError, TypeError):
            continue

    if not prices:
        return None

    # Trim outliers: remove top and bottom 20%
    prices.sort()
    n = len(prices)
    if n >= 5:
        trim = max(1, n // 5)
        trimmed = prices[trim:-trim]
    else:
        trimmed = prices

    if not trimmed:
        trimmed = prices

    fmv = statistics.median(trimmed)
    mean = statistics.mean(trimmed)

    confidence = min(n * 5, 50)
    if len(trimmed) >= 3:
        try:
            stdev = statistics.stdev(trimmed)
            cv = stdev / mean if mean > 0 else 1
            if cv < 0.15:
                confidence += 30
            elif cv < 0.30:
                confidence += 20
            elif cv < 0.50:
                confidence += 10
        except statistics.StatisticsError:
            pass
    confidence = min(confidence, 90)

    return {
        "fmv": round(fmv, 2),
        "mean": round(mean, 2),
        "high": round(max(trimmed), 2),
        "low": round(min(trimmed), 2),
        "median": round(fmv, 2),
        "num_listings": n,
        "num_used": len(trimmed),
        "confidence": confidence,
        "query": query,
        "source": "ebay_active",
    }


def calculate_fmv(
    cardladder_fmv: float | None = None,
    cardladder_confidence: float = 0,
    avg_30d: float | None = None,
    avg_90d: float | None = None,
    ebay_price: float | None = None,
    ebay_confidence: float = 0,
    cardhedge_price: float | None = None,
    cardhedge_num_comps: int = 0,
) -> dict:
    """Calculate composite FMV from all available pricing sources.

    Priority waterfall:
      1. CardLadder FMV + 30d/90d averages (sold data, best signal)
      2. Card Hedge comps (sold data, good signal when 3+ comps)
      3. eBay active listings median, discounted 10% (weakest signal)

    Returns dict with: fmv, confidence, source, sources_used,
    and pass-through values for cardladder_fmv, avg_30d, avg_90d.
    """
    values = []
    sources_used = 0

    # Collect available price signals
    if cardladder_fmv and cardladder_fmv > 0:
        values.append(cardladder_fmv)
        sources_used += 1

    if avg_30d and avg_30d > 0:
        values.append(avg_30d)
        sources_used += 1

    if avg_90d and avg_90d > 0:
        values.append(avg_90d)
        sources_used += 1

    # Card Hedge comps (only if no CardLadder data)
    if not values and cardhedge_price and cardhedge_price > 0 and cardhedge_num_comps >= 3:
        return {
            "fmv": round(cardhedge_price, 2),
            "confidence": min(cardhedge_num_comps * 15, 95),
            "source": "cardhedge_comps",
            "sources_used": 1,
            "cardladder_fmv": None,
            "avg_30d": avg_30d,
            "avg_90d": avg_90d,
        }

    # eBay active listings (only if no CardLadder or CardHedge data)
    if not values and ebay_price and ebay_price > 0:
        sold_estimate = ebay_price * 0.90
        return {
            "fmv": round(sold_estimate, 2),
            "confidence": round(ebay_confidence * 0.85, 1),
            "source": "ebay_active_discounted",
            "sources_used": 1,
            "cardladder_fmv": None,
            "avg_30d": avg_30d,
            "avg_90d": avg_90d,
        }

    # No data at all
    if not values:
        return {
            "fmv": 0,
            "confidence": 10,
            "source": "none",
            "sources_used": 0,
            "cardladder_fmv": None,
            "avg_30d": avg_30d,
            "avg_90d": avg_90d,
        }

    # Weighted average: CardLadder FMV weighted higher than averages
    if cardladder_fmv and cardladder_fmv > 0:
        weights = [2.0]  # CardLadder FMV gets 2x weight
        weighted = [cardladder_fmv * 2.0]
        if avg_30d and avg_30d > 0:
            weights.append(1.5)
            weighted.append(avg_30d * 1.5)
        if avg_90d and avg_90d > 0:
            weights.append(1.0)
            weighted.append(avg_90d * 1.0)
        fmv = sum(weighted) / sum(weights)
    else:
        # Only averages, no CardLadder FMV
        if avg_30d and avg_90d:
            fmv = avg_30d * 0.6 + avg_90d * 0.4
        elif avg_30d:
            fmv = avg_30d
        else:
            fmv = avg_90d

    # Confidence calculation
    confidence = cardladder_confidence or 0
    base_boost = sources_used * 5
    confidence = confidence + base_boost

    # Agreement bonus/penalty between CardLadder FMV and 30d average
    if cardladder_fmv and avg_30d and cardladder_fmv > 0:
        divergence = abs(cardladder_fmv - avg_30d) / cardladder_fmv
        if divergence <= 0.10:
            confidence += 10  # close agreement boosts confidence
        elif divergence > 0.30:
            confidence -= 10  # large divergence penalizes confidence

    confidence = max(0, min(confidence, 99))

    return {
        "fmv": round(fmv, 2),
        "confidence": round(confidence, 1),
        "source": "cardladder",
        "sources_used": sources_used,
        "cardladder_fmv": cardladder_fmv,
        "avg_30d": avg_30d,
        "avg_90d": avg_90d,
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
