"""Goldin auction tracker — live bid monitoring with FMV analysis.

Combines GoldinClient live scraping with the comp ladder pricing engine
to track bids in real-time and flag actionable opportunities.
"""

from datetime import datetime, timezone

from src.api.goldin import GoldinClient, BUYER_PREMIUM_RATE
from src.engine.pricing import EBAY_SELLER_FEE_RATE


# FMV estimates: {lot_number: (fmv, confidence%, trend)}
FMV_ESTIMATES = {
    1:  (2200, 55, "stable"),
    2:  (1350, 80, "stable"),
    3:  (1800, 60, "stable"),
    4:  (1900, 70, "up"),
    5:  (2000, 65, "up"),
    6:  (2100, 50, "stable"),
    7:  (1000, 65, "stable"),
    8:  (1400, 60, "up"),
    9:  (1000, 65, "up"),
    10: (1100, 55, "up"),
    11: (1050, 60, "stable"),
    12: (1050, 60, "stable"),
    13: (475, 65, "stable"),
    14: (850, 55, "stable"),
    15: (800, 50, "up"),
    16: (600, 55, "up"),
    17: (575, 60, "stable"),
    18: (350, 60, "stable"),
    19: (750, 65, "up"),
    20: (800, 55, "up"),
    21: (300, 65, "stable"),
    22: (650, 50, "stable"),
    23: (550, 60, "up"),
    24: (575, 60, "stable"),
    25: (425, 60, "stable"),
    26: (225, 60, "stable"),
    27: (625, 55, "stable"),
    28: (625, 55, "stable"),
    29: (300, 60, "up"),
    30: (350, 55, "up"),
    31: (400, 40, "stable"),
    32: (200, 50, "up"),
    33: (300, 70, "stable"),
    34: (325, 50, "up"),
    35: (175, 45, "stable"),
    36: (110, 45, "down"),
    37: (200, 55, "stable"),
    38: (185, 50, "stable"),
    39: (150, 50, "stable"),
    40: (275, 50, "stable"),
    41: (140, 50, "stable"),
    42: (275, 50, "up"),
    43: (175, 50, "stable"),
    44: (250, 45, "stable"),
    45: (225, 60, "up"),
    46: (185, 55, "stable"),
    47: (200, 50, "stable"),
    48: (165, 50, "stable"),
    49: (185, 45, "stable"),
    50: (90, 60, "stable"),
    51: (50, 40, "stable"),
    52: (55, 45, "stable"),
    53: (130, 50, "stable"),
    54: (55, 50, "stable"),
    55: (25, 50, "down"),
    56: (45, 45, "stable"),
    57: (25, 45, "stable"),
    58: (55, 50, "up"),
    59: (35, 45, "down"),
    60: (60, 40, "up"),
    61: (85, 40, "up"),
    62: (30, 40, "up"),
}


def analyze_lot(lot: dict) -> dict:
    """Analyze a single lot against its FMV estimate.

    Args:
        lot: Dict with at least 'lot', 'card', 'current_bid', 'tier', 'pop'

    Returns:
        Dict with full analysis: all_in_cost, fmv, net_profit, margin, verdict, trend
    """
    lot_num = lot["lot"]
    fmv_est, confidence, trend = FMV_ESTIMATES.get(lot_num, (0, 0, "stable"))
    current_bid = lot["current_bid"]

    all_in_cost = current_bid * (1 + BUYER_PREMIUM_RATE)
    ebay_net = fmv_est * (1 - EBAY_SELLER_FEE_RATE)
    net_profit = ebay_net - all_in_cost
    margin = (net_profit / all_in_cost * 100) if all_in_cost > 0 else 0

    pop = lot.get("pop") or 0

    if margin >= 30 and confidence >= 55:
        verdict = "BUY"
    elif margin >= 15 and confidence >= 45:
        verdict = "WATCH"
    elif margin >= 0:
        verdict = "THIN"
    else:
        verdict = "PASS"

    return {
        "lot": lot_num,
        "card": lot["card"],
        "tier": lot.get("tier", "?"),
        "player": lot.get("player", ""),
        "current_bid": current_bid,
        "all_in_cost": round(all_in_cost, 2),
        "fmv": fmv_est,
        "confidence": confidence,
        "trend": trend,
        "net_profit": round(net_profit, 2),
        "margin_pct": round(margin, 1),
        "verdict": verdict,
        "pop": pop,
        "scarce": 0 < pop < 10,
    }


def analyze_all(lots: list[dict]) -> list[dict]:
    """Analyze all lots and return sorted results."""
    results = [analyze_lot(lot) for lot in lots]
    return results


def max_bid_for_target_margin(lot_number: int, target_margin_pct: float = 15.0) -> float | None:
    """Calculate the maximum hammer price to achieve a target margin.

    This tells you the max you should bid to still make money.

    Args:
        lot_number: The lot number
        target_margin_pct: Desired profit margin after all fees (default 15%)

    Returns:
        Maximum hammer price (before buyer's premium), or None if no FMV data
    """
    if lot_number not in FMV_ESTIMATES:
        return None

    fmv, _, _ = FMV_ESTIMATES[lot_number]
    ebay_net = fmv * (1 - EBAY_SELLER_FEE_RATE)

    # all_in = hammer × (1 + premium)
    # margin = (ebay_net - all_in) / all_in
    # target = (ebay_net / all_in) - 1
    # all_in = ebay_net / (1 + target)
    # hammer = all_in / (1 + premium)
    target = target_margin_pct / 100
    all_in = ebay_net / (1 + target)
    max_hammer = all_in / (1 + BUYER_PREMIUM_RATE)

    return round(max_hammer, 2)


def refresh_live_bids(lots: list[dict], lot_urls: dict[int, str] | None = None) -> list[dict]:
    """Fetch live bids from Goldin and update lot data.

    Args:
        lots: The LOTS list to update in-place
        lot_urls: Optional dict mapping lot numbers to Goldin URLs

    Returns:
        List of lots that had bid changes, with old and new values
    """
    if not lot_urls:
        from Inventory.goldin_auction_2026_04 import LOT_URLS
        lot_urls = LOT_URLS

    if not lot_urls:
        return []

    client = GoldinClient()
    changes = []

    for lot in lots:
        lot_num = lot["lot"]
        url = lot_urls.get(lot_num)
        if not url:
            continue

        live_data = client.get_auction_lot(url)
        if not live_data or live_data.get("current_bid", 0) <= 0:
            continue

        old_bid = lot["current_bid"]
        new_bid = live_data["current_bid"]

        if new_bid != old_bid:
            lot["current_bid"] = new_bid
            changes.append({
                "lot": lot_num,
                "card": lot["card"],
                "old_bid": old_bid,
                "new_bid": new_bid,
                "change": new_bid - old_bid,
                "change_pct": ((new_bid - old_bid) / old_bid * 100) if old_bid > 0 else 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    return changes
