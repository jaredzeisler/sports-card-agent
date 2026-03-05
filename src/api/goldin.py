"""Goldin Auctions browser automation client.

Uses Playwright to:
  1. Log in with stored credentials
  2. Search current auctions for cards matching criteria
  3. Place max bids on lots (proxy bid model)
  4. Monitor bid status (winning/outbid/ended)

Goldin uses a 20% buyer's premium on top of the hammer price.
The bid input on the site is the HAMMER price.
"""

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

from config.settings import get_settings

_BROWSER_STATE_DIR = Path.home() / ".cardagent" / "goldin_browser_state"

BASE_URL = "https://goldin.co"
LOGIN_URL = f"{BASE_URL}/sign-in"
AUCTIONS_URL = f"{BASE_URL}/auctions"


class GoldinClient:
    """Browser automation client for Goldin auctions."""

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

        _BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = _BROWSER_STATE_DIR / "state.json"
        self._context = await self._browser.new_context(
            storage_state=str(state_file) if state_file.exists() else None,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()

    async def _save_state(self):
        """Save browser state for session reuse."""
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
        """Log in to Goldin via eBay SSO. Returns True if successful.

        Goldin supports "Sign in with eBay" — we use the eBay credentials
        from settings rather than requiring separate Goldin credentials.
        """
        await self._ensure_browser()
        page = self._page

        email = self.settings.goldin_email or self.settings.ebay_login_email
        password = self.settings.goldin_password or self.settings.ebay_login_password
        if not email or not password:
            raise ValueError(
                "Goldin login requires eBay credentials. "
                "Set EBAY_LOGIN_EMAIL and EBAY_LOGIN_PASSWORD in .env "
                "(or GOLDIN_EMAIL / GOLDIN_PASSWORD for a direct Goldin account)."
            )

        # Check if already logged in
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        logged_in = await page.query_selector(
            'a[href*="/account"], a[href*="/my-bids"], '
            'button:has-text("My Account"), button:has-text("Account"), '
            '[data-testid*="user"], [data-testid*="account"], '
            '.user-menu, .account-menu'
        )
        if logged_in:
            print("  Already logged in to Goldin")
            await self._save_state()
            return True

        # Navigate to sign-in page
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Try "Sign in with eBay" button first
        ebay_sso = await page.query_selector(
            'button:has-text("eBay"), a:has-text("eBay"), '
            'button:has-text("Sign in with eBay"), a:has-text("Sign in with eBay"), '
            '[data-testid*="ebay"], .ebay-login, .ebay-signin'
        )
        if ebay_sso:
            await ebay_sso.click()
            await page.wait_for_timeout(5000)

            # We may be on eBay's login page now — fill credentials there
            email_input = await page.query_selector(
                'input[type="email"], input[name="userid"], '
                'input[id="userid"], input[placeholder*="email" i]'
            )
            if email_input:
                await email_input.fill(email)
                # eBay login is often two-step: email first, then password
                continue_btn = await page.query_selector(
                    'button[type="submit"], button:has-text("Continue"), '
                    'button[id="signin-continue-btn"]'
                )
                if continue_btn:
                    await continue_btn.click()
                    await page.wait_for_timeout(3000)

                password_input = await page.query_selector(
                    'input[type="password"], input[name="pass"], '
                    'input[id="pass"], input[placeholder*="password" i]'
                )
                if password_input:
                    await password_input.fill(password)
                    submit = await page.query_selector(
                        'button[type="submit"], button:has-text("Sign in"), '
                        'button[id="sgnBt"]'
                    )
                    if submit:
                        await submit.click()
                    else:
                        await password_input.press("Enter")
                    await page.wait_for_timeout(5000)
        else:
            # Fall back to direct Goldin login form
            email_input = await page.query_selector(
                'input[type="email"], input[name="email"], '
                'input[placeholder*="email" i], input[id*="email" i], '
                'input[autocomplete="email"]'
            )
            password_input = await page.query_selector(
                'input[type="password"], input[name="password"], '
                'input[placeholder*="password" i], input[id*="password" i]'
            )

            if not email_input or not password_input:
                for frame in page.frames:
                    email_input = await frame.query_selector(
                        'input[type="email"], input[name="email"]'
                    )
                    password_input = await frame.query_selector(
                        'input[type="password"], input[name="password"]'
                    )
                    if email_input and password_input:
                        break

            if not email_input or not password_input:
                print("  Could not find Goldin login form fields")
                return False

            await email_input.fill(email)
            await password_input.fill(password)

            submit = await page.query_selector(
                'button[type="submit"], button:has-text("Sign In"), '
                'button:has-text("Log In"), button:has-text("Login")'
            )
            if submit:
                await submit.click()
            else:
                await password_input.press("Enter")
            await page.wait_for_timeout(5000)

        # Verify login
        logged_in = await page.query_selector(
            'a[href*="/account"], a[href*="/my-bids"], '
            'button:has-text("My Account"), [data-testid*="user"]'
        )
        if logged_in:
            print("  Successfully logged in to Goldin")
            await self._save_state()
            return True

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

    async def search_auctions(self, query: str) -> list[dict]:
        """Search for auction lots matching a query.

        Returns list of dicts with: auction_id, title, current_price,
        auction_url, image_url, end_time, bid_count
        """
        await self._ensure_browser()
        page = self._page

        # Navigate to auctions page
        await page.goto(AUCTIONS_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Try search input
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
                f"{AUCTIONS_URL}?search={query.replace(' ', '+')}",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(3000)

        # Scrape lot cards from results
        results = []
        cards = await page.query_selector_all(
            '[data-testid*="lot"], [data-testid*="card"], '
            '.lot-card, .auction-item, .product-card, '
            'a[href*="/item/"], a[href*="/lot/"], a[href*="/listing/"]'
        )

        for card in cards[:50]:
            try:
                item = await self._parse_lot_card(card)
                if item:
                    results.append(item)
            except Exception:
                continue

        return results

    async def _parse_lot_card(self, element) -> dict | None:
        """Extract lot data from a card element."""
        href = await element.get_attribute("href")
        if not href:
            link = await element.query_selector("a[href]")
            if link:
                href = await link.get_attribute("href")
        if not href:
            return None

        if not href.startswith("http"):
            href = f"{BASE_URL}{href}"

        auction_id = href.rstrip("/").split("/")[-1]

        # Title
        title_el = await element.query_selector(
            "h2, h3, h4, .title, .lot-title, .item-title, "
            '[data-testid*="title"], .product-name, p'
        )
        title = await title_el.inner_text() if title_el else ""

        # Current price
        price_el = await element.query_selector(
            '.price, .current-bid, [data-testid*="price"], '
            '.bid-amount, .auction-price, span:has-text("$")'
        )
        price_text = await price_el.inner_text() if price_el else "0"
        price = self._parse_price(price_text)

        # Image
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

    async def get_lot_details(self, lot_url: str) -> dict | None:
        """Navigate to a lot page and extract details."""
        await self._ensure_browser()
        page = self._page

        await page.goto(lot_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        title_el = await page.query_selector(
            "h1, .lot-title, .item-title, "
            '[data-testid*="title"]'
        )
        title = await title_el.inner_text() if title_el else ""

        price_el = await page.query_selector(
            '.current-bid, .winning-bid, [data-testid*="current-bid"], '
            '[data-testid*="price"], .bid-amount'
        )
        price_text = await price_el.inner_text() if price_el else "0"
        current_price = self._parse_price(price_text)

        bid_count_el = await page.query_selector(
            '.bid-count, [data-testid*="bid-count"], '
            ':text-matches("\\\\d+ bids?")'
        )
        bid_count_text = await bid_count_el.inner_text() if bid_count_el else "0"
        bid_count = int(m.group()) if (m := re.search(r"\d+", bid_count_text)) else 0

        time_el = await page.query_selector(
            '.time-remaining, .countdown, [data-testid*="time"], '
            '[data-testid*="countdown"], .auction-timer'
        )
        end_time_text = await time_el.inner_text() if time_el else None

        return {
            "auction_id": lot_url.rstrip("/").split("/")[-1],
            "title": title.strip(),
            "current_price": current_price,
            "bid_count": bid_count,
            "end_time_text": end_time_text,
            "auction_url": lot_url,
        }

    async def place_bid(self, lot_url: str, max_bid: float) -> dict:
        """Place a maximum bid on a Goldin lot.

        The max_bid is the HAMMER price (before 20% buyer's premium).

        Returns dict with: success, message, bid_placed, current_price
        """
        await self._ensure_browser()
        page = self._page

        await page.goto(lot_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Find bid input
        bid_input = await page.query_selector(
            'input[data-testid*="bid"], input[name*="bid"], '
            'input[placeholder*="bid" i], input[type="number"], '
            'input[id*="bid" i], input[placeholder*="$"]'
        )
        if not bid_input:
            return {
                "success": False,
                "message": "Could not find bid input field on Goldin lot page",
                "bid_placed": 0,
                "current_price": 0,
            }

        # Clear and enter bid
        await bid_input.click(click_count=3)
        await bid_input.fill(str(int(max_bid)))

        # Click Place Bid
        bid_button = await page.query_selector(
            'button:has-text("Place Bid"), button:has-text("Bid"), '
            'button:has-text("Submit Bid"), '
            'button[data-testid*="bid"], button[type="submit"]'
        )
        if not bid_button:
            return {
                "success": False,
                "message": "Could not find Place Bid button on Goldin",
                "bid_placed": 0,
                "current_price": 0,
            }

        await bid_button.click()
        await page.wait_for_timeout(2000)

        # Confirmation dialog
        confirm_button = await page.query_selector(
            'button:has-text("Confirm"), button:has-text("Yes"), '
            'button:has-text("Place Bid"):visible'
        )
        if confirm_button:
            await confirm_button.click()
            await page.wait_for_timeout(3000)

        # Check for error
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

        success_el = await page.query_selector(
            '.success, .alert-success, :has-text("highest bidder"), '
            ':has-text("bid placed"), :has-text("winning"), '
            '[data-testid*="success"]'
        )

        return {
            "success": True,
            "message": "Bid placed successfully" if success_el else "Bid submitted (confirm on site)",
            "bid_placed": max_bid,
            "current_price": max_bid,
        }

    async def get_my_bids(self) -> list[dict]:
        """Get all active bids for the logged-in user."""
        await self._ensure_browser()
        page = self._page

        # Try common bid history paths
        for path in ["/my-bids", "/account/bids", "/account/activity"]:
            await page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            content = await page.content()
            if "404" not in content and "not found" not in content.lower():
                break

        results = []
        bid_items = await page.query_selector_all(
            '.bid-item, .auction-item, [data-testid*="bid-item"], '
            'tr:has(td), .lot-card'
        )

        for item in bid_items:
            try:
                title_el = await item.query_selector(
                    ".title, h3, h4, .lot-title, td:first-child"
                )
                title = await title_el.inner_text() if title_el else ""

                link = await item.query_selector("a[href]")
                href = await link.get_attribute("href") if link else ""
                if href and not href.startswith("http"):
                    href = f"{BASE_URL}{href}"

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
