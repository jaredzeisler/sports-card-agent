"""Fanatics Collect browser automation client.

Uses Playwright to:
  1. Log in with stored credentials
  2. Search the weekly auction for cards matching criteria
  3. Place max bids on auctions (proxy bid model)
  4. Monitor bid status (winning/outbid/ended)

Fanatics Collect uses a 20% buyer's premium on top of the hammer price.
The bid input on the site is the HAMMER price — the premium is shown
separately as a total.
"""

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

from config.settings import get_settings

# Playwright is imported lazily to avoid import errors when not installed
_BROWSER_STATE_DIR = Path.home() / ".cardagent" / "fanatics_browser_state"

BASE_URL = "https://www.fanaticscollect.com"
LOGIN_URL = f"{BASE_URL}/login"
MARKETPLACE_URL = f"{BASE_URL}/marketplace"


class FanaticsClient:
    """Browser automation client for Fanatics Collect auctions."""

    def __init__(self, settings=None, headless: bool = True):
        self.settings = settings or get_settings()
        self.headless = headless
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self):
        """Launch browser if not already running."""
        if self._page:
            return

        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)

        # Use persistent state to keep login session across runs
        _BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._context = await self._browser.new_context(
            storage_state=str(_BROWSER_STATE_DIR / "state.json")
            if (_BROWSER_STATE_DIR / "state.json").exists()
            else None,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()

    async def _save_state(self):
        """Save browser state (cookies, localStorage) for session reuse."""
        if self._context:
            _BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(
                path=str(_BROWSER_STATE_DIR / "state.json")
            )

    async def close(self):
        """Close browser and save state."""
        if self._context:
            await self._save_state()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw") and self._pw:
            await self._pw.stop()
        self._page = None
        self._context = None
        self._browser = None

    # ── Authentication ──────────────────────────────────────────────

    async def login(self) -> bool:
        """Log in to Fanatics Collect. Returns True if successful."""
        await self._ensure_browser()
        page = self._page

        email = self.settings.fanatics_email
        password = self.settings.fanatics_password
        if not email or not password:
            raise ValueError(
                "FANATICS_EMAIL and FANATICS_PASSWORD must be set in .env"
            )

        # Check if already logged in
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Look for indicators of being logged in (avatar, account menu, etc.)
        logged_in = await page.query_selector(
            '[data-testid="user-menu"], [data-testid="account-menu"], '
            '.user-avatar, .account-dropdown, a[href*="account"], '
            'button:has-text("My Account")'
        )
        if logged_in:
            print("  Already logged in to Fanatics Collect")
            await self._save_state()
            return True

        # Navigate to login
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Fill login form — try common selectors
        email_input = await page.query_selector(
            'input[type="email"], input[name="email"], '
            'input[placeholder*="email" i], input[id*="email" i]'
        )
        password_input = await page.query_selector(
            'input[type="password"], input[name="password"], '
            'input[placeholder*="password" i], input[id*="password" i]'
        )

        if not email_input or not password_input:
            # Try iframe-based login (some sites embed auth in iframe)
            frames = page.frames
            for frame in frames:
                email_input = await frame.query_selector(
                    'input[type="email"], input[name="email"]'
                )
                password_input = await frame.query_selector(
                    'input[type="password"], input[name="password"]'
                )
                if email_input and password_input:
                    break

        if not email_input or not password_input:
            print("  Could not find login form fields")
            return False

        await email_input.fill(email)
        await password_input.fill(password)

        # Submit
        submit = await page.query_selector(
            'button[type="submit"], button:has-text("Sign In"), '
            'button:has-text("Log In"), button:has-text("Login")'
        )
        if submit:
            await submit.click()
        else:
            await password_input.press("Enter")

        # Wait for navigation / login to complete
        await page.wait_for_timeout(5000)

        # Verify login succeeded
        logged_in = await page.query_selector(
            '[data-testid="user-menu"], .user-avatar, '
            'a[href*="account"], button:has-text("My Account")'
        )
        if logged_in:
            print("  Successfully logged in to Fanatics Collect")
            await self._save_state()
            return True

        # Check for error messages
        error = await page.query_selector(
            '.error-message, .alert-error, [role="alert"]'
        )
        if error:
            error_text = await error.inner_text()
            print(f"  Login failed: {error_text}")
        else:
            print("  Login may have failed — could not confirm logged-in state")

        return False

    # ── Auction Search ──────────────────────────────────────────────

    async def search_auctions(
        self,
        query: str,
        auction_type: str = "WEEKLY",
    ) -> list[dict]:
        """Search for auction listings matching a query.

        Returns list of dicts with: auction_id, title, current_price,
        auction_url, image_url, end_time, bid_count
        """
        await self._ensure_browser()
        page = self._page

        # Navigate to marketplace with search
        url = f"{MARKETPLACE_URL}?type={auction_type}"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Find and fill search box
        search_input = await page.query_selector(
            'input[type="search"], input[placeholder*="search" i], '
            'input[name="search"], input[aria-label*="search" i], '
            'input[data-testid*="search" i]'
        )
        if search_input:
            await search_input.fill(query)
            await search_input.press("Enter")
            await page.wait_for_timeout(3000)
        else:
            # Try URL-based search
            await page.goto(
                f"{url}&q={query.replace(' ', '+')}",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(3000)

        # Scrape auction cards from results
        results = []
        cards = await page.query_selector_all(
            '[data-testid*="listing"], [data-testid*="card"], '
            '.listing-card, .auction-item, .product-card, '
            'a[href*="/item/"], a[href*="/lot/"], a[href*="/listing/"]'
        )

        for card in cards[:50]:  # Limit to 50 results
            try:
                item = await self._parse_auction_card(card)
                if item:
                    results.append(item)
            except Exception:
                continue

        return results

    async def _parse_auction_card(self, element) -> dict | None:
        """Extract auction data from a listing card element."""
        # Get the link/URL
        href = await element.get_attribute("href")
        if not href:
            link = await element.query_selector("a[href]")
            if link:
                href = await link.get_attribute("href")
        if not href:
            return None

        if not href.startswith("http"):
            href = f"{BASE_URL}{href}"

        # Extract auction ID from URL
        auction_id = href.rstrip("/").split("/")[-1]

        # Get title
        title_el = await element.query_selector(
            "h2, h3, h4, .title, .item-title, "
            '[data-testid*="title"], .product-name'
        )
        title = await title_el.inner_text() if title_el else ""

        # Get current price
        price_el = await element.query_selector(
            '.price, .current-bid, [data-testid*="price"], '
            '.bid-amount, .auction-price'
        )
        price_text = await price_el.inner_text() if price_el else "0"
        price = self._parse_price(price_text)

        # Get image
        img = await element.query_selector("img")
        image_url = await img.get_attribute("src") if img else None

        return {
            "auction_id": auction_id,
            "title": title.strip(),
            "current_price": price,
            "auction_url": href,
            "image_url": image_url,
        }

    # ── Bidding ─────────────────────────────────────────────────────

    async def get_auction_details(self, auction_url: str) -> dict | None:
        """Navigate to an auction page and extract details.

        Returns dict with: auction_id, title, current_price, bid_count,
        end_time, description, seller
        """
        await self._ensure_browser()
        page = self._page

        await page.goto(auction_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        title_el = await page.query_selector(
            "h1, .listing-title, .item-title, "
            '[data-testid*="title"]'
        )
        title = await title_el.inner_text() if title_el else ""

        # Current price/bid
        price_el = await page.query_selector(
            '.current-bid, .winning-bid, [data-testid*="current-bid"], '
            '[data-testid*="price"], .bid-amount'
        )
        price_text = await price_el.inner_text() if price_el else "0"
        current_price = self._parse_price(price_text)

        # Bid count
        bid_count_el = await page.query_selector(
            '.bid-count, [data-testid*="bid-count"], '
            ':text-matches("\\\\d+ bids?")'
        )
        bid_count_text = await bid_count_el.inner_text() if bid_count_el else "0"
        bid_count = int(re.search(r"\d+", bid_count_text).group()) if re.search(r"\d+", bid_count_text) else 0

        # End time
        time_el = await page.query_selector(
            '.time-remaining, .countdown, [data-testid*="time"], '
            '[data-testid*="countdown"], .auction-timer'
        )
        end_time_text = await time_el.inner_text() if time_el else None

        return {
            "auction_id": auction_url.rstrip("/").split("/")[-1],
            "title": title.strip(),
            "current_price": current_price,
            "bid_count": bid_count,
            "end_time_text": end_time_text,
            "auction_url": auction_url,
        }

    async def place_bid(self, auction_url: str, max_bid: float) -> dict:
        """Place a maximum bid on an auction.

        The max_bid is the HAMMER price (before buyer's premium).
        Fanatics uses proxy bidding — your max is kept private.

        Returns dict with: success, message, bid_placed, current_price
        """
        await self._ensure_browser()
        page = self._page

        await page.goto(auction_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Find bid input
        bid_input = await page.query_selector(
            'input[data-testid*="bid"], input[name*="bid"], '
            'input[placeholder*="bid" i], input[type="number"][aria-label*="bid" i], '
            'input[id*="bid" i]'
        )
        if not bid_input:
            return {
                "success": False,
                "message": "Could not find bid input field",
                "bid_placed": 0,
                "current_price": 0,
            }

        # Clear and enter bid amount
        await bid_input.click(click_count=3)  # Select all
        await bid_input.fill(str(int(max_bid)))  # Fanatics uses whole dollar bids

        # Find and click the place bid button
        bid_button = await page.query_selector(
            'button:has-text("Place Bid"), button:has-text("Bid"), '
            'button[data-testid*="bid"], button[type="submit"]:near(input[name*="bid"])'
        )
        if not bid_button:
            return {
                "success": False,
                "message": "Could not find Place Bid button",
                "bid_placed": 0,
                "current_price": 0,
            }

        await bid_button.click()
        await page.wait_for_timeout(2000)

        # Check for confirmation dialog
        confirm_button = await page.query_selector(
            'button:has-text("Confirm"), button:has-text("Yes"), '
            'button:has-text("Place Bid"):visible'
        )
        if confirm_button:
            await confirm_button.click()
            await page.wait_for_timeout(3000)

        # Check for success/error
        error_el = await page.query_selector(
            '.error, .alert-error, [role="alert"]:has-text("error"), '
            '.bid-error, [data-testid*="error"]'
        )
        if error_el:
            error_text = await error_el.inner_text()
            return {
                "success": False,
                "message": f"Bid error: {error_text}",
                "bid_placed": max_bid,
                "current_price": 0,
            }

        # Check for success indicators
        success_el = await page.query_selector(
            '.success, .alert-success, :has-text("highest bidder"), '
            ':has-text("bid placed"), [data-testid*="success"]'
        )

        return {
            "success": True,
            "message": "Bid placed successfully" if success_el else "Bid submitted (confirm on site)",
            "bid_placed": max_bid,
            "current_price": max_bid,
        }

    async def get_my_bids(self) -> list[dict]:
        """Get all active bids for the logged-in user.

        Returns list of dicts with: auction_id, title, my_bid,
        current_price, status (winning/outbid), auction_url
        """
        await self._ensure_browser()
        page = self._page

        # Navigate to bids/activity page
        for path in ["/my-bids", "/account/bids", "/account/activity", "/mybids"]:
            await page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            # Check if page loaded (not a 404)
            content = await page.content()
            if "404" not in content and "not found" not in content.lower():
                break

        results = []
        bid_items = await page.query_selector_all(
            '.bid-item, .auction-item, [data-testid*="bid-item"], '
            'tr:has(td), .listing-card'
        )

        for item in bid_items:
            try:
                title_el = await item.query_selector(
                    ".title, h3, h4, .item-title, td:first-child"
                )
                title = await title_el.inner_text() if title_el else ""

                link = await item.query_selector("a[href]")
                href = await link.get_attribute("href") if link else ""
                if href and not href.startswith("http"):
                    href = f"{BASE_URL}{href}"

                # Status (winning/outbid)
                status_el = await item.query_selector(
                    ".status, .bid-status, [data-testid*='status']"
                )
                status = await status_el.inner_text() if status_el else "unknown"

                results.append({
                    "title": title.strip(),
                    "auction_url": href,
                    "status": status.strip().lower(),
                })
            except Exception:
                continue

        return results

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_price(text: str) -> float:
        """Parse a price string like '$1,234.56' into a float."""
        if not text:
            return 0.0
        cleaned = re.sub(r"[^\d.]", "", text)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0


def run_sync(coro):
    """Helper to run async Fanatics methods synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
