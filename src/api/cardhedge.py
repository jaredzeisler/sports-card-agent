"""Card Hedge API client for card pricing and valuation."""

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
    ) -> list[dict]:
        """Search for cards by text query. Returns list of card results."""
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
            data = resp.json()
            return data.get("results", data) if isinstance(data, dict) else data
        except httpx.HTTPError:
            return []

    def get_price_estimate(
        self,
        card_id: str,
        grade: str | None = None,
    ) -> dict | None:
        """Get price estimate for a single card."""
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
            return data.get("results", data) if isinstance(data, dict) else data
        except httpx.HTTPError:
            return []

    def get_comps(self, card_id: str, grade: str | None = None) -> list[dict]:
        """Get comparable sold prices for a card."""
        body = {"card_id": card_id}
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
            data = resp.json()
            return data.get("results", data) if isinstance(data, dict) else data
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
            return data.get("prices", data) if isinstance(data, dict) else data
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
            return data.get("results", data) if isinstance(data, dict) else data
        except httpx.HTTPError:
            return []
