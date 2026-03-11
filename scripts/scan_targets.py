"""Scan all target cards, classify base vs parallel, show FMV + live auctions + BIN."""
import httpx, base64, time, sys
from config.settings import get_settings
from src.api.sportscardspro import SportsCardsProClient

s = get_settings()
scp = SportsCardsProClient(s)

# Get eBay token
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


TARGETS = [
    ("PSA 10 Luka Doncic Prizm rookie", "Prizm", "Luka Doncic", 10, "#280"),
    ("PSA 10 Jayson Tatum Prizm rookie", "Prizm", "Jayson Tatum", 10, "#16"),
    ("PSA 10 Anthony Edwards Prizm rookie", "Prizm", "Anthony Edwards", 10, "#258"),
    ("PSA 10 Victor Wembanyama Prizm rookie", "Prizm", "Victor Wembanyama", 10, "#136"),
    ("PSA 10 Ja Morant Prizm rookie", "Prizm", "Ja Morant", 10, "#249"),
    ("PSA 9 LeBron James Topps Chrome rookie", "Chrome", "LeBron James", 9, "#111"),
]

for query, expected_set, player, grade, card_num in TARGETS:
    print(f"\n{'='*95}")
    print(f"TARGET: {query} {card_num}")
    print(f"{'='*95}")

    # FMV
    try:
        set_q = "Topps Chrome" if expected_set == "Chrome" else expected_set
        fmv_data = scp.get_fmv(player=player, set_name=set_q, grade=grade)
        if fmv_data:
            print(f"  BASE FMV: ${fmv_data['fmv']:,.2f}  (product: {fmv_data.get('product_name','')}, vol: {fmv_data.get('sales_volume',0)})")
        else:
            print(f"  BASE FMV: Unknown")
    except Exception as e:
        print(f"  FMV Error: {e}")
    time.sleep(1.1)

    # Auctions
    print(f"\n  AUCTIONS:")
    try:
        r = httpx.get(
            f"{s.ebay_base_url}/buy/browse/v1/item_summary/search",
            headers=hdrs,
            params={"q": query, "limit": 25, "filter": "buyingOptions:{AUCTION}"},
            timeout=30,
        )
        r.raise_for_status()
        auctions = r.json().get("itemSummaries", [])
        base_a = []
        other_a = []
        for a in auctions:
            bp = a.get("currentBidPrice") or a.get("price", {})
            price = float(bp.get("value", 0))
            bids = a.get("bidCount", 0)
            end = (a.get("itemEndDate") or "?")[:19].replace("T", " ")
            title = a.get("title", "")
            label = classify(title, expected_set)
            row = (price, bids, end, title, label)
            if label == "BASE":
                base_a.append(row)
            else:
                other_a.append(row)

        if base_a:
            print(f"    BASE CARD auctions ({len(base_a)}):")
            for p, b, e, t, l in base_a:
                print(f"      ${p:>8.2f}  bids={b:<3} ends={e}  {t[:65]}")
        else:
            print(f"    BASE CARD auctions: NONE")

        if other_a:
            print(f"    Parallels/Other ({len(other_a)}):")
            for p, b, e, t, l in other_a:
                print(f"      ${p:>8.2f}  bids={b:<3} ends={e}  [{l}]")
                print(f"        {t[:75]}")
    except Exception as e:
        print(f"    Error: {e}")

    # BIN
    print(f"\n  BUY IT NOW:")
    try:
        r2 = httpx.get(
            f"{s.ebay_base_url}/buy/browse/v1/item_summary/search",
            headers=hdrs,
            params={"q": query, "limit": 25, "filter": "buyingOptions:{FIXED_PRICE}"},
            timeout=30,
        )
        r2.raise_for_status()
        bins = r2.json().get("itemSummaries", [])
        base_b = []
        other_b = []
        for b in bins:
            price = float(b.get("price", {}).get("value", 0))
            title = b.get("title", "")
            label = classify(title, expected_set)
            if label == "BASE":
                base_b.append((price, title, label))
            else:
                other_b.append((price, title, label))

        if base_b:
            base_b.sort(key=lambda x: x[0])
            print(f"    BASE CARD BIN ({len(base_b)}):")
            for p, t, l in base_b[:5]:
                print(f"      ${p:>8.2f}  {t[:70]}")
        else:
            print(f"    BASE CARD BIN: NONE")

        if other_b:
            other_b.sort(key=lambda x: x[0])
            print(f"    Parallels/Other BIN ({len(other_b)}):")
            for p, t, l in other_b[:3]:
                print(f"      ${p:>8.2f}  [{l}]")
                print(f"        {t[:75]}")
    except Exception as e:
        print(f"    Error: {e}")

print(f"\n{'='*95}")
print("DONE")
