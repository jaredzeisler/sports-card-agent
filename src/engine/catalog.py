"""Card catalog builder — pulls all cards for target players from SportsCardsPro.

Builds a local catalog with FMV at every grade for each card product.
Designed to run once per day (SportsCardsPro prices update daily).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config.settings import get_settings
from config.targets import ALL_PLAYERS
from src.api.sportscardspro import SportsCardsProClient

CATALOG_DIR = Path("data/catalog")
CATALOG_FILE = CATALOG_DIR / "catalog.json"

# Grade fields from SportsCardsPro API
GRADE_FIELDS = {
    "raw": "loose-price",
    "psa_7": "cib-price",
    "psa_8": "new-price",
    "psa_9": "graded-price",
    "psa_9.5": "box-only-price",
    "psa_10": "manual-only-price",
    "bgs_10": "bgs-10-price",
    "cgc_10": "condition-17-price",
    "sgc_10": "condition-18-price",
}


def _extract_prices(product: dict) -> dict:
    """Extract all grade prices from a product, converting cents to dollars."""
    prices = {}
    for grade_key, api_field in GRADE_FIELDS.items():
        val = product.get(api_field)
        if val:
            prices[grade_key] = int(val) / 100.0
    return prices


def _extract_card_info(product: dict) -> dict:
    """Extract card info from a SportsCardsPro product search result."""
    return {
        "scp_id": product.get("id", ""),
        "product_name": product.get("product-name", ""),
        "set_name": product.get("console-name", ""),
    }


def build_catalog(players: dict[str, list[str]] | None = None, limit_per_player: int = 100) -> dict:
    """Build complete card catalog for all target players.

    Args:
        players: Dict of sport -> player list. Defaults to ALL_PLAYERS.
        limit_per_player: Max products to fetch per player from SportsCardsPro.

    Returns:
        Catalog dict with structure:
        {
            "updated_at": "...",
            "players": {
                "Victor Wembanyama": {
                    "sport": "basketball",
                    "cards": [
                        {
                            "scp_id": "6343314",
                            "product_name": "Victor Wembanyama #136",
                            "set_name": "Basketball Cards 2023 Panini Prizm",
                            "prices": {"raw": 31.50, "psa_9": 40.60, "psa_10": 160.00, ...}
                        },
                        ...
                    ]
                }
            }
        }
    """
    if players is None:
        players = ALL_PLAYERS

    settings = get_settings()
    scp = SportsCardsProClient(settings)

    catalog = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "players": {},
    }

    total_players = sum(len(plist) for plist in players.values())
    player_num = 0

    for sport, player_list in players.items():
        for player in player_list:
            player_num += 1
            print(f"[{player_num}/{total_players}] {player} ({sport})...", end=" ", flush=True)

            try:
                products = scp.search(player, limit=limit_per_player)
                time.sleep(1.1)  # rate limit

                cards = []
                for p in products:
                    info = _extract_card_info(p)

                    # Get full product data with prices (search only returns name/id/set)
                    full = scp.get_product_by_id(info["scp_id"])
                    time.sleep(1.1)  # rate limit

                    if not full:
                        continue

                    prices = _extract_prices(full)
                    if not prices:
                        continue  # skip cards with no price data

                    info["prices"] = prices
                    info["sales_volume"] = int(full.get("sales-volume", 0) or 0)
                    cards.append(info)

                catalog["players"][player] = {
                    "sport": sport,
                    "cards": cards,
                }
                print(f"{len(cards)} cards with prices")

            except Exception as e:
                print(f"ERROR: {e}")
                catalog["players"][player] = {
                    "sport": sport,
                    "cards": [],
                    "error": str(e),
                }

    return catalog


def build_catalog_fast(players: dict[str, list[str]] | None = None) -> dict:
    """Build catalog using only the search endpoint (no per-product lookups).

    Much faster (~1 API call per player instead of ~100), but search results
    only include id, product-name, and console-name — no prices.

    We then do a single /api/product call per card to get prices, but only
    for cards that have likely price data (skip obscure inserts).

    For the initial build, use build_catalog() for full data.
    For daily updates, use this + selective price refreshes.
    """
    if players is None:
        players = ALL_PLAYERS

    settings = get_settings()
    scp = SportsCardsProClient(settings)

    catalog = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "players": {},
    }

    total_players = sum(len(plist) for plist in players.values())
    player_num = 0

    for sport, player_list in players.items():
        for player in player_list:
            player_num += 1
            print(f"[{player_num}/{total_players}] {player} ({sport})...", end=" ", flush=True)

            try:
                products = scp.search(player, limit=100)
                time.sleep(1.1)

                cards = []
                for p in products:
                    cards.append({
                        "scp_id": p.get("id", ""),
                        "product_name": p.get("product-name", ""),
                        "set_name": p.get("console-name", ""),
                        "prices": {},  # filled in during price refresh
                        "sales_volume": 0,
                    })

                catalog["players"][player] = {
                    "sport": sport,
                    "cards": cards,
                }
                print(f"{len(cards)} cards")

            except Exception as e:
                print(f"ERROR: {e}")
                catalog["players"][player] = {
                    "sport": sport,
                    "cards": [],
                    "error": str(e),
                }

    return catalog


def refresh_prices(catalog: dict, min_volume: int = 0) -> dict:
    """Refresh prices for all cards in an existing catalog.

    Args:
        catalog: Existing catalog dict.
        min_volume: Only refresh cards with at least this sales volume (0 = all).

    Returns updated catalog.
    """
    settings = get_settings()
    scp = SportsCardsProClient(settings)

    total_cards = sum(
        len(pdata["cards"])
        for pdata in catalog["players"].values()
    )
    card_num = 0
    updated = 0

    for player, pdata in catalog["players"].items():
        for card in pdata["cards"]:
            card_num += 1
            scp_id = card.get("scp_id")
            if not scp_id:
                continue

            if min_volume > 0 and card.get("sales_volume", 0) < min_volume:
                continue

            try:
                full = scp.get_product_by_id(scp_id)
                time.sleep(1.1)

                if full:
                    card["prices"] = _extract_prices(full)
                    card["sales_volume"] = int(full.get("sales-volume", 0) or 0)
                    updated += 1

                if card_num % 50 == 0:
                    print(f"  [{card_num}/{total_cards}] refreshed {updated} prices...", flush=True)

            except Exception as e:
                print(f"  Error refreshing {scp_id}: {e}")

    catalog["updated_at"] = datetime.now(timezone.utc).isoformat()
    print(f"  Refreshed {updated}/{total_cards} card prices")
    return catalog


def save_catalog(catalog: dict, path: Path | None = None):
    """Save catalog to JSON file."""
    path = path or CATALOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(catalog, f, indent=2)
    print(f"Catalog saved to {path} ({path.stat().st_size / 1024:.0f} KB)")


def load_catalog(path: Path | None = None) -> dict | None:
    """Load catalog from JSON file."""
    path = path or CATALOG_FILE
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def get_player_cards(catalog: dict, player: str) -> list[dict]:
    """Get all cards for a player from the catalog."""
    pdata = catalog.get("players", {}).get(player)
    if not pdata:
        return []
    return pdata.get("cards", [])


def find_card_fmv(catalog: dict, player: str, product_name: str, grade: str = "psa_10") -> float | None:
    """Look up FMV for a specific card + grade from the catalog.

    Args:
        catalog: The loaded catalog.
        player: Player name.
        product_name: SportsCardsPro product name (e.g., "Victor Wembanyama #136").
        grade: Grade key (raw, psa_7, psa_8, psa_9, psa_9.5, psa_10, bgs_10).

    Returns FMV in dollars or None if not found.
    """
    cards = get_player_cards(catalog, player)
    for card in cards:
        if card.get("product_name") == product_name:
            return card.get("prices", {}).get(grade)
    return None
