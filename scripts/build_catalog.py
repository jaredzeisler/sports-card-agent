"""Build the card catalog — pulls all cards for all target players.

Usage:
    python scripts/build_catalog.py              # Fast build (names only, no prices)
    python scripts/build_catalog.py --prices     # Full build with prices (~67 min for 40 players)
    python scripts/build_catalog.py --refresh    # Refresh prices on existing catalog
"""

import sys
import time

from src.engine.catalog import (
    build_catalog,
    build_catalog_fast,
    refresh_prices,
    save_catalog,
    load_catalog,
)


def main():
    start = time.time()

    if "--refresh" in sys.argv:
        print("Loading existing catalog...")
        catalog = load_catalog()
        if not catalog:
            print("No existing catalog found. Run without --refresh first.")
            sys.exit(1)
        print(f"Refreshing prices for {sum(len(p['cards']) for p in catalog['players'].values())} cards...")
        catalog = refresh_prices(catalog)
        save_catalog(catalog)

    elif "--prices" in sys.argv:
        print("Building full catalog with prices (this will take a while)...")
        catalog = build_catalog()
        save_catalog(catalog)

    else:
        print("Building fast catalog (names only, no prices)...")
        catalog = build_catalog_fast()
        save_catalog(catalog)
        total = sum(len(p["cards"]) for p in catalog["players"].values())
        print(f"\nCatalog built: {len(catalog['players'])} players, {total} total cards")
        print(f"Run with --prices for full build, or --refresh to add prices later.")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed/60:.1f} minutes")


if __name__ == "__main__":
    main()
