"""Card Hedge API client for card pricing and valuation.

API docs: https://api.cardhedger.com/docs
Auth: X-API-Key header

Key flow for pricing a card in our inventory:
  1. search_card(query) -> get card_id from results
  2. get_comps(card_id, grade) -> get comp_price (FMV based on recent eBay sold)
"""

import httpx

from config.settings import get_settings

BASE_URL = "https://api.cardhedger.com/v1"


class CardHedgeClient:
    """Client for the Card Hedge pricing API."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.cardhedge_api_key

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def search_card(
        self,
        query: str,
        category: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """Search for cards by text query.

        Returns dict with:
          page (int), pages (int), cards (list of dicts)

        Each card has: card_id, description, player, set, number, variant,
        image, category, category_group, set_type, 90_day_sales, grade, price
        """
        body = {
            "query": query,
            "page": page,
            "page_size": page_size,
        }
        if category:
            body["category"] = category

        try:
            resp = httpx.post(
                f"{BASE_URL}/cards/card-search",
                headers=self._headers(),
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return {"page": 0, "pages": 0, "cards": []}

    def get_comps(
        self,
        card_id: str,
        grade: str | None = None,
        count: int = 5,
        time_weighted: bool = True,
    ) -> dict | None:
        """Get comparable sold prices for a card.

        Returns dict with:
          comp_price (float) - time-weighted average of recent eBay sold prices
          high (float), low (float) - price range
          count_used (int) - number of comps found
          raw_prices (list) - individual sales with price, sale_date, sale_type, title, sale_url
        """
        body = {
            "card_id": card_id,
            "count": count,
            "time_weighted": time_weighted,
        }
        if grade:
            body["grade"] = grade

        try:
            resp = httpx.post(
                f"{BASE_URL}/cards/comps",
                headers=self._headers(),
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return None

    def get_price_estimate(
        self,
        card_id: str,
        grade: str | None = None,
    ) -> dict | None:
        """Get price estimate with confidence score for a single card."""
        body = {"card_id": card_id}
        if grade:
            body["grade"] = grade

        try:
            resp = httpx.post(
                f"{BASE_URL}/cards/price-estimate",
                headers=self._headers(),
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return None

    def batch_price_estimate(self, items: list[dict]) -> list[dict]:
        """Get price estimates for up to 100 cards at once.

        Each item should have: card_id and optionally grade.
        """
        try:
            resp = httpx.post(
                f"{BASE_URL}/cards/batch-price-estimate",
                headers=self._headers(),
                json={"items": items[:100]},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", []) if isinstance(data, dict) else data
        except httpx.HTTPError:
            return []

    def get_prices_by_card(
        self,
        card_id: str,
        grade: str | None = None,
        days: int = 180,
    ) -> list[dict]:
        """Get price history for a card (up to 365 days)."""
        body = {"card_id": card_id, "days": min(days, 365)}
        if grade:
            body["grade"] = grade

        try:
            resp = httpx.post(
                f"{BASE_URL}/cards/prices-by-card",
                headers=self._headers(),
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("prices", []) if isinstance(data, dict) else data
        except httpx.HTTPError:
            return []

    def get_top_movers(self, count: int = 20, category: str | None = None) -> list[dict]:
        """Get cards with biggest positive price changes this week."""
        params = {"count": count}
        if category:
            params["category"] = category

        try:
            resp = httpx.get(
                f"{BASE_URL}/cards/top-movers",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", []) if isinstance(data, dict) else data
        except httpx.HTTPError:
            return []

    @staticmethod
    def _result_matches_card(result: dict, player: str, year: int | None,
                             brand: str | None, set_name: str | None) -> bool:
        """Verify a Card Hedge search result actually matches our card."""
        desc = (result.get("description") or "").lower()
        result_player = (result.get("player") or "").lower()
        result_set = (result.get("set") or "").lower()
        combined = f"{desc} {result_player} {result_set}"

        # Player last name must appear
        player_lower = player.lower()
        last_name = player_lower.split()[-1] if player_lower else ""
        if last_name and last_name not in combined:
            return False

        # If we have set_name or brand, check for it
        if set_name:
            set_words = [w for w in set_name.lower().split() if len(w) > 3]
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
        sport: str = "basketball",
    ) -> dict | None:
        """High-level: search for a card and get its FMV from comps.

        This is the main method for pricing inventory cards.
        Returns dict with: fmv, high, low, num_comps, card_id
        """
        # Build search query
        parts = [player]
        if year:
            parts.insert(0, str(year))
        if brand:
            parts.append(brand)
        if set_name:
            parts.append(set_name)
        query = " ".join(parts)

        # Map sport to Card Hedge category
        category_map = {
            "basketball": "Basketball",
            "baseball": "Baseball",
            "football": "Football",
            "soccer": "Soccer",
            "hockey": "Hockey",
        }
        category = category_map.get(sport)

        # Search for the card and pick the first result that actually matches
        search_result = self.search_card(query, category=category, page_size=5)
        cards = search_result.get("cards", [])
        if not cards:
            return None

        card = None
        for candidate in cards:
            if self._result_matches_card(candidate, player, year, brand, set_name):
                card = candidate
                break

        if not card:
            return None

        card_id = card.get("card_id")
        if not card_id:
            return None

        # Build grade string for comps (e.g. "PSA 10")
        grade_str = None
        if grade:
            grade_int = int(grade) if grade == int(grade) else grade
            grade_str = f"PSA {grade_int}"

        # Get comps (real eBay sold prices)
        comps = self.get_comps(card_id, grade=grade_str)
        if not comps or not comps.get("comp_price"):
            # Try without grade
            comps = self.get_comps(card_id)
            if not comps or not comps.get("comp_price"):
                return None

        return {
            "fmv": comps["comp_price"],
            "high": comps.get("high", 0),
            "low": comps.get("low", 0),
            "num_comps": comps.get("count_used", 0),
            "card_id": card_id,
            "card_description": card.get("description", ""),
        }
