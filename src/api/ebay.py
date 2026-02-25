"""eBay API client for Browse, Order, and Inventory APIs."""

import base64
from datetime import datetime, timezone
import httpx

from config.settings import get_settings


class EbayClient:
    """Client for eBay REST APIs."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.ebay_base_url
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

    # ── Authentication ──────────────────────────────────────────────

    def _get_app_token(self) -> str:
        """Get an application (client credentials) OAuth token."""
        if self._access_token and self._token_expiry and datetime.now(timezone.utc) < self._token_expiry:
            return self._access_token

        credentials = base64.b64encode(
            f"{self.settings.ebay_app_id}:{self.settings.ebay_cert_id}".encode()
        ).decode()

        resp = httpx.post(
            self.settings.ebay_auth_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = datetime.now(timezone.utc)
        return self._access_token

    def _get_user_token(self) -> str:
        """Return the user OAuth token for actions that need user context."""
        return self.settings.ebay_user_token

    def _app_headers(self) -> dict:
        token = self._get_app_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

    def _user_headers(self) -> dict:
        token = self._get_user_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

    # ── Browse API ──────────────────────────────────────────────────

    def search_listings(
        self,
        query: str,
        min_price: float | None = None,
        max_price: float | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Search active eBay listings via the Browse API."""
        params = {"q": query, "limit": limit, "filter": "buyingOptions:{FIXED_PRICE}"}

        price_filters = []
        if min_price is not None:
            price_filters.append(f"price:[{min_price}..],priceCurrency:USD")
        if max_price is not None:
            price_filters.append(f"price:[..{max_price}],priceCurrency:USD")
        if price_filters:
            params["filter"] += "," + ",".join(price_filters)

        resp = httpx.get(
            f"{self.base_url}/buy/browse/v1/item_summary/search",
            headers=self._app_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("itemSummaries", [])

    def get_item(self, item_id: str) -> dict:
        """Get details for a specific listing."""
        resp = httpx.get(
            f"{self.base_url}/buy/browse/v1/item/{item_id}",
            headers=self._app_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_sold_comps(self, query: str, days: int = 90, limit: int = 50) -> list[dict]:
        """Search completed/sold listings for comparable pricing data."""
        params = {
            "q": query,
            "limit": limit,
            "filter": "buyingOptions:{FIXED_PRICE},conditions:{UNSPECIFIED}",
            "sort": "-price",
        }
        resp = httpx.get(
            f"{self.base_url}/buy/browse/v1/item_summary/search",
            headers=self._app_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("itemSummaries", [])

    # ── Order API (Buy) ─────────────────────────────────────────────

    def place_order(self, item_id: str, quantity: int = 1) -> dict:
        """Purchase an item via the Order API. Requires user token."""
        # Step 1: Initiate checkout
        checkout_resp = httpx.post(
            f"{self.base_url}/buy/order/v2/guest_checkout_session/initiate",
            headers=self._user_headers(),
            json={
                "lineItemInputs": [
                    {"itemId": item_id, "quantity": quantity}
                ]
            },
            timeout=30,
        )
        checkout_resp.raise_for_status()
        session = checkout_resp.json()
        session_id = session["checkoutSessionId"]

        # Step 2: Place the order
        order_resp = httpx.post(
            f"{self.base_url}/buy/order/v2/guest_checkout_session/{session_id}/place_order",
            headers=self._user_headers(),
            timeout=30,
        )
        order_resp.raise_for_status()
        return order_resp.json()

    # ── Sell / Inventory API ────────────────────────────────────────

    def create_listing(
        self,
        title: str,
        description: str,
        price: float,
        condition: str = "LIKE_NEW",
        category_id: str = "261328",  # Sports Trading Cards
        image_urls: list[str] | None = None,
        sku: str | None = None,
    ) -> dict:
        """Create a sell listing via the Inventory API."""
        sku = sku or f"card-{int(datetime.now(timezone.utc).timestamp())}"

        # Step 1: Create inventory item
        inventory_payload = {
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
            "condition": condition,
            "product": {
                "title": title,
                "description": description,
                "imageUrls": image_urls or [],
            },
        }
        inv_resp = httpx.put(
            f"{self.base_url}/sell/inventory/v1/inventory_item/{sku}",
            headers=self._user_headers(),
            json=inventory_payload,
            timeout=30,
        )
        inv_resp.raise_for_status()

        # Step 2: Create offer
        offer_payload = {
            "sku": sku,
            "marketplaceId": "EBAY_US",
            "format": "FIXED_PRICE",
            "listingDescription": description,
            "pricingSummary": {"price": {"value": str(price), "currency": "USD"}},
            "categoryId": category_id,
        }
        offer_resp = httpx.post(
            f"{self.base_url}/sell/inventory/v1/offer",
            headers=self._user_headers(),
            json=offer_payload,
            timeout=30,
        )
        offer_resp.raise_for_status()
        offer = offer_resp.json()
        offer_id = offer["offerId"]

        # Step 3: Publish
        pub_resp = httpx.post(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}/publish",
            headers=self._user_headers(),
            timeout=30,
        )
        pub_resp.raise_for_status()
        return pub_resp.json()

    # ── Order History (for import) ──────────────────────────────────

    def get_orders(self, days: int = 365, limit: int = 200) -> list[dict]:
        """Fetch recent purchase orders. Requires user token."""
        from datetime import timedelta

        date_from = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT00:00:00.000Z"
        )
        params = {
            "limit": limit,
            "filter": f"creationdate:[{date_from}..]",
        }
        resp = httpx.get(
            f"{self.base_url}/buy/order/v2/purchase_order",
            headers=self._user_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("orders", [])
