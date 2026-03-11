"""eBay listing scanner — finds listings below FMV using the card catalog.

For each target player, searches eBay and attempts to match each listing
against the SportsCardsPro catalog to determine FMV and % below FMV.
"""

import base64
import re
import time
from datetime import datetime, timezone, timedelta

import httpx

from config.settings import get_settings
from config.targets import ALL_PLAYERS
from src.engine.catalog import load_catalog, get_player_cards

MAX_HOURS = 12  # only show auctions ending within this window

# Junk listing keywords to filter
JUNK_KEYWORDS = [
    "mystery", "repack", "break", "chase pack", "hot pack",
    "digital", "read desc", "read description",
    "case hit", "lot of", "pick your",
    "magazine", "poster", "book ", "program", "ticket stub",
    "display case", "holder only", "empty box",
]

# Non-PSA grading companies
NON_PSA_GRADERS = ["bgs", "cgc", "sgc", "wcg", "hga", "ags", "csg", "gma"]

# Grade keywords to detect in titles
GRADE_PATTERNS = {
    "psa_10": [r"\bpsa\s*10\b"],
    "psa_9": [r"\bpsa\s*9\b"],
    "psa_8": [r"\bpsa\s*8\b"],
    "psa_7": [r"\bpsa\s*7\b"],
    "bgs_10": [r"\bbgs\s*10\b", r"\bbeckett\s*10\b"],
    "sgc_10": [r"\bsgc\s*10\b"],
    "raw": [],  # default if no grade detected
}


def _get_ebay_token(settings) -> str:
    """Get eBay OAuth application token."""
    creds = base64.b64encode(
        f"{settings.ebay_app_id}:{settings.ebay_cert_id}".encode()
    ).decode()
    resp = httpx.post(
        settings.ebay_auth_url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {creds}",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _is_junk(title: str) -> str | None:
    """Check if listing is junk. Returns reason or None."""
    t = title.lower()
    for kw in JUNK_KEYWORDS:
        if kw in t:
            return kw
    return None


def _detect_grade(title: str) -> str:
    """Detect grade from listing title. Returns grade key (e.g., 'psa_10', 'raw')."""
    t = title.lower()
    for grade_key, patterns in GRADE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, t):
                return grade_key
    # Check for non-PSA graders
    for grader in NON_PSA_GRADERS:
        if re.search(rf"\b{grader}\s*\d", t):
            return f"{grader}_graded"
    return "raw"


def _match_listing_to_catalog(title: str, player: str, catalog_cards: list[dict]) -> dict | None:
    """Try to match an eBay listing title to a card in the catalog.

    Matching strategy:
    1. Extract card number from title (e.g., #136, #280)
    2. Extract set keywords from title
    3. Match against catalog entries by card number + set name

    Returns the best matching catalog card or None.
    """
    t = title.lower()

    # Must contain player name (last name at minimum)
    last_name = player.split()[-1].lower()
    if last_name not in t:
        return None

    # Extract all card numbers from title
    title_numbers = set(re.findall(r"#(\d+(?:-\w+)?)", t))

    best_match = None
    best_score = 0

    for card in catalog_cards:
        pname = card.get("product_name", "").lower()
        sname = card.get("set_name", "").lower()
        score = 0

        # Extract card number from catalog product name
        cat_nums = set(re.findall(r"#(\d+(?:-\w+)?)", pname))

        # Card number match is strong signal
        if cat_nums and title_numbers:
            if cat_nums & title_numbers:
                score += 10
            else:
                continue  # wrong card number, skip

        # Check if set name keywords appear in title
        # e.g., "2023 Panini Prizm" -> look for "prizm" in title
        set_words = re.findall(r"\b\w{4,}\b", sname)
        for word in set_words:
            if word in t and word not in ("cards", "basketball", "football", "panini"):
                score += 2

        # Check for parallel/variation match
        # Catalog product names use [brackets] for parallels
        bracket_match = re.search(r"\[(.+?)\]", pname)
        if bracket_match:
            parallel = bracket_match.group(1).lower()
            parallel_words = parallel.split()
            for pw in parallel_words:
                if pw in t:
                    score += 3
                else:
                    score -= 2  # penalty for parallel not in title
        else:
            # Base card — penalize if title has known parallel keywords
            parallel_kws = [
                "silver", "gold", "green", "blue", "red", "purple", "pink",
                "orange", "ice", "wave", "refractor", "mojo", "disco",
                "fast break", "hyper", "pulsar", "shimmer", "camo",
            ]
            for pk in parallel_kws:
                if pk in t:
                    score -= 3
                    break

        if score > best_score:
            best_score = score
            best_match = card

    if best_score >= 5:
        return best_match
    return None


def _parse_end_time(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    iso_str = iso_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_str)
    except ValueError:
        return None


def _hours_left(end_dt: datetime | None) -> float:
    if not end_dt:
        return 999.0
    return (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600


def scan_player(
    player: str,
    sport: str,
    catalog_cards: list[dict],
    ebay_headers: dict,
    settings,
    max_hours: int = MAX_HOURS,
) -> list[dict]:
    """Scan eBay for a single player's listings and match against catalog.

    Returns list of matched listing dicts with FMV comparison.
    """
    results = []
    base_url = f"{settings.ebay_base_url}/buy/browse/v1/item_summary/search"

    for listing_type, buy_filter, sort in [
        ("auction", "buyingOptions:{AUCTION}", "endingSoonest"),
        ("bin", "buyingOptions:{FIXED_PRICE}", "price"),
    ]:
        try:
            # Search eBay with player name + graded
            queries = [
                f"{player} PSA card",
                f"{player} raw card",
            ]

            for query in queries:
                resp = httpx.get(
                    base_url,
                    headers=ebay_headers,
                    params={
                        "q": query,
                        "limit": 50,
                        "filter": buy_filter,
                        "sort": sort,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                items = resp.json().get("itemSummaries", [])

                for item in items:
                    title = item.get("title", "")

                    # Filter junk
                    junk_reason = _is_junk(title)
                    if junk_reason:
                        continue

                    # For auctions, check end time
                    if listing_type == "auction":
                        end_dt = _parse_end_time(item.get("itemEndDate"))
                        h_left = _hours_left(end_dt)
                        if h_left > max_hours:
                            continue
                    else:
                        end_dt = None
                        h_left = 0

                    # Detect grade
                    grade = _detect_grade(title)

                    # Match to catalog
                    match = _match_listing_to_catalog(title, player, catalog_cards)
                    if not match:
                        continue

                    # Get price
                    if listing_type == "auction":
                        bp = item.get("currentBidPrice") or item.get("price", {})
                    else:
                        bp = item.get("price", {})
                    price = float(bp.get("value", 0))

                    # Get FMV for the matched grade
                    fmv = match.get("prices", {}).get(grade)
                    if not fmv or fmv <= 0:
                        # Try raw as fallback
                        fmv = match.get("prices", {}).get("raw")
                    if not fmv or fmv <= 0:
                        continue

                    pct_below = ((fmv - price) / fmv) * 100

                    results.append({
                        "player": player,
                        "sport": sport,
                        "listing_type": listing_type,
                        "title": title,
                        "price": price,
                        "grade": grade,
                        "fmv": fmv,
                        "pct_below_fmv": round(pct_below, 1),
                        "matched_card": match.get("product_name", ""),
                        "matched_set": match.get("set_name", ""),
                        "scp_id": match.get("scp_id", ""),
                        "bids": item.get("bidCount", 0),
                        "hours_left": round(h_left, 1) if listing_type == "auction" else None,
                        "end_time": end_dt.isoformat() if end_dt else None,
                        "ebay_item_id": item.get("itemId", ""),
                        "listing_url": item.get("itemWebUrl", ""),
                        "sales_volume": match.get("sales_volume", 0),
                    })

                time.sleep(0.5)  # be nice to eBay

        except Exception as e:
            print(f"  Error scanning {player} ({listing_type}): {e}")

    return results


def scan_all(
    catalog: dict | None = None,
    players: dict[str, list[str]] | None = None,
    max_hours: int = MAX_HOURS,
) -> list[dict]:
    """Scan all target players against the catalog.

    Args:
        catalog: Card catalog. If None, loads from disk.
        players: Player dict to scan. If None, uses ALL_PLAYERS.
        max_hours: Only include auctions ending within this many hours.

    Returns list of all matched listings sorted by pct_below_fmv descending.
    """
    if catalog is None:
        catalog = load_catalog()
    if catalog is None:
        raise ValueError("No catalog found. Run catalog build first.")

    if players is None:
        players = ALL_PLAYERS

    settings = get_settings()
    token = _get_ebay_token(settings)
    ebay_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    all_results = []
    total_players = sum(len(plist) for plist in players.values())
    player_num = 0

    for sport, player_list in players.items():
        for player in player_list:
            player_num += 1
            catalog_cards = get_player_cards(catalog, player)
            if not catalog_cards:
                print(f"[{player_num}/{total_players}] {player} — no catalog data, skipping")
                continue

            # Only use cards that have prices
            priced_cards = [c for c in catalog_cards if c.get("prices")]
            print(f"[{player_num}/{total_players}] {player} — scanning ({len(priced_cards)} cards in catalog)...", end=" ", flush=True)

            results = scan_player(
                player=player,
                sport=sport,
                catalog_cards=priced_cards,
                ebay_headers=ebay_headers,
                settings=settings,
                max_hours=max_hours,
            )

            print(f"{len(results)} matches")
            all_results.extend(results)

    # Sort: highest % below FMV first
    all_results.sort(key=lambda r: -r["pct_below_fmv"])
    return all_results


def print_results(results: list[dict], min_pct: float = -999):
    """Print scan results in a readable format."""
    filtered = [r for r in results if r["pct_below_fmv"] >= min_pct]

    if not filtered:
        print("No results found.")
        return

    print(f"\n{'='*110}")
    print(f"{'% FMV':>7} {'Price':>9} {'FMV':>9} {'Grade':<7} {'Type':<8} {'Player':<24} {'Matched Card':<40}")
    print(f"{'='*110}")

    for r in filtered:
        pct = r["pct_below_fmv"]
        typ = r["listing_type"].upper()
        time_str = ""
        if r["listing_type"] == "auction" and r.get("hours_left") is not None:
            time_str = f" ({r['hours_left']}h, {r['bids']}bid)"

        print(
            f"{pct:>+6.0f}% ${r['price']:>8.2f} ${r['fmv']:>8.2f} "
            f"{r['grade']:<7} {typ:<8} {r['player']:<24} "
            f"{r['matched_card'][:40]}"
        )
        if time_str:
            print(f"        {time_str}")
        # Show title on next line for verification
        print(f"        {r['title'][:90]}")
