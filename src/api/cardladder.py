"""CardLadder API client for fair market value and pricing data."""

import httpx

from config.settings import get_settings

BASE_URL = "https://api.cardladder.com/v1"


class CardLadderClient:
    """Client for the CardLadder pricing API."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.cardladder_api_key

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def get_fmv(
        self,
        player: str,
        year: int | None = None,
        brand: str | None = None,
        set_name: str | None = None,
        grade: float | None = None,
        sport: str = "basketball",
    ) -> dict | None:
        """Get fair market value for a card.

        Returns dict with keys: fmv, avg_30d, avg_90d, trend, confidence
        """
        params = {"player": player, "sport": sport}
        if year:
            params["year"] = year
        if brand:
            params["brand"] = brand
        if set_name:
            params["set"] = set_name
        if grade:
            params["grade"] = grade

        try:
            resp = httpx.get(
                f"{BASE_URL}/cards/fmv",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("results"):
                return None
            result = data["results"][0]
            return {
                "fmv": result.get("fmv", 0),
                "avg_30d": result.get("avg_30d", 0),
                "avg_90d": result.get("avg_90d", 0),
                "trend": result.get("trend", "stable"),  # up, down, stable
                "confidence": result.get("confidence", 0),
                "population": result.get("population", 0),
            }
        except httpx.HTTPError:
            return None

    def get_price_history(
        self,
        player: str,
        year: int | None = None,
        brand: str | None = None,
        grade: float | None = None,
        days: int = 365,
    ) -> list[dict]:
        """Get historical pricing data for a card."""
        params = {"player": player, "days": days}
        if year:
            params["year"] = year
        if brand:
            params["brand"] = brand
        if grade:
            params["grade"] = grade

        try:
            resp = httpx.get(
                f"{BASE_URL}/cards/history",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("prices", [])
        except httpx.HTTPError:
            return []

    def get_market_movers(self, sport: str = "basketball", limit: int = 20) -> list[dict]:
        """Get cards with biggest recent price movements."""
        try:
            resp = httpx.get(
                f"{BASE_URL}/market/movers",
                headers=self._headers(),
                params={"sport": sport, "limit": limit},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("movers", [])
        except httpx.HTTPError:
            return []

    def get_population(
        self,
        player: str,
        year: int | None = None,
        brand: str | None = None,
        grade: float | None = None,
    ) -> dict | None:
        """Get population/census data for a card."""
        params = {"player": player}
        if year:
            params["year"] = year
        if brand:
            params["brand"] = brand
        if grade:
            params["grade"] = grade

        try:
            resp = httpx.get(
                f"{BASE_URL}/cards/population",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return None
