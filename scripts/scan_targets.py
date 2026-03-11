"""Scan target cards: base-only, ending within 12h, with deal scoring vs FMV."""
import httpx, base64, time, sys
from datetime import datetime, timezone, timedelta
from config.settings import get_settings
from src.api.sportscardspro import SportsCardsProClient

s = get_settings()
scp = SportsCardsProClient(s)

# eBay auth
creds = base64.b64encode(f"{s.ebay_app_id}:{s.ebay_cert_id}".encode()).decode()
resp = httpx.post(
    s.ebay_auth_url,
    headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {creds}"},
    data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
    timeout=30,
)
if resp.status_code != 200:
    print(f"Auth failed: {resp.status_code} {resp.text[:200]}")
    sys.exit(1)
token = resp.json()["access_token"]
hdrs = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
}

MAX_HOURS = 12  # only show auctions ending within this window

VARIATIONS = [
    "silver", "gold", " red ", "blue", "green", "orange", "purple", "pink",
    "black", "refractor", "wave", "shimmer", "mojo",
    "ice", "camo", "tie-dye", "snakeskin", "tiger", "zebra", "ruby",
    "fast break", "disco", "choice", "hyper", "pulsar", "neon",
    "scope", "lazer", "color blast", "downtown", "kaboom",
    "auto ", "autograph", "signature", "signed", "patch", " rpa",
    "variation", " sp ", " ssp", "image variation",
    "purple wave", "ruby wave", "red wave", "green wave", "blue wave",
    "red white blue", "rwb", "cracked ice", "color match",
]

WRONG_SET = {
    "Prizm": ["select", "mosaic", "optic", "hoops", "contenders", "revolution",
              "court kings", "origins", "national treasures", "immaculate", "spectra"],
    "Chrome": ["bowman", "stadium club", "heritage"],
}


def classify(title, expected_set):
    t = f" {title.lower()} "
    if expected_set.lower() not in t:
        return "WRONG SET"
    for ws in WRONG_SET.get(expected_set, []):
        if ws in t:
            return f"WRONG SET ({ws})"
    found = [v.strip() for v in VARIATIONS if v in t]
    if found:
        return f"PARALLEL ({', '.join(found)})"
    return "BASE"


def parse_end_time(iso_str):
    """Parse eBay ISO timestamp to UTC datetime."""
    if not iso_str:
        return None
    # Handle both Z and +00:00 formats
    iso_str = iso_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_str)
    except ValueError:
        return None


def hours_left(end_dt):
    """Hours remaining until auction ends."""
    if not end_dt:
        return 999
    now = datetime.now(timezone.utc)
    delta = end_dt - now
    return delta.total_seconds() / 3600


def discount_pct(current_price, fmv):
    """% below FMV. Positive = deal, negative = overpriced."""
    if not fmv or fmv == 0:
        return 0
    return ((fmv - current_price) / fmv) * 100


TARGETS = [
    ("PSA 10 Luka Doncic Prizm rookie", "Prizm", "Luka Doncic", 10, "#280"),
    ("PSA 10 Jayson Tatum Prizm rookie", "Prizm", "Jayson Tatum", 10, "#16"),
    ("PSA 10 Anthony Edwards Prizm rookie", "Prizm", "Anthony Edwards", 10, "#258"),
    ("PSA 10 Victor Wembanyama Prizm rookie", "Prizm", "Victor Wembanyama", 10, "#136"),
    ("PSA 10 Ja Morant Prizm rookie", "Prizm", "Ja Morant", 10, "#249"),
    ("PSA 9 LeBron James Topps Chrome rookie", "Chrome", "LeBron James", 9, "#111"),
]

now = datetime.now(timezone.utc)
cutoff = now + timedelta(hours=MAX_HOURS)
print(f"Current time (UTC): {now.strftime('%Y-%m-%d %H:%M')}")
print(f"Auction cutoff:     {cutoff.strftime('%Y-%m-%d %H:%M')} ({MAX_HOURS}h window)")

all_deals = []  # collect best deals across all targets

for query, expected_set, player, grade, card_num in TARGETS:
    print(f"\n{'='*95}")
    print(f"TARGET: {query} {card_num}")
    print(f"{'='*95}")

    # FMV
    fmv = None
    try:
        set_q = "Topps Chrome" if expected_set == "Chrome" else expected_set
        fmv_data = scp.get_fmv(player=player, set_name=set_q, grade=grade)
        if fmv_data:
            fmv = fmv_data["fmv"]
            print(f"  BASE FMV: ${fmv:,.2f}  (vol: {fmv_data.get('sales_volume', 0)})")
        else:
            print(f"  BASE FMV: Unknown")
    except Exception as e:
        print(f"  FMV Error: {e}")
    time.sleep(1.1)

    # --- AUCTIONS ending within 12h ---
    print(f"\n  AUCTIONS (ending within {MAX_HOURS}h, base cards only):")
    try:
        r = httpx.get(
            f"{s.ebay_base_url}/buy/browse/v1/item_summary/search",
            headers=hdrs,
            params={
                "q": query,
                "limit": 50,
                "filter": "buyingOptions:{AUCTION}",
                "sort": "endingSoonest",
            },
            timeout=30,
        )
        r.raise_for_status()
        auctions = r.json().get("itemSummaries", [])

        base_soon = []
        base_later = 0
        non_base = 0
        for a in auctions:
            title = a.get("title", "")
            label = classify(title, expected_set)
            if label != "BASE":
                non_base += 1
                continue

            end_dt = parse_end_time(a.get("itemEndDate"))
            h_left = hours_left(end_dt)

            if h_left > MAX_HOURS:
                base_later += 1
                continue

            bp = a.get("currentBidPrice") or a.get("price", {})
            price = float(bp.get("value", 0))
            bids = a.get("bidCount", 0)
            end_str = end_dt.strftime("%m/%d %H:%M") if end_dt else "?"

            disc = discount_pct(price, fmv) if fmv else 0
            base_soon.append((price, bids, h_left, end_str, title, disc))

        if base_soon:
            base_soon.sort(key=lambda x: x[0])  # cheapest first
            for p, b, h, e, t, d in base_soon:
                flag = ""
                if d >= 50:
                    flag = " *** SNIPE CANDIDATE"
                elif d >= 25:
                    flag = " ** POTENTIAL DEAL"
                elif d >= 10:
                    flag = " * WATCH"
                print(f"    ${p:>8.2f}  bids={b:<3} ends={e} ({h:.1f}h)  {d:+.0f}% vs FMV{flag}")
                print(f"      {t[:75]}")
                if fmv and d >= 10:
                    all_deals.append((player, "AUCTION", p, fmv, d, h, b, e, t))
        else:
            print(f"    No base auctions ending within {MAX_HOURS}h")

        print(f"    [{non_base} parallels/wrong-set filtered, {base_later} base ending later]")

    except Exception as e:
        print(f"    Error: {e}")

    # --- BIN below FMV ---
    print(f"\n  BUY IT NOW (base cards, sorted by price):")
    try:
        r2 = httpx.get(
            f"{s.ebay_base_url}/buy/browse/v1/item_summary/search",
            headers=hdrs,
            params={
                "q": query,
                "limit": 25,
                "filter": "buyingOptions:{FIXED_PRICE}",
                "sort": "price",
            },
            timeout=30,
        )
        r2.raise_for_status()
        bins = r2.json().get("itemSummaries", [])
        base_bins = []
        for b in bins:
            title = b.get("title", "")
            label = classify(title, expected_set)
            if label != "BASE":
                continue
            price = float(b.get("price", {}).get("value", 0))
            base_bins.append((price, title))

        if base_bins:
            base_bins.sort(key=lambda x: x[0])
            for p, t in base_bins[:5]:
                disc = discount_pct(p, fmv) if fmv else 0
                flag = ""
                if disc >= 20:
                    flag = " ** BIN DEAL"
                elif disc >= 10:
                    flag = " * BELOW FMV"
                print(f"    ${p:>8.2f}  {disc:+.0f}% vs FMV{flag}")
                print(f"      {t[:75]}")
                if fmv and disc >= 10:
                    all_deals.append((player, "BIN", p, fmv, disc, 0, 0, "now", t))
        else:
            print(f"    No base card BINs found")

    except Exception as e:
        print(f"    Error: {e}")

# --- DEAL SUMMARY ---
print(f"\n{'='*95}")
print(f"DEAL SUMMARY (all cards >10% below FMV)")
print(f"{'='*95}")
if all_deals:
    all_deals.sort(key=lambda x: -x[4])  # best discount first
    for player, typ, price, fmv_val, disc, h, bids, end, title in all_deals:
        if typ == "AUCTION":
            print(f"  {disc:+.0f}%  ${price:>8.2f} (FMV ${fmv_val:,.0f})  {player}  AUCTION  bids={bids} ends={end} ({h:.1f}h)")
        else:
            print(f"  {disc:+.0f}%  ${price:>8.2f} (FMV ${fmv_val:,.0f})  {player}  BIN NOW")
        print(f"         {title[:70]}")
else:
    print("  No deals found >10% below FMV")

print(f"\n{'='*95}")
print("DONE")
