"""Market scanner that finds deals on eBay using AI-powered title parsing."""

import re

from config.settings import get_settings
from src.api.ebay import EbayClient
from src.api.cardladder import CardLadderClient
from src.engine.pricing import calculate_fmv, get_ebay_market_price
from src.engine.analyzer import DealAnalyzer
from src.models.database import get_session
from src.models.card import Listing

# Default search queries — customize these for your trading focus
DEFAULT_SEARCHES = [
    "PSA 10 Luka Doncic Prizm rookie",
    "PSA 10 Jayson Tatum Prizm rookie",
    "PSA 10 Anthony Edwards Prizm rookie",
    "PSA 10 Victor Wembanyama Prizm rookie",
    "PSA 10 Ja Morant Prizm rookie",
    "PSA 9 LeBron James Topps Chrome rookie",
]


def parse_listing_title_regex(title: str) -> dict:
    """Parse an eBay listing title into structured card data using regex."""
    result = {
        "player": None,
        "year": None,
        "brand": None,
        "set_name": None,
        "grade": None,
        "variation": None,
        "sport": None,
    }

    # Year: 4-digit number between 1900-2030
    year_match = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title)
    if year_match:
        result["year"] = int(year_match.group(1))

    # Grade: PSA/BGS/SGC followed by number
    grade_match = re.search(r"\b(?:PSA|BGS|SGC|CGC)\s*(\d+\.?\d*)\b", title, re.IGNORECASE)
    if grade_match:
        result["grade"] = float(grade_match.group(1))

    # Brand detection
    brands = ["Panini", "Topps", "Upper Deck", "Bowman", "Donruss", "Fleer", "Hoops"]
    for brand in brands:
        if brand.lower() in title.lower():
            result["brand"] = brand
            break

    # Set detection
    sets = [
        "Prizm", "Select", "Mosaic", "Optic", "Chrome", "National Treasures",
        "Immaculate", "Spectra", "Court Kings", "Contenders", "Revolution",
        "Obsidian", "Origins", "Noir", "Flawless",
    ]
    for s in sets:
        if s.lower() in title.lower():
            result["set_name"] = s
            break

    # Variation detection
    variations = [
        "Silver", "Gold", "Red", "Blue", "Green", "Orange", "Purple", "Pink",
        "Black", "White", "Holo", "Refractor", "Wave", "Shimmer", "Mojo",
        "Ice", "Camo", "Tie-Dye", "Snakeskin", "Tiger", "Zebra",
        "Fast Break", "Disco", "Choice", "Hyper",
    ]
    for v in variations:
        if v.lower() in title.lower():
            result["variation"] = v
            break

    # Player: attempt to extract — remove known tokens and grab remaining proper nouns
    cleaned = title
    # Remove year, grade, brand, set, variation, common words
    remove_patterns = [
        r"\b\d{4}(-\d{2,4})?\b", r"\bPSA\s*\d+\b", r"\bBGS\s*\d+\b",
        r"\bSGC\s*\d+\b", r"\b#\d+\b", r"\bRC\b", r"\bRookie\b",
        r"\bCard\b", r"\bLot\b", r"\bNM\b", r"\bMint\b", r"\bGem\b",
    ]
    for pat in remove_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    # Remove brand/set/variation
    for token in brands + sets + variations:
        cleaned = re.sub(re.escape(token), "", cleaned, flags=re.IGNORECASE)
    # Remove special characters and extra whitespace
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned:
        result["player"] = cleaned

    return result


def parse_listing_title_llm(title: str, api_key: str) -> dict | None:
    """Parse an eBay listing title using Claude for better accuracy."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"Parse this sports card listing title into structured data. "
                    f"Return ONLY a JSON object with these keys: "
                    f"player, year (int), brand, set_name, grade (float), "
                    f"variation, sport. Use null for unknown fields.\n\n"
                    f"Title: {title}"
                ),
            }],
        )
        import json
        text = response.content[0].text.strip()
        # Extract JSON from response
        if "{" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(json_str)
    except Exception:
        return None
    return None


def parse_listing_title(title: str) -> dict:
    """Parse a listing title, using LLM if available, falling back to regex."""
    settings = get_settings()
    if settings.anthropic_api_key:
        llm_result = parse_listing_title_llm(title, settings.anthropic_api_key)
        if llm_result:
            return llm_result
    return parse_listing_title_regex(title)


class MarketScanner:
    """Scans eBay for card deals and evaluates them."""

    def __init__(self, searches: list[str] | None = None, settings=None):
        self.settings = settings or get_settings()
        self.searches = searches or DEFAULT_SEARCHES
        self.ebay = EbayClient(self.settings)
        self.cardladder = CardLadderClient(self.settings)
        self.analyzer = DealAnalyzer(self.settings)

        # Optional pricing clients for waterfall
        self._scp_client = None
        self._ch_client = None
        if self.settings.sportscardspro_api_key:
            from src.api.sportscardspro import SportsCardsProClient
            self._scp_client = SportsCardsProClient(self.settings)
        if self.settings.cardhedge_api_key:
            from src.api.cardhedge import CardHedgeClient
            self._ch_client = CardHedgeClient(self.settings)

    def scan(self, dry_run: bool = True) -> list[dict]:
        """Run a full market scan across all search queries.

        Returns list of deal dicts with scores and recommendations.
        """
        all_deals = []
        session = get_session()

        try:
            for query in self.searches:
                try:
                    listings = self.ebay.search_listings(query, limit=25)
                except Exception as e:
                    from src.notifications.notifier import notify_error
                    notify_error(f"eBay search: {query}", str(e))
                    continue

                for item in listings:
                    deal = self._evaluate_listing(item, session)
                    if deal:
                        all_deals.append(deal)
        finally:
            session.close()

        # Sort by score descending
        all_deals.sort(key=lambda d: d["score"], reverse=True)
        return all_deals

    def _get_fmv_waterfall(self, parsed: dict) -> tuple[dict | None, str, int]:
        """Try pricing sources in waterfall order.

        Returns (fmv_data, trend, population).
        Waterfall: SportsCardsPro -> CardLadder -> Card Hedge -> eBay active
        """
        player = parsed.get("player")
        year = parsed.get("year")
        brand = parsed.get("brand")
        set_name = parsed.get("set_name")
        grade = parsed.get("grade")
        sport = parsed.get("sport", "basketball")

        # 1. SportsCardsPro (real sold prices)
        if self._scp_client:
            try:
                scp = self._scp_client.get_fmv(
                    player=player, year=year, brand=brand,
                    set_name=set_name, grade=grade,
                )
                if scp and scp.get("fmv") and scp["fmv"] > 0:
                    vol = scp.get("sales_volume", 0)
                    confidence = min(40 + vol * 0.5, 95) if vol else 50
                    fmv_data = {
                        "fmv": scp["fmv"],
                        "confidence": confidence,
                        "source": "sportscardspro",
                        "sources_used": 1,
                    }
                    return fmv_data, "stable", 0
            except Exception:
                pass

        # 2. CardLadder (FMV + trends)
        cl_data = self.cardladder.get_fmv(
            player=player, year=year, brand=brand,
            set_name=set_name, grade=grade, sport=sport,
        )
        if cl_data:
            fmv_data = calculate_fmv(
                cardladder_fmv=cl_data.get("fmv"),
                cardladder_confidence=cl_data.get("confidence", 0),
                avg_30d=cl_data.get("avg_30d"),
                avg_90d=cl_data.get("avg_90d"),
            )
            if fmv_data["fmv"] > 0:
                return fmv_data, cl_data.get("trend", "stable"), cl_data.get("population", 0)

        # 3. Card Hedge (sold comps)
        if self._ch_client:
            try:
                ch = self._ch_client.get_fmv(
                    player=player, year=year, brand=brand,
                    set_name=set_name, grade=grade, sport=sport,
                )
                if ch and ch.get("fmv") and ch["fmv"] > 0:
                    fmv_data = calculate_fmv(
                        cardhedge_price=ch["fmv"],
                        cardhedge_num_comps=ch.get("num_comps", 0),
                    )
                    if fmv_data["fmv"] > 0:
                        return fmv_data, "stable", 0
            except Exception:
                pass

        # 4. eBay active listings (last resort)
        market = get_ebay_market_price(
            player=player, year=year, brand=brand,
            set_name=set_name, grade=grade, sport=sport,
        )
        if market:
            fmv_data = calculate_fmv(
                ebay_price=market["fmv"],
                ebay_confidence=market["confidence"],
            )
            if fmv_data["fmv"] > 0:
                return fmv_data, "stable", 0

        return None, "stable", 0

    def _evaluate_listing(self, item: dict, session) -> dict | None:
        """Evaluate a single eBay listing."""
        try:
            price = float(item.get("price", {}).get("value", 0))
            if price <= 0:
                return None

            title = item.get("title", "")
            item_id = item.get("itemId", "")

            # Parse the listing title
            parsed = parse_listing_title(title)
            player = parsed.get("player")
            if not player:
                return None

            # Get FMV via waterfall (SportsCardsPro -> CardLadder -> CardHedge -> eBay)
            fmv_data, trend, population = self._get_fmv_waterfall(parsed)

            if not fmv_data or fmv_data["fmv"] <= 0:
                return None

            # Analyze the deal
            analysis = self.analyzer.analyze(
                listing_price=price,
                estimated_fmv=fmv_data["fmv"],
                fmv_confidence=fmv_data["confidence"],
                trend=trend,
                population=population,
            )

            # Save listing to DB
            listing = Listing(
                ebay_item_id=item_id,
                title=title,
                price=price,
                seller=item.get("seller", {}).get("username"),
                listing_url=item.get("itemWebUrl"),
                player=player,
                year=parsed.get("year"),
                brand=parsed.get("brand"),
                set_name=parsed.get("set_name"),
                grade=parsed.get("grade"),
                sport=parsed.get("sport"),
                estimated_fmv=fmv_data["fmv"],
                deal_score=analysis["score"],
            )
            session.add(listing)
            session.commit()

            return {
                "listing_id": listing.id,
                "item_id": item_id,
                "title": title,
                "price": price,
                "player": player,
                "parsed": parsed,
                "fmv": fmv_data["fmv"],
                "confidence": fmv_data["confidence"],
                "trend": trend,
                "score": analysis["score"],
                "action": analysis["action"],
                "reasons": analysis["reasons"],
                "estimated_profit": analysis["estimated_profit"],
                "profit_margin": analysis["profit_margin"],
            }
        except Exception:
            return None
