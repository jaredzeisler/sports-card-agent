"""Scan target cards: base-only, ending within 12h, % below FMV."""
import httpx, base64, time, sys, re
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

# Junk listings to filter out
JUNK_KEYWORDS = [
    "mystery", "repack", "break", "pack", "box", "lot of",
    "digital", "read desc", "read description",
]

# Non-PSA grading companies to exclude
NON_PSA_GRADERS = [
    "bgs", "bgc", "cgc", "sgc", "wcg", "hga", "ags", "csg", "gma", "mga",
]


def classify(title, expected_set, player_last_name, card_num):
    """Classify a listing. Returns (label, reason) where label is BASE or a rejection reason."""
    t = f" {title.lower()} "

    # Must contain player's last name
    if player_last_name.lower() not in t:
        return f"WRONG PLAYER (no '{player_last_name}')"

    # Must contain expected set name
    if expected_set.lower() not in t:
        return "WRONG SET"

    # Check wrong-set keywords
    for ws in WRONG_SET.get(expected_set, []):
        if ws in t:
            return f"WRONG SET ({ws})"

    # Must contain the correct card number
    # Match #280, #16, etc. — strip the # for matching
    num = card_num.lstrip("#")
    # Look for #280 or # 280 patterns in title
    if not re.search(rf"#\s*{re.escape(num)}\b", t):
        return f"WRONG CARD (no {card_num})"

    # Filter junk listings
    for junk in JUNK_KEYWORDS:
        if junk in t:
            return f"JUNK ({junk})"

    # Filter non-PSA graders
    for grader in NON_PSA_GRADERS:
        if f" {grader} " in t or f" {grader}/" in t:
            return f"WRONG GRADER ({grader})"

    # Check for parallels/variations
    found = [v.strip() for v in VARIATIONS if v in t]
    if found:
        return f"PARALLEL ({', '.join(found)})"

    return "BASE"


def parse_end_time(iso_str):
    if not iso_str:
        return None
    iso_str = iso_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_str)
    except ValueError:
        return None


def hours_left(end_dt):
    if not end_dt:
        return 999
    now = datetime.now(timezone.utc)
    delta = end_dt - now
    return delta.total_seconds() / 3600


def pct_below_fmv(current_price, fmv):
    """% below FMV. Positive = below FMV, negative = above FMV."""
    if not fmv or fmv == 0:
        return 0
    return ((fmv - current_price) / fmv) * 100


TARGETS = [
    ("PSA 10 Luka Doncic Prizm rookie #280", "Prizm", "Luka Doncic", "Doncic", 10, "#280"),
    ("PSA 10 Jayson Tatum Prizm rookie #16", "Prizm", "Jayson Tatum", "Tatum", 10, "#16"),
    ("PSA 10 Anthony Edwards Prizm rookie #258", "Prizm", "Anthony Edwards", "Edwards", 10, "#258"),
    ("PSA 10 Victor Wembanyama Prizm rookie #136", "Prizm", "Victor Wembanyama", "Wembanyama", 10, "#136"),
    ("PSA 10 Ja Morant Prizm rookie #249", "Prizm", "Ja Morant", "Morant", 10, "#249"),
    ("PSA 9 LeBron James Topps Chrome rookie #111", "Chrome", "LeBron James", "LeBron", 9, "#111"),
]

now = datetime.now(timezone.utc)
cutoff = now + timedelta(hours=MAX_HOURS)
print(f"Current time (UTC): {now.strftime('%Y-%m-%d %H:%M')}")
print(f"Auction cutoff:     {cutoff.strftime('%Y-%m-%d %H:%M')} ({MAX_HOURS}h window)")

all_below_fmv = []  # collect listings below FMV across all targets

for query, expected_set, player, last_name, grade, card_num in TARGETS:
    print(f"\n{'='*95}")
    print(f"TARGET: {player} — {expected_set} {card_num} PSA {grade}")
    print(f"{'='*95}")

    # FMV
    fmv = None
    try:
        set_q = "Topps Chrome" if expected_set == "Chrome" else expected_set
        fmv_data = scp.get_fmv(player=player, set_name=set_q, grade=grade)
        if fmv_data:
            fmv = fmv_data["fmv"]
            print(f"  FMV: ${fmv:,.2f}  (vol: {fmv_data.get('sales_volume', 0)})")
        else:
            print(f"  FMV: Unknown")
    except Exception as e:
        print(f"  FMV Error: {e}")
    time.sleep(1.1)

    # --- AUCTIONS ending within 12h ---
    print(f"\n  AUCTIONS (ending within {MAX_HOURS}h):")
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
        filtered = {"later": 0}
        for a in auctions:
            title = a.get("title", "")
            label = classify(title, expected_set, last_name, card_num)
            if label != "BASE":
                filtered[label] = filtered.get(label, 0) + 1
                continue

            end_dt = parse_end_time(a.get("itemEndDate"))
            h_left = hours_left(end_dt)

            if h_left > MAX_HOURS:
                filtered["later"] += 1
                continue

            bp = a.get("currentBidPrice") or a.get("price", {})
            price = float(bp.get("value", 0))
            bids = a.get("bidCount", 0)
            end_str = end_dt.strftime("%m/%d %H:%M") if end_dt else "?"

            pct = pct_below_fmv(price, fmv) if fmv else 0
            base_soon.append((price, bids, h_left, end_str, title, pct))

        if base_soon:
            base_soon.sort(key=lambda x: x[0])
            for p, b, h, e, t, pct in base_soon:
                print(f"    ${p:>8.2f}  bids={b:<3} ends={e} ({h:.1f}h)  {pct:+.0f}% vs FMV")
                print(f"      {t[:75]}")
                all_below_fmv.append((player, "AUCTION", p, fmv, pct, h, b, e, t))
        else:
            print(f"    None")

        # Show filter summary
        filter_parts = []
        for reason, count in sorted(filtered.items()):
            if count > 0:
                filter_parts.append(f"{count} {reason}")
        if filter_parts:
            print(f"    [filtered: {', '.join(filter_parts)}]")

    except Exception as e:
        print(f"    Error: {e}")

    # --- BIN ---
    print(f"\n  BUY IT NOW:")
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
            label = classify(title, expected_set, last_name, card_num)
            if label != "BASE":
                continue
            price = float(b.get("price", {}).get("value", 0))
            base_bins.append((price, title))

        if base_bins:
            base_bins.sort(key=lambda x: x[0])
            for p, t in base_bins[:5]:
                pct = pct_below_fmv(p, fmv) if fmv else 0
                print(f"    ${p:>8.2f}  {pct:+.0f}% vs FMV")
                print(f"      {t[:75]}")
                all_below_fmv.append((player, "BIN", p, fmv, pct, 0, 0, "now", t))
        else:
            print(f"    None matching {card_num}")

    except Exception as e:
        print(f"    Error: {e}")

# --- SUMMARY ---
print(f"\n{'='*95}")
print(f"SUMMARY — All matched listings vs FMV")
print(f"{'='*95}")
if all_below_fmv:
    all_below_fmv.sort(key=lambda x: -x[4])  # highest % below FMV first
    for player, typ, price, fmv_val, pct, h, bids, end, title in all_below_fmv:
        fmv_str = f"FMV ${fmv_val:,.0f}" if fmv_val else "FMV ?"
        if typ == "AUCTION":
            print(f"  {pct:+.0f}%  ${price:>8.2f} ({fmv_str})  {player}  AUCTION  bids={bids} ends={end} ({h:.1f}h)")
        else:
            print(f"  {pct:+.0f}%  ${price:>8.2f} ({fmv_str})  {player}  BIN")
        print(f"         {title[:70]}")
else:
    print("  No matched listings found")

print(f"\n{'='*95}")
print("DONE")
