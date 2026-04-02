"""Goldin auction tracker — seller defense mode.

You are the SELLER. You get hammer price + 15% (1.15x hammer).
The buyer pays hammer + 22% to Goldin. Goldin keeps the 7% spread.

This tracker tells you which lots are in danger of selling below what
you'd get on eBay, and calculates your defense floor for each card.

Fee structure:
  - You receive: hammer × 1.15 (hammer plus 15% consignment bonus)
  - Buyer pays: hammer × 1.22 (hammer plus 22% buyer's premium)
  - Goldin keeps: the 7% spread between buyer premium and your payout
  - Alternative: eBay resale FMV minus 16.25% eBay fees
  - Defense floor: minimum hammer where Goldin net >= eBay net
"""

from datetime import datetime, timezone

from src.api.goldin import GoldinClient
from src.engine.pricing import EBAY_SELLER_FEE_RATE

# You get 115% of hammer price
GOLDIN_SELLER_NET_RATE = 1.15


# FMV estimates: {lot_number: (fmv, confidence%, trend)}
# FMV = what the card would sell for on eBay at fair market value
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


def defense_floor(lot_number: int) -> float | None:
    """Calculate the minimum hammer price where Goldin net >= eBay net.

    Below this price, you're better off pulling the card and selling on eBay.

    Formula:
      eBay net   = FMV × 0.8375
      Goldin net = hammer × 1.15
      Break-even: hammer × 1.15 = FMV × 0.8375
      Floor = FMV × 0.8375 / 1.15 = FMV × 0.7283
    """
    if lot_number not in FMV_ESTIMATES:
        return None
    fmv, _, _ = FMV_ESTIMATES[lot_number]
    ebay_net = fmv * (1 - EBAY_SELLER_FEE_RATE)
    floor = ebay_net / GOLDIN_SELLER_NET_RATE
    return round(floor, 2)


def analyze_lot(lot: dict) -> dict:
    """Analyze a single lot from the SELLER's perspective.

    Returns defense status, your net proceeds, how far below/above floor, etc.
    """
    lot_num = lot["lot"]
    fmv_est, confidence, trend = FMV_ESTIMATES.get(lot_num, (0, 0, "stable"))
    current_bid = lot["current_bid"]
    pop = lot.get("pop") or 0

    # What you net from Goldin at current hammer
    goldin_net = current_bid * GOLDIN_SELLER_NET_RATE

    # What you'd net selling on eBay instead
    ebay_net = fmv_est * (1 - EBAY_SELLER_FEE_RATE)

    # How much you're losing vs eBay at this hammer price
    vs_ebay = goldin_net - ebay_net

    # Defense floor — minimum acceptable hammer
    floor = defense_floor(lot_num) or 0

    # How far current bid is from floor
    floor_gap = current_bid - floor
    floor_gap_pct = (floor_gap / floor * 100) if floor > 0 else 0

    # Defense verdict
    if current_bid >= floor * 1.15:
        verdict = "SAFE"        # 15%+ above floor — let it ride
    elif current_bid >= floor:
        verdict = "CLOSE"       # Above floor but thin — watch it
    elif current_bid >= floor * 0.85:
        verdict = "DEFEND"      # Below floor but within 15% — bid it up
    else:
        verdict = "DANGER"      # Way below floor — needs immediate defense

    return {
        "lot": lot_num,
        "card": lot["card"],
        "tier": lot.get("tier", "?"),
        "player": lot.get("player", ""),
        "current_bid": current_bid,
        "goldin_net": round(goldin_net, 2),
        "ebay_net": round(ebay_net, 2),
        "fmv": fmv_est,
        "confidence": confidence,
        "trend": trend,
        "vs_ebay": round(vs_ebay, 2),
        "floor": round(floor, 2),
        "floor_gap": round(floor_gap, 2),
        "floor_gap_pct": round(floor_gap_pct, 1),
        "verdict": verdict,
        "pop": pop,
        "scarce": 0 < pop < 10,
    }


def analyze_all(lots: list[dict]) -> list[dict]:
    """Analyze all lots from seller defense perspective."""
    return [analyze_lot(lot) for lot in lots]


def get_danger_lots(lots: list[dict]) -> list[dict]:
    """Get lots that need immediate defense — sorted by urgency."""
    results = analyze_all(lots)
    danger = [r for r in results if r["verdict"] in ("DANGER", "DEFEND")]
    danger.sort(key=lambda r: r["floor_gap_pct"])  # Most underwater first
    return danger


def get_safe_lots(lots: list[dict]) -> list[dict]:
    """Get lots that are above defense floor — no action needed."""
    results = analyze_all(lots)
    return [r for r in results if r["verdict"] in ("SAFE", "CLOSE")]


def refresh_live_bids(lots: list[dict], lot_urls: dict[int, str] | None = None) -> list[dict]:
    """Fetch live bids from Goldin and update lot data.

    Returns list of lots that had bid changes.
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
