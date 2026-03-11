"""Scan eBay for all target players and find listings below FMV.

Usage:
    python scripts/scan.py                    # Scan all, show everything
    python scripts/scan.py --min-pct 10       # Only show listings >= 10% below FMV
    python scripts/scan.py --hours 6          # Auctions ending within 6 hours
    python scripts/scan.py --player "Luka Doncic"  # Scan single player
"""

import sys
import time
from datetime import datetime, timezone

from config.targets import ALL_PLAYERS
from src.engine.catalog import load_catalog
from src.engine.scanner import scan_all, print_results


def main():
    # Parse args
    min_pct = -999
    max_hours = 12
    single_player = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--min-pct" and i + 1 < len(args):
            min_pct = float(args[i + 1])
            i += 2
        elif args[i] == "--hours" and i + 1 < len(args):
            max_hours = int(args[i + 1])
            i += 2
        elif args[i] == "--player" and i + 1 < len(args):
            single_player = args[i + 1]
            i += 2
        else:
            i += 1

    # Load catalog
    catalog = load_catalog()
    if not catalog:
        print("No catalog found. Run 'python scripts/build_catalog.py --prices' first.")
        sys.exit(1)

    total_cards = sum(
        len(p["cards"]) for p in catalog["players"].values()
        if p.get("cards")
    )
    priced_cards = sum(
        len([c for c in p["cards"] if c.get("prices")])
        for p in catalog["players"].values()
        if p.get("cards")
    )
    print(f"Catalog: {len(catalog['players'])} players, {total_cards} cards, {priced_cards} with prices")
    print(f"Updated: {catalog.get('updated_at', '?')}")
    print(f"Settings: auctions ending within {max_hours}h, min % below FMV: {min_pct}")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # Filter to single player if requested
    players = ALL_PLAYERS
    if single_player:
        players = {}
        for sport, plist in ALL_PLAYERS.items():
            matching = [p for p in plist if single_player.lower() in p.lower()]
            if matching:
                players[sport] = matching
        if not players:
            print(f"Player '{single_player}' not found in targets.")
            sys.exit(1)

    start = time.time()
    results = scan_all(catalog=catalog, players=players, max_hours=max_hours)
    elapsed = time.time() - start

    print(f"\nScan complete: {len(results)} matched listings in {elapsed/60:.1f} min")
    print_results(results, min_pct=min_pct)


if __name__ == "__main__":
    main()
