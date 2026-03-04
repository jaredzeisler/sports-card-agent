"""SportsCardsPro (PriceCharting) API client for card pricing.

API docs: https://www.sportscardspro.com/api-documentation
Base URL: https://www.sportscardspro.com/api
Auth: ?t= query parameter with API token
Rate limit: 1 request per second

Price fields are in CENTS (divide by 100 for dollars).
Grade-to-field mapping:
  loose-price    = Ungraded / Raw
  cib-price      = PSA 7 / BGS 7
  new-price      = PSA 8 / BGS 8
  graded-price   = PSA 9 / BGS 9
  box-only-price = PSA 9.5 / BGS 9.5
  manual-only-price = PSA 10
  bgs-10-price   = BGS 10
"""

import httpx

from config.settings import get_settings

BASE_URL = "https://www.sportscardspro.com/api"

# Map numeric grade -> API price field
GRADE_PRICE_FIELD = {
    7: "cib-price",
    7.5: "cib-price",      # closest match
    8: "new-price",
    8.5: "new-price",      # closest match
    9: "graded-price",
    9.5: "box-only-price",
    10: "manual-only-price",
}


class SportsCardsProClient:
    """Client for the SportsCardsPro pricing API."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.sportscardspro_api_key

    def _params(self, extra: dict | None = None) -> dict:
        params = {"t": self.api_key}
        if extra:
            params.update(extra)
        return params

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search for cards. Returns list of product dicts."""
        try:
            resp = httpx.get(
                f"{BASE_URL}/products",
                params=self._params({"q": query, "limit": limit}),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("products", [])
        except httpx.HTTPError:
            return []

    def get_product(self, query: str) -> dict | None:
        """Get single best-match product for a query."""
        try:
            resp = httpx.get(
                f"{BASE_URL}/product",
                params=self._params({"q": query}),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data
            return None
        except httpx.HTTPError:
            return None

    def get_product_by_id(self, product_id: str) -> dict | None:
        """Get product by SportsCardsPro ID."""
        try:
            resp = httpx.get(
                f"{BASE_URL}/product",
                params=self._params({"id": product_id}),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data
            return None
        except httpx.HTTPError:
            return None

    @staticmethod
    def _product_matches_card(product: dict, player: str, year: int | None,
                              brand: str | None, set_name: str | None) -> bool:
        """Verify the returned product actually matches our card.

        Checks that the product name contains the player name and at least
        one of brand/set_name. This prevents a vague query like
        "2019 LeBron James" from matching a $15 base card when we need
        a National Treasures patch auto.
        """
        name = (product.get("product-name") or "").lower()
        console = (product.get("console-name") or "").lower()
        combined = f"{name} {console}"

        # Player name must appear
        player_lower = player.lower()
        # Check last name at minimum (handles "LeBron James" vs "James, LeBron")
        last_name = player_lower.split()[-1] if player_lower else ""
        if last_name and last_name not in combined:
            return False

        # If we have a set_name or brand, at least one should appear
        if set_name:
            set_lower = set_name.lower()
            # Check each meaningful word (skip short words like "of", "the")
            set_words = [w for w in set_lower.split() if len(w) > 3]
            if set_words and not any(w in combined for w in set_words):
                return False
        elif brand:
            if brand.lower() not in combined:
                return False

        return True

    def get_fmv(
        self,
        player: str,
        year: int | None = None,
        brand: str | None = None,
        set_name: str | None = None,
        grade: float | None = None,
        grading_company: str | None = None,
        card_number: str | None = None,
        variation: str | None = None,
    ) -> dict | None:
        """Get FMV for a card based on recent sold prices.

        Returns dict with: fmv, grade_used, price_field, product_name,
        set_name, product_id, sales_volume, all_prices
        """
        # Build search query — include variation/parallel for accurate match
        parts = []
        if year:
            parts.append(str(year))
        if set_name:
            parts.append(set_name)
        elif brand:
            parts.append(brand)
        parts.append(player)
        if variation:
            parts.append(variation)
        if card_number:
            parts.append(f"#{card_number}")
        query = " ".join(parts)

        product = self.get_product(query)

        # Validate the match — reject if the product doesn't match our card
        if product and not self._product_matches_card(product, player, year, brand, set_name):
            product = None

        if not product:
            # Retry with brand + set if we have both (more specific than year+player)
            if brand and set_name:
                broader = f"{year or ''} {brand} {set_name} {player}".strip()
                product = self.get_product(broader)
                if product and not self._product_matches_card(product, player, year, brand, set_name):
                    product = None

        if not product:
            # Last resort: year + player only — but still validate
            broader = f"{year or ''} {player}".strip()
            product = self.get_product(broader)
            if product and not self._product_matches_card(product, player, year, brand, set_name):
                product = None

        if not product:
            return None

        # Determine which price field to use based on grade
        if grade and grade >= 7:
            # Use BGS 10 field if grading company is BGS and grade is 10
            if grading_company and "BGS" in grading_company.upper() and grade == 10:
                price_field = "bgs-10-price"
            else:
                price_field = GRADE_PRICE_FIELD.get(grade, "graded-price")
        elif grade and grade < 7:
            # Below PSA 7 — use ungraded as proxy
            price_field = "loose-price"
        else:
            # Ungraded
            price_field = "loose-price"

        price_cents = product.get(price_field, 0)
        if not price_cents:
            # Fall back to loose if graded price not available
            price_cents = product.get("loose-price", 0)
            price_field = "loose-price"

        if not price_cents:
            return None

        fmv = price_cents / 100.0

        # Collect all grade prices for reference
        all_prices = {}
        for field, label in [
            ("loose-price", "ungraded"),
            ("cib-price", "PSA 7"),
            ("new-price", "PSA 8"),
            ("graded-price", "PSA 9"),
            ("box-only-price", "PSA 9.5"),
            ("manual-only-price", "PSA 10"),
            ("bgs-10-price", "BGS 10"),
        ]:
            val = product.get(field, 0)
            if val:
                all_prices[label] = val / 100.0

        return {
            "fmv": fmv,
            "grade_used": price_field,
            "product_name": product.get("product-name", ""),
            "set_name": product.get("console-name", ""),
            "product_id": product.get("id", ""),
            "sales_volume": int(product.get("sales-volume", 0)),
            "all_prices": all_prices,
            "query": query,
        }
