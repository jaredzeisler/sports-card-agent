"""Goldin Auctions browser scraper — uses Playwright to fetch JS-rendered lot data.

Goldin's site is fully client-rendered (React/Redux). No public API.
This scraper launches a headless browser to load the page and extract lot data.

Requirements:
    pip install playwright
    python -m playwright install chromium

Usage:
    from src.api.goldin_browser import GoldinBrowserScraper
    scraper = GoldinBrowserScraper()
    lots = scraper.scrape_weekly_auction(category="Basketball Cards")
"""

import json
import re
import time


def scrape_weekly_auction(
    category: str = "Basketball Cards",
    max_pages: int = 10,
    sort: str = "Bid_Amount_asc",
    headless: bool = True,
) -> list[dict]:
    """Scrape all lots from Goldin's weekly auction.

    Args:
        category: Filter by category (e.g. "Basketball Cards", "Baseball Cards")
        max_pages: Maximum pages to scrape
        sort: Sort order
        headless: Run browser headless

    Returns:
        List of dicts: {title, current_bid, lot_url, bid_count, image_url}
    """
    from playwright.sync_api import sync_playwright

    all_lots = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        for page_num in range(1, max_pages + 1):
            url = (
                f"https://goldin.co/buy?"
                f"auction_type=Weekly"
                f"&category={category.replace(' ', '+')}"
                f"&page={page_num}"
                f"&sort={sort}"
            )

            page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait for lot cards to render
            page.wait_for_timeout(2000)

            # Try to find lot card elements
            cards = page.query_selector_all('[class*="lot-card"], [class*="item-card"], [class*="auction-item"], [data-testid*="lot"], [data-testid*="item"]')

            if not cards:
                # Fallback: look for any card-like containers with price data
                cards = page.query_selector_all('a[href*="/item/"]')

            if not cards:
                break  # No more lots

            for card in cards:
                lot = _extract_lot_from_element(card)
                if lot and lot.get("current_bid", 0) > 0:
                    all_lots.append(lot)

            # Check if there's a next page
            next_btn = page.query_selector('[aria-label="Next"], [class*="next-page"], button:has-text("Next")')
            if not next_btn or not next_btn.is_enabled():
                break

        browser.close()

    return all_lots


def _extract_lot_from_element(element) -> dict | None:
    """Extract lot data from a page element."""
    try:
        lot = {}

        # Title — try multiple selectors
        title_el = element.query_selector('h2, h3, h4, [class*="title"], [class*="name"]')
        lot["title"] = title_el.inner_text().strip() if title_el else element.inner_text().strip()[:100]

        # Current bid — look for dollar amounts
        text = element.inner_text()
        prices = re.findall(r'\$([\d,]+(?:\.\d{2})?)', text)
        if prices:
            lot["current_bid"] = float(prices[0].replace(",", ""))
        else:
            lot["current_bid"] = 0

        # URL
        href = element.get_attribute("href")
        if href:
            lot["lot_url"] = href if href.startswith("http") else f"https://goldin.co{href}"
        else:
            link = element.query_selector("a[href]")
            if link:
                href = link.get_attribute("href")
                lot["lot_url"] = href if href.startswith("http") else f"https://goldin.co{href}"

        # Bid count
        bid_match = re.search(r'(\d+)\s*bids?', text, re.IGNORECASE)
        lot["bid_count"] = int(bid_match.group(1)) if bid_match else 0

        # Image
        img = element.query_selector("img")
        lot["image_url"] = img.get_attribute("src") if img else None

        return lot
    except Exception:
        return None


def scrape_lot_detail(lot_url: str, headless: bool = True) -> dict | None:
    """Scrape detailed info from a single lot page.

    Returns:
        Dict with: title, current_bid, bid_count, time_remaining, description, image_url
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        if not lot_url.startswith("http"):
            lot_url = f"https://goldin.co{lot_url}"

        page.goto(lot_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        text = page.inner_text("body")
        lot = {"url": lot_url}

        # Title
        title_el = page.query_selector('h1, [class*="lot-title"], [class*="item-title"]')
        lot["title"] = title_el.inner_text().strip() if title_el else "Unknown"

        # Current bid
        prices = re.findall(r'\$([\d,]+(?:\.\d{2})?)', text)
        if prices:
            lot["current_bid"] = max(float(p.replace(",", "")) for p in prices)
        else:
            lot["current_bid"] = 0

        # Bid count
        bid_match = re.search(r'(\d+)\s*bids?', text, re.IGNORECASE)
        lot["bid_count"] = int(bid_match.group(1)) if bid_match else 0

        # Time remaining
        time_match = re.search(r'(\d+[dhms]\s*)+(?:\s*remaining|\s*left)?', text, re.IGNORECASE)
        lot["time_remaining"] = time_match.group(0).strip() if time_match else "unknown"

        browser.close()

    return lot
