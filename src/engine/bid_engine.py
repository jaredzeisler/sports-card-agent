"""Bid calculation engine — determines max bid based on FMV and player tier.

Tier 1 (top 25 most-traded players): bid up to 80% of FMV all-in
Tier 2 (everyone else): bid up to 60% of FMV all-in

"All-in" means the max you're willing to pay total (hammer + buyer's premium).
The engine back-calculates the max hammer bid from the all-in ceiling.
"""

# Buyer's premium rates by platform
BUYERS_PREMIUM = {
    "fanatics": 0.20,   # 20% buyer's premium
    "ebay": 0.0,        # eBay auctions: no buyer's premium
    "goldin": 0.20,     # Goldin: 20% buyer's premium
}

# FMV percentage ceilings by tier
TIER1_FMV_PCT = 0.80   # Top 25 players: bid up to 80% of FMV
TIER2_FMV_PCT = 0.60   # Everyone else: bid up to 60% of FMV

# Top 25 most-traded players in the hobby (by volume).
# Normalized to lowercase for matching.
TOP_25_PLAYERS = [
    "michael jordan",
    "lebron james",
    "luka doncic",
    "luka dončić",
    "victor wembanyama",
    "shohei ohtani",
    "kobe bryant",
    "stephen curry",
    "giannis antetokounmpo",
    "jayson tatum",
    "anthony edwards",
    "patrick mahomes",
    "lionel messi",
    "josh allen",
    "ja morant",
    "aaron judge",
    "mike trout",
    "ronald acuna jr",
    "ronald acuña jr",
    "lamar jackson",
    "cooper flagg",
    "joe burrow",
    "justin herbert",
    "tyrese maxey",
    "caitlin clark",
    "shai gilgeous-alexander",
    "nikola jokic",
    "nikola jokić",
    "connor mcdavid",
    "travis kelce",
]


def is_tier1_player(player_name: str) -> bool:
    """Check if a player is in the top-25 most-traded tier."""
    name = player_name.strip().lower()
    return any(top in name or name in top for top in TOP_25_PLAYERS)


def get_fmv_ceiling(player_name: str) -> float:
    """Get the FMV percentage ceiling for a player (0.80 or 0.60)."""
    return TIER1_FMV_PCT if is_tier1_player(player_name) else TIER2_FMV_PCT


def calculate_max_bid(
    fmv: float,
    player_name: str,
    platform: str = "fanatics",
    override_pct: float | None = None,
) -> dict:
    """Calculate the maximum hammer bid for an auction.

    Args:
        fmv: Fair market value of the card
        player_name: Player name (determines tier)
        platform: Auction platform (determines buyer's premium)
        override_pct: Override the FMV percentage (0.0-1.0)

    Returns dict with:
        max_all_in: Maximum total you'd pay (hammer + premium)
        max_hammer: Maximum hammer bid to place
        buyers_premium_rate: The platform's buyer's premium rate
        fmv_pct: The FMV percentage used
        tier: "tier1" or "tier2"
        fmv: The input FMV
    """
    if fmv <= 0:
        return {
            "max_all_in": 0,
            "max_hammer": 0,
            "buyers_premium_rate": 0,
            "fmv_pct": 0,
            "tier": "unknown",
            "fmv": fmv,
        }

    premium_rate = BUYERS_PREMIUM.get(platform, 0.0)
    fmv_pct = override_pct if override_pct is not None else get_fmv_ceiling(player_name)
    tier = "tier1" if is_tier1_player(player_name) else "tier2"

    # max_all_in = FMV * fmv_pct
    # max_all_in = max_hammer * (1 + premium_rate)
    # => max_hammer = (FMV * fmv_pct) / (1 + premium_rate)
    max_all_in = fmv * fmv_pct
    max_hammer = max_all_in / (1 + premium_rate)

    return {
        "max_all_in": round(max_all_in, 2),
        "max_hammer": round(max_hammer, 2),
        "buyers_premium_rate": premium_rate,
        "fmv_pct": fmv_pct,
        "tier": tier,
        "fmv": fmv,
    }


def should_bid(
    current_price: float,
    fmv: float,
    player_name: str,
    platform: str = "fanatics",
    hard_cap: float | None = None,
) -> dict:
    """Decide whether to bid on an auction at the current price.

    Returns dict with:
        bid: True/False
        max_hammer: Maximum hammer bid
        reason: Human-readable explanation
    """
    calc = calculate_max_bid(fmv, player_name, platform)

    if fmv <= 0:
        return {"bid": False, "max_hammer": 0, "reason": "No FMV available"}

    if hard_cap and calc["max_hammer"] > hard_cap:
        calc["max_hammer"] = hard_cap
        calc["max_all_in"] = hard_cap * (1 + calc["buyers_premium_rate"])

    if current_price >= calc["max_hammer"]:
        return {
            "bid": False,
            "max_hammer": calc["max_hammer"],
            "reason": (
                f"Current ${current_price:.2f} >= max bid ${calc['max_hammer']:.2f} "
                f"({calc['tier']}, {calc['fmv_pct']:.0%} of ${fmv:.2f} FMV)"
            ),
        }

    return {
        "bid": True,
        "max_hammer": calc["max_hammer"],
        "reason": (
            f"Bid up to ${calc['max_hammer']:.2f} "
            f"(all-in ${calc['max_all_in']:.2f} = {calc['fmv_pct']:.0%} of ${fmv:.2f} FMV, "
            f"{calc['tier']})"
        ),
    }
