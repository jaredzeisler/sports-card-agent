"""eBay API client for Browse, Order, Inventory, and Offer APIs."""

import base64
from datetime import datetime, timezone, timedelta
import httpx

from config.settings import get_settings
from src.api.ebay_auth import get_valid_user_token


class EbayClient:
    """Client for eBay REST APIs (search, buy, sell, manage listings)."""

    SPORTS_CARDS_CATEGORY = "261328"
    TEST_AUCTIONS_CATEGORY = "178993"  # Everything Else > Test Auctions > General
    EBAY_FEE_RATE = 0.1625  # ~16.25% final value + payment processing

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.ebay_base_url
        self._app_token: str | None = None
        self._app_token_expiry: datetime | None = None

    # ── Authentication ──────────────────────────────────────────────

    def _get_app_token(self) -> str:
        """Get an application (client credentials) OAuth token for Browse API."""
        if self._app_token and self._app_token_expiry and datetime.now(timezone.utc) < self._app_token_expiry:
            return self._app_token

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
        self._app_token = data["access_token"]
        self._app_token_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=data.get("expires_in", 7200) - 300
        )
        return self._app_token

    def _get_user_token(self) -> str:
        """Get a valid user token (auto-refreshes if needed)."""
        return get_valid_user_token(self.settings)

    def _app_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_app_token()}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

    def _user_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_user_token()}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

    # ── Browse API (search) ─────────────────────────────────────────

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
        return resp.json().get("itemSummaries", [])

    def get_item(self, item_id: str) -> dict:
        """Get details for a specific listing."""
        resp = httpx.get(
            f"{self.base_url}/buy/browse/v1/item/{item_id}",
            headers=self._app_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Order API (buy) ─────────────────────────────────────────────

    def place_order(self, item_id: str, quantity: int = 1) -> dict:
        """Purchase an item via the Order API. Requires user token."""
        checkout_resp = httpx.post(
            f"{self.base_url}/buy/order/v2/guest_checkout_session/initiate",
            headers=self._user_headers(),
            json={"lineItemInputs": [{"itemId": item_id, "quantity": quantity}]},
            timeout=30,
        )
        checkout_resp.raise_for_status()
        session_id = checkout_resp.json()["checkoutSessionId"]

        order_resp = httpx.post(
            f"{self.base_url}/buy/order/v2/guest_checkout_session/{session_id}/place_order",
            headers=self._user_headers(),
            timeout=30,
        )
        order_resp.raise_for_status()
        return order_resp.json()

    # ── Sell / Inventory API ────────────────────────────────────────

    def create_inventory_item(self, sku: str, card_data: dict, test_listing: bool = False) -> None:
        """Create or update an inventory item from card data.

        If test_listing=True, prepends 'Test' to title/description per eBay policy.

        card_data keys: title, description, condition, condition_descriptors,
                        image_urls, aspects
        """
        title = card_data["title"]
        description = card_data.get("description", "")
        if test_listing:
            if not title.lower().startswith("test"):
                title = f"Test - {title}"
            if not description.lower().startswith("test"):
                description = f"Test - {description}"

        payload = {
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
            "condition": card_data.get("condition", "4000"),
            "conditionDescription": card_data.get("condition_description", ""),
            "product": {
                "title": title,
                "description": description,
                "imageUrls": card_data.get("image_urls", []),
                "aspects": card_data.get("aspects", {}),
            },
        }

        # Add condition descriptors (required for graded cards since Oct 2023)
        if card_data.get("condition_descriptors"):
            payload["conditionDescriptors"] = card_data["condition_descriptors"]

        resp = httpx.put(
            f"{self.base_url}/sell/inventory/v1/inventory_item/{sku}",
            headers=self._user_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()

    def create_offer(
        self,
        sku: str,
        price: float,
        description: str = "",
        category_id: str | None = None,
        fulfillment_policy_id: str | None = None,
        return_policy_id: str | None = None,
        payment_policy_id: str | None = None,
        best_offer: bool = True,
        auto_accept_price: float | None = None,
        auto_decline_price: float | None = None,
        test_listing: bool = False,
    ) -> str:
        """Create an offer for an inventory item. Returns offer ID.

        If test_listing=True, uses Test Auctions category.
        """
        if test_listing and not category_id:
            category_id = self.TEST_AUCTIONS_CATEGORY

        payload: dict = {
            "sku": sku,
            "marketplaceId": "EBAY_US",
            "format": "FIXED_PRICE",
            "listingDescription": description,
            "pricingSummary": {
                "price": {"value": f"{price:.2f}", "currency": "USD"},
            },
            "categoryId": category_id or self.SPORTS_CARDS_CATEGORY,
            "listingPolicies": {},
        }

        if fulfillment_policy_id:
            payload["listingPolicies"]["fulfillmentPolicyId"] = fulfillment_policy_id
        if return_policy_id:
            payload["listingPolicies"]["returnPolicyId"] = return_policy_id
        if payment_policy_id:
            payload["listingPolicies"]["paymentPolicyId"] = payment_policy_id

        if best_offer:
            payload["pricingSummary"]["bestOfferEnabled"] = True
            if auto_accept_price:
                payload["pricingSummary"]["autoAcceptPrice"] = {
                    "value": f"{auto_accept_price:.2f}", "currency": "USD"
                }
            if auto_decline_price:
                payload["pricingSummary"]["minimumAdvertisedPrice"] = {
                    "value": f"{auto_decline_price:.2f}", "currency": "USD"
                }

        resp = httpx.post(
            f"{self.base_url}/sell/inventory/v1/offer",
            headers=self._user_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["offerId"]

    def publish_offer(self, offer_id: str) -> dict:
        """Publish an offer to make it a live listing. Returns listing ID."""
        resp = httpx.post(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}/publish",
            headers=self._user_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def create_listing(
        self,
        card_data: dict,
        price: float,
        sku: str | None = None,
        best_offer: bool = True,
        auto_accept_price: float | None = None,
        auto_decline_price: float | None = None,
        fulfillment_policy_id: str | None = None,
        return_policy_id: str | None = None,
        payment_policy_id: str | None = None,
        test_listing: bool = False,
    ) -> dict:
        """Full listing flow: create inventory item → offer → publish.

        card_data: dict from build_card_listing()
        If test_listing=True, uses Test Auctions category and 'Test' prefix per eBay policy.
        Returns: {"sku": ..., "offerId": ..., "listingId": ...}
        """
        sku = sku or f"card-{int(datetime.now(timezone.utc).timestamp())}"

        self.create_inventory_item(sku, card_data, test_listing=test_listing)

        offer_id = self.create_offer(
            sku=sku,
            price=price,
            description=card_data.get("description", ""),
            fulfillment_policy_id=fulfillment_policy_id,
            return_policy_id=return_policy_id,
            payment_policy_id=payment_policy_id,
            best_offer=best_offer,
            auto_accept_price=auto_accept_price,
            auto_decline_price=auto_decline_price,
            test_listing=test_listing,
        )

        result = self.publish_offer(offer_id)
        return {"sku": sku, "offerId": offer_id, "listingId": result.get("listingId")}

    # ── Listing Management ──────────────────────────────────────────

    def get_offers(self, sku: str | None = None, limit: int = 100) -> list[dict]:
        """Get all offers (optionally filtered by SKU)."""
        params = {"limit": limit}
        if sku:
            params["sku"] = sku
        resp = httpx.get(
            f"{self.base_url}/sell/inventory/v1/offer",
            headers=self._user_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("offers", [])

    def update_offer_price(self, offer_id: str, new_price: float) -> None:
        """Update the price on an existing offer."""
        # First get the current offer to preserve other fields
        resp = httpx.get(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}",
            headers=self._user_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        offer = resp.json()

        offer["pricingSummary"]["price"] = {
            "value": f"{new_price:.2f}", "currency": "USD"
        }

        # Remove read-only fields that can't be sent in update
        for key in ["offerId", "status", "listing"]:
            offer.pop(key, None)

        update_resp = httpx.put(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}",
            headers=self._user_headers(),
            json=offer,
            timeout=30,
        )
        update_resp.raise_for_status()

    def withdraw_offer(self, offer_id: str) -> None:
        """Withdraw (end) an offer/listing."""
        resp = httpx.post(
            f"{self.base_url}/sell/inventory/v1/offer/{offer_id}/withdraw",
            headers=self._user_headers(),
            timeout=30,
        )
        resp.raise_for_status()

    def delete_inventory_item(self, sku: str) -> None:
        """Delete an inventory item and its associated offers."""
        resp = httpx.delete(
            f"{self.base_url}/sell/inventory/v1/inventory_item/{sku}",
            headers=self._user_headers(),
            timeout=30,
        )
        resp.raise_for_status()

    def get_active_listings(self, limit: int = 100) -> list[dict]:
        """Get all inventory items (active listings)."""
        params = {"limit": limit}
        resp = httpx.get(
            f"{self.base_url}/sell/inventory/v1/inventory_item",
            headers=self._user_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("inventoryItems", [])

    # ── Offer Negotiation ───────────────────────────────────────────

    def get_selling_offers(self, listing_id: str) -> list[dict]:
        """Get buyer offers on a listing via the Offer API."""
        resp = httpx.get(
            f"{self.base_url}/sell/negotiation/v1/offer",
            headers=self._user_headers(),
            params={"listing_id": listing_id, "limit": 100},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("offers", [])

    def accept_offer(self, offer_id: str) -> dict:
        """Accept a buyer's offer."""
        resp = httpx.post(
            f"{self.base_url}/sell/negotiation/v1/offer/{offer_id}/accept",
            headers=self._user_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def decline_offer(self, offer_id: str) -> dict:
        """Decline a buyer's offer."""
        resp = httpx.post(
            f"{self.base_url}/sell/negotiation/v1/offer/{offer_id}/decline",
            headers=self._user_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def counter_offer(self, offer_id: str, price: float, message: str = "") -> dict:
        """Send a counter-offer to a buyer."""
        payload = {
            "counterOfferPrice": {"value": f"{price:.2f}", "currency": "USD"},
        }
        if message:
            payload["message"] = message
        resp = httpx.post(
            f"{self.base_url}/sell/negotiation/v1/offer/{offer_id}/counter",
            headers=self._user_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Account API (policies) ──────────────────────────────────────

    def get_fulfillment_policies(self) -> list[dict]:
        """Get seller's shipping/fulfillment policies."""
        resp = httpx.get(
            f"{self.base_url}/sell/account/v1/fulfillment_policy",
            headers=self._user_headers(),
            params={"marketplace_id": "EBAY_US"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("fulfillmentPolicies", [])

    def get_return_policies(self) -> list[dict]:
        """Get seller's return policies."""
        resp = httpx.get(
            f"{self.base_url}/sell/account/v1/return_policy",
            headers=self._user_headers(),
            params={"marketplace_id": "EBAY_US"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("returnPolicies", [])

    def get_payment_policies(self) -> list[dict]:
        """Get seller's payment policies."""
        resp = httpx.get(
            f"{self.base_url}/sell/account/v1/payment_policy",
            headers=self._user_headers(),
            params={"marketplace_id": "EBAY_US"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("paymentPolicies", [])

    # ── Seller Orders (Fulfillment API) ─────────────────────────────

    def get_seller_orders(self, days: int = 30, limit: int = 50) -> list[dict]:
        """Get recent sold items / orders as a seller."""
        date_from = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT00:00:00.000Z"
        )
        resp = httpx.get(
            f"{self.base_url}/sell/fulfillment/v1/order",
            headers=self._user_headers(),
            params={
                "limit": limit,
                "filter": f"creationdate:[{date_from}..]",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("orders", [])

    # ── Order History (for import / buying) ─────────────────────────

    def get_orders(self, days: int = 365, limit: int = 200) -> list[dict]:
        """Fetch recent purchase orders. Requires user token."""
        date_from = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT00:00:00.000Z"
        )
        resp = httpx.get(
            f"{self.base_url}/buy/order/v2/purchase_order",
            headers=self._user_headers(),
            params={"limit": limit, "filter": f"creationdate:[{date_from}..]"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("orders", [])
