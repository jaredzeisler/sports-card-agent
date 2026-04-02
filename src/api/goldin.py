"""Goldin Auctions client for fetching live bid data.

Goldin does not offer a public REST API, so this client scrapes
their auction pages to extract current bid prices and lot metadata.
"""

import re
import httpx

from config.settings import get_settings

GOLDIN_BASE_URL = "https://goldin.co"
BUYER_PREMIUM_RATE = 0.20  # 20% buyer's premium


class GoldinClient:
    """Client for fetching live Goldin auction data."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.base_url = GOLDIN_BASE_URL
        self._session_cookie: str | None = getattr(self.settings, "goldin_session_cookie", "") or None

    def _headers(self) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self._session_cookie:
            headers["Cookie"] = self._session_cookie
        return headers

    def get_auction_lot(self, lot_url: str) -> dict | None:
        """Fetch a single auction lot page and extract bid data.

        Args:
            lot_url: Full URL or path like '/item/2024-cooper-flagg-bowman-...'

        Returns:
            dict with: title, current_bid, bid_count, time_remaining, lot_number, url
        """
        if not lot_url.startswith("http"):
            lot_url = f"{self.base_url}{lot_url}"

        try:
            resp = httpx.get(lot_url, headers=self._headers(), timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return self._parse_lot_page(resp.text, lot_url)
        except httpx.HTTPError:
            return None

    def get_auction_listings(self, auction_url: str) -> list[dict]:
        """Fetch all lots from a Goldin auction page.

        Args:
            auction_url: Full URL or path like '/auctions/2026-april-elite'

        Returns:
            List of lot dicts with: title, current_bid, lot_number, url
        """
        if not auction_url.startswith("http"):
            auction_url = f"{self.base_url}{auction_url}"

        try:
            resp = httpx.get(auction_url, headers=self._headers(), timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return self._parse_auction_page(resp.text)
        except httpx.HTTPError:
            return []

    def get_live_bids(self, lot_urls: list[str]) -> list[dict]:
        """Fetch live bid data for multiple lots.

        Args:
            lot_urls: List of lot URLs or paths

        Returns:
            List of dicts with bid data for each lot
        """
        results = []
        for url in lot_urls:
            lot_data = self.get_auction_lot(url)
            if lot_data:
                lot_data["all_in_cost"] = round(
                    lot_data["current_bid"] * (1 + BUYER_PREMIUM_RATE), 2
                )
                results.append(lot_data)
        return results

    def _parse_lot_page(self, html: str, url: str) -> dict | None:
        """Extract bid data from a Goldin lot page HTML."""
        result = {"url": url}

        # Extract title
        title_match = re.search(r'<h1[^>]*class="[^"]*lot-title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if not title_match:
            title_match = re.search(r"<title>(.*?)</title>", html)
        result["title"] = _clean_html(title_match.group(1)) if title_match else "Unknown"

        # Extract current bid — look for common patterns in auction HTML
        bid = self._extract_bid(html)
        result["current_bid"] = bid

        # Bid count
        bid_count_match = re.search(r'(\d+)\s*bids?', html, re.IGNORECASE)
        result["bid_count"] = int(bid_count_match.group(1)) if bid_count_match else 0

        # Time remaining
        time_match = re.search(r'([\dhms\s]+)\s*(?:remaining|left)', html, re.IGNORECASE)
        result["time_remaining"] = time_match.group(1).strip() if time_match else "unknown"

        # Lot number
        lot_match = re.search(r'[Ll]ot\s*#?\s*(\d+)', html)
        result["lot_number"] = int(lot_match.group(1)) if lot_match else None

        return result

    def _extract_bid(self, html: str) -> float:
        """Extract current bid price from HTML using multiple strategies."""
        # Strategy 1: JSON-LD structured data
        json_bid = re.search(r'"currentBid"[:\s]*["\']?\$?([\d,]+\.?\d*)', html)
        if json_bid:
            return _parse_price(json_bid.group(1))

        # Strategy 2: data attribute
        data_bid = re.search(r'data-(?:current-)?bid[=:]["\']?\$?([\d,]+\.?\d*)', html)
        if data_bid:
            return _parse_price(data_bid.group(1))

        # Strategy 3: "Current Bid" label near a price
        current_bid_match = re.search(
            r'[Cc]urrent\s*[Bb]id[^$]*\$\s*([\d,]+\.?\d*)', html
        )
        if current_bid_match:
            return _parse_price(current_bid_match.group(1))

        # Strategy 4: "Winning Bid" label
        winning_match = re.search(
            r'[Ww]inning\s*[Bb]id[^$]*\$\s*([\d,]+\.?\d*)', html
        )
        if winning_match:
            return _parse_price(winning_match.group(1))

        # Strategy 5: largest dollar amount on the page (last resort)
        all_prices = re.findall(r'\$([\d,]+\.?\d*)', html)
        if all_prices:
            prices = [_parse_price(p) for p in all_prices]
            prices = [p for p in prices if p > 0]
            if prices:
                return max(prices)

        return 0.0

    def _parse_auction_page(self, html: str) -> list[dict]:
        """Extract all lot summaries from an auction listing page."""
        lots = []

        # Look for lot card/item patterns
        lot_blocks = re.findall(
            r'<(?:div|a)[^>]*class="[^"]*(?:lot-card|auction-item|item-card)[^"]*"[^>]*>(.*?)</(?:div|a)>',
            html,
            re.DOTALL,
        )

        for block in lot_blocks:
            lot = {}

            # Title
            title_match = re.search(r'<(?:h[2-4]|span|div)[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</', block, re.DOTALL)
            lot["title"] = _clean_html(title_match.group(1)) if title_match else "Unknown"

            # Price
            price_match = re.search(r'\$([\d,]+\.?\d*)', block)
            lot["current_bid"] = _parse_price(price_match.group(1)) if price_match else 0

            # Lot number
            lot_match = re.search(r'[Ll]ot\s*#?\s*(\d+)', block)
            lot["lot_number"] = int(lot_match.group(1)) if lot_match else None

            # Link
            link_match = re.search(r'href="([^"]*)"', block)
            lot["url"] = link_match.group(1) if link_match else None

            if lot["current_bid"] > 0:
                lots.append(lot)

        return lots


def _clean_html(text: str) -> str:
    """Strip HTML tags and excess whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_price(price_str: str) -> float:
    """Parse a price string like '1,588.00' to float."""
    cleaned = price_str.replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0
