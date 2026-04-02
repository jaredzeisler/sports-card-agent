"""Goldin Auction Tracker — April 2026 lot data.

Each lot includes current bid, Goldin tier, card details, and an optional
Goldin URL for live bid fetching. Bids can be updated in-place via
update_bids_from_live() or manually by editing current_bid values.

Goldin charges ~20% buyer's premium on top of hammer price.
"""

GOLDIN_BUYER_PREMIUM = 0.20

# Map lot numbers to Goldin item URLs for live scraping.
# Populate these with the actual Goldin URLs for each lot.
LOT_URLS: dict[int, str] = {
    # Example: 1: "/item/shaq-nt-1-1-lasting-legacies-patch-auto-abc123",
}


def get_lot_url(lot_number: int) -> str | None:
    """Get the Goldin URL for a lot number."""
    return LOT_URLS.get(lot_number)


def update_bid(lot_number: int, new_bid: float) -> bool:
    """Update the current bid for a lot in-memory."""
    for lot in LOTS:
        if lot["lot"] == lot_number:
            lot["current_bid"] = new_bid
            return True
    return False


def update_bids_from_live(live_data: list[dict]) -> int:
    """Bulk-update bids from live Goldin scrape results.

    Args:
        live_data: List of dicts from GoldinClient.get_live_bids()
                   Each must have 'lot_number' and 'current_bid'.

    Returns:
        Number of lots updated.
    """
    updated = 0
    for entry in live_data:
        lot_num = entry.get("lot_number")
        bid = entry.get("current_bid", 0)
        if lot_num and bid > 0 and update_bid(lot_num, bid):
            updated += 1
    return updated


def get_lot(lot_number: int) -> dict | None:
    """Get a single lot by number."""
    for lot in LOTS:
        if lot["lot"] == lot_number:
            return lot
    return None


def get_lots_by_tier(tier: str) -> list[dict]:
    """Get all lots in a given tier (A, B, C, D)."""
    return [lot for lot in LOTS if lot["tier"] == tier.upper()]


def get_lots_by_player(player_name: str) -> list[dict]:
    """Get all lots for a player (case-insensitive partial match)."""
    name = player_name.lower()
    return [lot for lot in LOTS if name in lot["player"].lower()]


LOTS = [
    # ── Tier A — Flagship lots ──
    {"lot": 1, "card": "Shaq NT 1/1 Lasting Legacies Patch Auto", "tier": "A", "current_bid": 1588, "player": "Shaquille O'Neal", "brand": "National Treasures", "variation": "1/1 Patch Auto", "grade": None, "pop": 1},
    {"lot": 2, "card": "Curry 2009 Topps RC PSA 8", "tier": "A", "current_bid": 1051, "player": "Stephen Curry", "brand": "Topps", "variation": "Rookie", "grade": 8.0, "pop": None},
    {"lot": 3, "card": "Curry Kaleidoscopic Gold /10 PSA 10 Pop 4", "tier": "A", "current_bid": 1400, "player": "Stephen Curry", "brand": "Kaleidoscopic", "variation": "Gold /10", "grade": 10.0, "pop": 4},
    {"lot": 4, "card": "Wemby Bowman U Best Auto PSA 10", "tier": "A", "current_bid": 1401, "player": "Victor Wembanyama", "brand": "Bowman University", "variation": "Best Auto", "grade": 10.0, "pop": None},
    {"lot": 5, "card": "Ant Edwards One & One Blue RPA /35 PSA Auth/10", "tier": "A", "current_bid": 1512, "player": "Anthony Edwards", "brand": "One & One", "variation": "Blue RPA /35", "grade": 10.0, "pop": None},
    {"lot": 6, "card": "Mantle/Ruth/Gehrig Flawless Triple /15 PSA 10 Pop 2", "tier": "A", "current_bid": 1601, "player": "Mantle/Ruth/Gehrig", "brand": "Flawless", "variation": "Triple /15", "grade": 10.0, "pop": 2},
    {"lot": 7, "card": "Curry NT Clutch Factor /25 PSA 9 Pop 4", "tier": "A", "current_bid": 803, "player": "Stephen Curry", "brand": "National Treasures", "variation": "Clutch Factor /25", "grade": 9.0, "pop": 4},

    # ── Tier B — Strong secondary lots ──
    {"lot": 8, "card": "Cooper Flagg Bowman Chrome U Auto PSA 10", "tier": "B", "current_bid": 910, "player": "Cooper Flagg", "brand": "Bowman Chrome U", "variation": "Auto", "grade": 10.0, "pop": None},
    {"lot": 9, "card": "Ant Edwards Optic Auto Choice PSA 10", "tier": "B", "current_bid": 775, "player": "Anthony Edwards", "brand": "Optic", "variation": "Auto Choice", "grade": 10.0, "pop": None},
    {"lot": 10, "card": "Ant Flawless Ruby Draft Gem /15", "tier": "B", "current_bid": 860, "player": "Anthony Edwards", "brand": "Flawless", "variation": "Ruby Draft Gem /15", "grade": None, "pop": 15},
    {"lot": 11, "card": "Kobe/MJ SP Dual Threads BGS 8.5", "tier": "B", "current_bid": 860, "player": "Kobe/MJ", "brand": "SP", "variation": "Dual Threads", "grade": 8.5, "pop": None},
    {"lot": 12, "card": "Luka Prizm Mojo Auto /25", "tier": "B", "current_bid": 810, "player": "Luka Doncic", "brand": "Prizm", "variation": "Mojo Auto /25", "grade": None, "pop": 25},
    {"lot": 13, "card": "Luka Courtside Gold /10 PSA 9", "tier": "B", "current_bid": 362, "player": "Luka Doncic", "brand": "Courtside", "variation": "Gold /10", "grade": 9.0, "pop": 10},
    {"lot": 14, "card": "AI Prizm Black Gold /10 PSA 10 Pop 2 Jersey #", "tier": "B", "current_bid": 680, "player": "Allen Iverson", "brand": "Prizm", "variation": "Black Gold /10 Jersey #", "grade": 10.0, "pop": 2},
    {"lot": 15, "card": "SGA NT Viewpoint Emerald /5", "tier": "B", "current_bid": 600, "player": "Shai Gilgeous-Alexander", "brand": "National Treasures", "variation": "Viewpoint Emerald /5", "grade": None, "pop": 5},
    {"lot": 16, "card": "SGA Immaculate Gold Patch Auto /10", "tier": "B", "current_bid": 450, "player": "Shai Gilgeous-Alexander", "brand": "Immaculate", "variation": "Gold Patch Auto /10", "grade": None, "pop": 10},
    {"lot": 17, "card": "Curry Regalia Patch Auto /15", "tier": "B", "current_bid": 450, "player": "Stephen Curry", "brand": "Regalia", "variation": "Patch Auto /15", "grade": None, "pop": 15},
    {"lot": 18, "card": "KD Flawless USA /10", "tier": "B", "current_bid": 285, "player": "Kevin Durant", "brand": "Flawless", "variation": "USA /10", "grade": None, "pop": 10},
    {"lot": 19, "card": "Wemby Mercury Gold Refractor /50 PSA 10", "tier": "B", "current_bid": 585, "player": "Victor Wembanyama", "brand": "Mercury", "variation": "Gold Refractor /50", "grade": 10.0, "pop": 50},
    {"lot": 20, "card": "Caitlin Clark Bowman U Red /10 Auto PSA 9", "tier": "B", "current_bid": 610, "player": "Caitlin Clark", "brand": "Bowman University", "variation": "Red /10 Auto", "grade": 9.0, "pop": 10},
    {"lot": 21, "card": "Jokic One & One Blue /49", "tier": "B", "current_bid": 235, "player": "Nikola Jokic", "brand": "One & One", "variation": "Blue /49", "grade": None, "pop": 49},
    {"lot": 22, "card": "Yao Ming Gold Standard Mother Lode /25 Auto", "tier": "B", "current_bid": 575, "player": "Yao Ming", "brand": "Gold Standard", "variation": "Mother Lode /25 Auto", "grade": None, "pop": 25},
    {"lot": 23, "card": "Tatum Contenders Optic Orange /15 PSA 10/10", "tier": "B", "current_bid": 415, "player": "Jayson Tatum", "brand": "Contenders Optic", "variation": "Orange /15", "grade": 10.0, "pop": None},
    {"lot": 24, "card": "Giannis All Kings PSA 9", "tier": "B", "current_bid": 475, "player": "Giannis Antetokounmpo", "brand": "All Kings", "variation": "", "grade": 9.0, "pop": None},
    {"lot": 25, "card": "Giannis Select Tie-Dye /25 BGS 9.5/10", "tier": "B", "current_bid": 340, "player": "Giannis Antetokounmpo", "brand": "Select", "variation": "Tie-Dye /25", "grade": 9.5, "pop": None},
    {"lot": 26, "card": "Curry One & One /25 BGS 9/10 Pop 3", "tier": "B", "current_bid": 160, "player": "Stephen Curry", "brand": "One & One", "variation": "/25", "grade": 9.0, "pop": 3},

    # ── Tier C — Mid-range lots ──
    {"lot": 27, "card": "Luka NT Treasured Sigs /25 PSA 9", "tier": "C", "current_bid": 510, "player": "Luka Doncic", "brand": "National Treasures", "variation": "Treasured Sigs /25", "grade": 9.0, "pop": 25},
    {"lot": 28, "card": "Luka Immaculate Scorers Club /25 PSA 9", "tier": "C", "current_bid": 515, "player": "Luka Doncic", "brand": "Immaculate", "variation": "Scorers Club /25", "grade": 9.0, "pop": 25},
    {"lot": 29, "card": "Ant NT Private Signings PSA 9 Pop 4", "tier": "C", "current_bid": 211, "player": "Anthony Edwards", "brand": "National Treasures", "variation": "Private Signings", "grade": 9.0, "pop": 4},
    {"lot": 30, "card": "Ant Optic Fast Break Gold /10 PSA 9 Pop 3", "tier": "C", "current_bid": 250, "player": "Anthony Edwards", "brand": "Optic", "variation": "Fast Break Gold /10", "grade": 9.0, "pop": 3},
    {"lot": 31, "card": "Jeremy Lin 1/1 Gold Vinyl BGS 10/10", "tier": "C", "current_bid": 325, "player": "Jeremy Lin", "brand": "Gold Vinyl", "variation": "1/1", "grade": 10.0, "pop": 1},
    {"lot": 32, "card": "Roki Sasaki Five Star /30 (#01/30)", "tier": "C", "current_bid": 155, "player": "Roki Sasaki", "brand": "Five Star", "variation": "/30 (#01/30)", "grade": None, "pop": 30},
    {"lot": 33, "card": "LeBron eTopps RC PSA 9", "tier": "C", "current_bid": 231, "player": "LeBron James", "brand": "eTopps", "variation": "Rookie", "grade": 9.0, "pop": None},
    {"lot": 34, "card": "Angel Reese Downtown PSA 10", "tier": "C", "current_bid": 265, "player": "Angel Reese", "brand": "Downtown", "variation": "", "grade": 10.0, "pop": None},
    {"lot": 35, "card": "Chet Flawless Excellence 1/1 Auto", "tier": "C", "current_bid": 120, "player": "Chet Holmgren", "brand": "Flawless", "variation": "Excellence 1/1 Auto", "grade": None, "pop": 1},
    {"lot": 36, "card": "Chet Eminence Gold /5 Auto", "tier": "C", "current_bid": 80, "player": "Chet Holmgren", "brand": "Eminence", "variation": "Gold /5 Auto", "grade": None, "pop": 5},
    {"lot": 37, "card": "Vince Carter Exquisite /30 BGS 9/10", "tier": "C", "current_bid": 160, "player": "Vince Carter", "brand": "Exquisite", "variation": "/30", "grade": 9.0, "pop": 30},
    {"lot": 38, "card": "Dr. J Flawless Gold /10 BGS 8", "tier": "C", "current_bid": 152, "player": "Julius Erving", "brand": "Flawless", "variation": "Gold /10", "grade": 8.0, "pop": 10},
    {"lot": 39, "card": "Dr. J Exquisite Sigs /30 PSA 9", "tier": "C", "current_bid": 121, "player": "Julius Erving", "brand": "Exquisite", "variation": "Sigs /30", "grade": 9.0, "pop": 30},
    {"lot": 40, "card": "Kobe/LeBron/Oscar 3 Star Swatches BGS 8", "tier": "C", "current_bid": 198, "player": "Kobe/LeBron/Oscar", "brand": "3 Star Swatches", "variation": "", "grade": 8.0, "pop": None},
    {"lot": 41, "card": "AD Immaculate Red Patch Auto /15", "tier": "C", "current_bid": 102, "player": "Anthony Davis", "brand": "Immaculate", "variation": "Red Patch Auto /15", "grade": None, "pop": 15},
    {"lot": 42, "card": "Maxey Absolute 3 Swatch /199 PSA 8 Pop 2", "tier": "C", "current_bid": 228, "player": "Tyrese Maxey", "brand": "Absolute", "variation": "3 Swatch /199", "grade": 8.0, "pop": 2},
    {"lot": 43, "card": "Maxey Silhouette NBA Gear Gold /10 BGS 8", "tier": "C", "current_bid": 145, "player": "Tyrese Maxey", "brand": "Silhouette", "variation": "NBA Gear Gold /10", "grade": 8.0, "pop": 10},
    {"lot": 44, "card": "KAT Flawless Vault Mem /25 PSA 8", "tier": "C", "current_bid": 215, "player": "Karl-Anthony Towns", "brand": "Flawless", "variation": "Vault Mem /25", "grade": 8.0, "pop": 25},
    {"lot": 45, "card": "Wemby Select Red Cracked Ice PSA 10", "tier": "C", "current_bid": 161, "player": "Victor Wembanyama", "brand": "Select", "variation": "Red Cracked Ice", "grade": 10.0, "pop": None},
    {"lot": 46, "card": "Luka Spectra Neon Pink /25 PSA 9", "tier": "C", "current_bid": 145, "player": "Luka Doncic", "brand": "Spectra", "variation": "Neon Pink /25", "grade": 9.0, "pop": 25},
    {"lot": 47, "card": "Giannis Flawless Premium Ink /25 BGS 9.5/10", "tier": "C", "current_bid": 155, "player": "Giannis Antetokounmpo", "brand": "Flawless", "variation": "Premium Ink /25", "grade": 9.5, "pop": 25},
    {"lot": 48, "card": "Giannis Obsidian Matrix Yellow /10 PSA 9", "tier": "C", "current_bid": 130, "player": "Giannis Antetokounmpo", "brand": "Obsidian", "variation": "Matrix Yellow /10", "grade": 9.0, "pop": 10},
    {"lot": 49, "card": "Yamamoto NPB Chrome Orange /25 PSA 9", "tier": "C", "current_bid": 160, "player": "Yoshinobu Yamamoto", "brand": "NPB Chrome", "variation": "Orange /25", "grade": 9.0, "pop": 25},
    {"lot": 50, "card": "Magic Johnson ATG /50 BGS 9.5", "tier": "C", "current_bid": 67, "player": "Magic Johnson", "brand": "ATG", "variation": "/50", "grade": 9.5, "pop": 50},
    {"lot": 51, "card": "Curry VIP Gold Memorabilia /5 BGS 8", "tier": "C", "current_bid": 14, "player": "Stephen Curry", "brand": "VIP Gold", "variation": "Memorabilia /5", "grade": 8.0, "pop": 5},
    {"lot": 52, "card": "Curry VIP Cracked Ice /50 BGS 9.5", "tier": "C", "current_bid": 30, "player": "Stephen Curry", "brand": "VIP", "variation": "Cracked Ice /50", "grade": 9.5, "pop": 50},
    {"lot": 53, "card": "Curry Prizm Swatches Orange Ice BGS Auth", "tier": "C", "current_bid": 105, "player": "Stephen Curry", "brand": "Prizm", "variation": "Swatches Orange Ice", "grade": None, "pop": None},
    {"lot": 54, "card": "Curry Prestige True Colors BGS 9", "tier": "C", "current_bid": 42, "player": "Stephen Curry", "brand": "Prestige", "variation": "True Colors", "grade": 9.0, "pop": None},
    {"lot": 55, "card": "Ray Allen Immaculate Ink Red /25 PSA 8", "tier": "C", "current_bid": 10, "player": "Ray Allen", "brand": "Immaculate", "variation": "Ink Red /25", "grade": 8.0, "pop": 25},

    # ── Tier D — Value lots ──
    {"lot": 56, "card": "Yao Crusade Green & Gold /25 PSA 10", "tier": "D", "current_bid": 34, "player": "Yao Ming", "brand": "Crusade", "variation": "Green & Gold /25", "grade": 10.0, "pop": 25},
    {"lot": 57, "card": "Yao Pristine Refractor BGS 9.5", "tier": "D", "current_bid": 16, "player": "Yao Ming", "brand": "Pristine", "variation": "Refractor", "grade": 9.5, "pop": None},
    {"lot": 58, "card": "Caitlin Clark VIP PSA 8", "tier": "D", "current_bid": 40, "player": "Caitlin Clark", "brand": "VIP", "variation": "", "grade": 8.0, "pop": None},
    {"lot": 59, "card": "Paolo Banchero Recon Purple /25 PSA 8/10", "tier": "D", "current_bid": 26, "player": "Paolo Banchero", "brand": "Recon", "variation": "Purple /25", "grade": 8.0, "pop": 25},
    {"lot": 60, "card": "VJ Edgecombe Panini Instant /99", "tier": "D", "current_bid": 52, "player": "VJ Edgecombe", "brand": "Panini Instant", "variation": "/99", "grade": None, "pop": 99},
    {"lot": 61, "card": "VJ Edgecombe Prizm DP Blue Ice /75 SGC 10/10", "tier": "D", "current_bid": 75, "player": "VJ Edgecombe", "brand": "Prizm DP", "variation": "Blue Ice /75", "grade": 10.0, "pop": 75},
    {"lot": 62, "card": "Hannah Hidalgo Bowman U Purple /25 PSA 9", "tier": "D", "current_bid": 22, "player": "Hannah Hidalgo", "brand": "Bowman University", "variation": "Purple /25", "grade": 9.0, "pop": 25},
]
