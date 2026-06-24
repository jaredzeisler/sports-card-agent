"""Match eBay purchase history to PSA Vault items to fill in missing cost basis."""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime

from bs4 import BeautifulSoup


def parse_float(s):
    try:
        return float(s.replace(",", "")) if s else 0
    except ValueError:
        return 0


def parse_date(s):
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y %I:%M%p", "%b %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_purchases(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    all_cells = soup.find_all("td", class_=re.compile(r"bottomBorder"))
    texts = [c.get_text(strip=True) for c in all_cells]
    purchases = []
    for i in range(0, len(texts), 9):
        chunk = texts[i:i + 9]
        if len(chunk) == 9:
            date_str, item_id, title, price_str, qty_str, shipping_str, total_str, currency, seller = chunk
            price = parse_float(price_str)
            total = parse_float(total_str)
            if title and (price > 0 or total > 0):
                purchases.append({
                    "date": parse_date(date_str),
                    "item_id": item_id,
                    "title": title,
                    "price": price,
                    "shipping": parse_float(shipping_str),
                    "total": total if total > 0 else price + parse_float(shipping_str),
                    "seller": seller,
                    "title_normalized": normalize(title),
                })
    return purchases


def parse_vault(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header_skipped = False
        for row in reader:
            if not header_skipped:
                if row and row[0].strip() == "Item Status":
                    header_skipped = True
                    continue
                header_skipped = True
            if len(row) < 20:
                continue

            def val(idx):
                return row[idx].strip() if idx < len(row) and row[idx].strip() not in ("-", "", "########") else ""

            cert = val(2)
            grader = ""
            if cert.startswith("VIH"):
                grader = "VIH"
            elif cert.startswith("00"):
                grader = "BGS"
            else:
                try:
                    float(cert.replace("E+", "e+"))
                    grader = "PSA"
                except ValueError:
                    grader = "SGC" if cert else "Unknown"

            item = {
                "status": val(0),
                "item": val(1),
                "cert": cert,
                "grader": grader,
                "grade": val(3),
                "year": val(6),
                "set": val(7),
                "card_number": val(8),
                "subject": val(9),
                "variety": val(10),
                "serial": val(11),
                "my_cost": parse_float(val(12)),
                "psa_estimate": parse_float(val(13)),
                "vault_status": val(19),
                "listing_status": val(22),
                "listing_price": parse_float(val(24)),
                "sold_price": parse_float(val(28)),
                "sold_fees": parse_float(val(29)),
                "sold_proceeds": parse_float(val(30)),
                "item_normalized": normalize(val(1)),
            }
            if item["item"]:
                items.append(item)
    return items


def normalize(s):
    """Normalize a string for fuzzy matching."""
    s = s.upper()
    s = re.sub(r'[^A-Z0-9/ ]', ' ', s)
    s = re.sub(r'\b(PSA|BGS|SGC|GMA|CSG|ISA|HGA)\b', '', s)
    s = re.sub(r'\b(RC|ROOKIE)\b', 'RC', s)
    s = re.sub(r'\b(AUTO|AUTOGRAPH|AUTOGRAPHS|AUTOGRAPHED|SIGNATURE|SIGNATURES|SIGNED)\b', 'AUTO', s)
    s = re.sub(r'\b(REFRACTOR|REFRACTORS)\b', 'REFRACTOR', s)
    s = re.sub(r'\b(PRIZM|PRISM)\b', 'PRIZM', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def extract_cert_numbers(title):
    """Try to extract grading cert numbers from eBay title."""
    certs = set()
    for m in re.finditer(r'#?(\d{7,10})', title):
        num = m.group(1)
        if not num.startswith("20") or len(num) > 6:
            certs.add(num)
    return certs


def extract_year(s):
    m = re.search(r'((?:19|20)\d{2})(?:-\d{2,4})?', s)
    return m.group(0) if m else ""


def extract_player_names(s):
    """Extract likely player names from a card description."""
    known_players = [
        "LEBRON", "JAMES", "CURRY", "STEPH", "STEPHEN", "LUKA", "DONCIC",
        "GIANNIS", "ANTETOKOUNMPO", "KOBE", "BRYANT", "JORDAN", "MICHAEL",
        "WEMBY", "WEMBANYAMA", "VICTOR", "EDWARDS", "ANTHONY", "ANT",
        "TATUM", "JAYSON", "JOKIC", "NIKOLA", "ZION", "WILLIAMSON",
        "MORANT", "JA", "DURANT", "KEVIN", "KD", "HARDEN",
        "BOOKER", "DEVIN", "EMBIID", "JOEL", "DAVIS", "BANCHERO", "PAOLO",
        "MAXEY", "TYRESE", "SGA", "SHAI", "GILGEOUS", "CHET", "HOLMGREN",
        "SHAQ", "SHAQUILLE", "IVERSON", "ALLEN", "YAO", "MING",
        "BIRD", "LARRY", "MAGIC", "JOHNSON", "KAREEM", "ABDUL",
        "MANTLE", "RUTH", "GEHRIG", "OHTANI", "SHOHEI", "TROUT", "MIKE",
        "SASAKI", "ROKI", "YAMAMOTO", "YOSHINOBU",
        "FLAGG", "COOPER", "EDGECOMBE", "VJ",
        "CLARK", "CAITLIN", "REESE", "ANGEL", "HIDALGO", "HANNAH",
        "CARTER", "VINCE", "DR J", "ERVING", "JULIUS",
        "KAT", "TOWNS", "RAY", "PIPPEN", "SCOTTIE",
        "LIN", "JEREMY", "WOOD",
        "BUZELIS", "MATAS", "BRONNY",
    ]
    s_upper = s.upper()
    found = []
    for p in known_players:
        if p in s_upper:
            found.append(p)
    return set(found)


def extract_card_number(s):
    m = re.search(r'#(\w+[-/]?\w*)', s)
    return m.group(1).upper() if m else ""


def extract_serial(s):
    m = re.search(r'/(\d+)', s)
    return m.group(1) if m else ""


def token_overlap_score(s1, s2):
    """Compute Jaccard-like token overlap between two normalized strings."""
    t1 = set(s1.split())
    t2 = set(s2.split())
    if not t1 or not t2:
        return 0
    intersection = t1 & t2
    union = t1 | t2
    return len(intersection) / len(union)


def match_purchases_to_vault(purchases, vault_items):
    """Match each vault item to the best eBay purchase."""
    # Build cert lookup from vault
    vault_by_cert = {}
    for v in vault_items:
        if v["cert"] and not v["cert"].startswith("VIH"):
            clean_cert = v["cert"].lstrip("0")
            vault_by_cert[clean_cert] = v
            vault_by_cert[v["cert"]] = v

    matches = []
    used_purchases = set()
    unmatched_vault = []

    # Pass 1: Exact cert number match
    for vi, v in enumerate(vault_items):
        if v["my_cost"] > 0:
            continue
        if v["cert"].startswith("VIH"):
            continue

        clean_cert = v["cert"].lstrip("0")
        best_match = None
        best_idx = None

        for pi, p in enumerate(purchases):
            if pi in used_purchases:
                continue
            certs_in_title = extract_cert_numbers(p["title"])
            if clean_cert in certs_in_title or v["cert"] in certs_in_title:
                if best_match is None or p["total"] > best_match["total"]:
                    best_match = p
                    best_idx = pi

        if best_match:
            matches.append({
                "vault_item": v["item"],
                "vault_cert": v["cert"],
                "ebay_title": best_match["title"],
                "ebay_item_id": best_match["item_id"],
                "price": best_match["price"],
                "total": best_match["total"],
                "date": best_match["date"],
                "method": "cert_exact",
                "confidence": 0.99,
            })
            v["matched_cost"] = best_match["total"]
            used_purchases.add(best_idx)

    # Pass 2: Fuzzy title matching for remaining items
    unmatched = [v for v in vault_items if v["my_cost"] == 0 and "matched_cost" not in v and not v["cert"].startswith("VIH")]

    for v in unmatched:
        v_year = extract_year(v["item"])
        v_players = extract_player_names(v["item"])
        v_card_num = extract_card_number(v["item"])
        v_serial = extract_serial(v["item"])
        v_norm = v["item_normalized"]

        best_score = 0
        best_match = None
        best_idx = None

        for pi, p in enumerate(purchases):
            if pi in used_purchases:
                continue

            p_year = extract_year(p["title"])
            p_players = extract_player_names(p["title"])

            # Must share at least one player name
            if not (v_players & p_players):
                continue

            # Year must match if both have years
            if v_year and p_year and v_year[:4] != p_year[:4]:
                continue

            score = 0

            # Token overlap
            overlap = token_overlap_score(v_norm, p["title_normalized"])
            score += overlap * 50

            # Player match bonus
            player_overlap = len(v_players & p_players) / max(len(v_players | p_players), 1)
            score += player_overlap * 20

            # Year match bonus
            if v_year and p_year and v_year == p_year:
                score += 10
            elif v_year and p_year and v_year[:4] == p_year[:4]:
                score += 5

            # Card number match
            p_card_num = extract_card_number(p["title"])
            if v_card_num and p_card_num and v_card_num == p_card_num:
                score += 15

            # Serial match
            p_serial = extract_serial(p["title"])
            if v_serial and p_serial and v_serial == p_serial:
                score += 10

            # Grade in title bonus
            if v["grade"] and v["grade"] in p["title"]:
                score += 5

            if score > best_score:
                best_score = score
                best_match = p
                best_idx = pi

        if best_match and best_score >= 35:
            confidence = min(best_score / 100, 0.95)
            matches.append({
                "vault_item": v["item"],
                "vault_cert": v["cert"],
                "ebay_title": best_match["title"],
                "ebay_item_id": best_match["item_id"],
                "price": best_match["price"],
                "total": best_match["total"],
                "date": best_match["date"],
                "method": "fuzzy",
                "confidence": round(confidence, 2),
                "score": round(best_score, 1),
            })
            v["matched_cost"] = best_match["total"]
            used_purchases.add(best_idx)

    return matches


def update_excel_with_costs(matches, vault_items):
    """Create updated P&L Excel with matched costs filled in."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    OUT = "/home/user/sports-card-agent/Inventory/eBay_PnL.xlsx"
    money_fmt = '#,##0.00'
    pct_fmt = '0.0%'
    thin_border = Border(bottom=Side(style="thin", color="CCCCCC"))
    green_font = Font(color="006100")
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_font = Font(color="9C0006")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

    def make_header(ws, headers, fill_color="1F4E79"):
        header_font = Font(bold=True, color="FFFFFF", size=11)
        fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.font = header_font
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center")

    # Apply matched costs to vault items
    match_by_cert = {m["vault_cert"]: m for m in matches}
    for v in vault_items:
        if v["my_cost"] == 0 and v["cert"] in match_by_cert:
            v["my_cost"] = match_by_cert[v["cert"]]["total"]
            v["cost_source"] = "matched"
        elif v["my_cost"] > 0:
            v["cost_source"] = "vault"
        else:
            v["cost_source"] = "unknown"

    wb = Workbook()

    # ── Summary Sheet ──
    ws = wb.active
    ws.title = "P&L Summary"
    ws.sheet_properties.tabColor = "1F4E79"

    vault_sold = [v for v in vault_items if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    vault_with_cost = [v for v in vault_items if v["my_cost"] > 0]
    vault_held = [v for v in vault_items if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    vault_listed = [v for v in vault_items if v["listing_status"] == "Fixed Price" and v["sold_price"] == 0]

    total_vault_cost = sum(v["my_cost"] for v in vault_with_cost)
    total_vault_sold_price = sum(v["sold_price"] for v in vault_sold)
    total_vault_sold_proceeds = sum(v["sold_proceeds"] for v in vault_sold)
    total_vault_fees = sum(v["sold_fees"] for v in vault_sold)
    sold_cost_basis = sum(v["my_cost"] for v in vault_sold if v["my_cost"] > 0)
    sold_with_cost = [v for v in vault_sold if v["my_cost"] > 0]
    sold_without_cost = [v for v in vault_sold if v["my_cost"] == 0]

    held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    held_est = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)
    held_with_cost = len([v for v in vault_held if v["my_cost"] > 0])
    total_listed_price = sum(v["listing_price"] for v in vault_listed)

    gross_pnl = total_vault_sold_proceeds - sold_cost_basis
    items_matched = len(matches)
    items_from_vault = len([v for v in vault_items if v.get("cost_source") == "vault"])
    items_no_cost = len([v for v in vault_items if v["my_cost"] == 0 and not v["cert"].startswith("VIH")])

    summary = [
        ("COMPLETE P&L SUMMARY", "", True),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M"), False),
        ("", "", False),
        ("COST BASIS MATCHING", "", True),
        ("Vault items with original cost", items_from_vault, False),
        ("Items matched from eBay purchases", items_matched, False),
        ("Total items with cost data", len(vault_with_cost), False),
        ("Items still missing cost", items_no_cost, False),
        ("", "", False),
        ("TOTAL INVESTMENT", "", True),
        ("Total Cost Basis (all items)", total_vault_cost, False),
        ("", "", False),
        ("REALIZED P&L (SOLD ITEMS)", "", True),
        ("Items Sold", len(vault_sold), False),
        ("Sold Items with Cost Data", len(sold_with_cost), False),
        ("Sold Items Missing Cost", len(sold_without_cost), False),
        ("Total Sold Price", total_vault_sold_price, False),
        ("Total Fees", total_vault_fees, False),
        ("Total Net Proceeds", total_vault_sold_proceeds, False),
        ("Cost Basis (sold items)", sold_cost_basis, False),
        ("Realized Gross P&L", gross_pnl, False),
        ("", "", False),
        ("UNREALIZED P&L (HELD ITEMS)", "", True),
        ("Cards in Vault (unsold)", len(vault_held), False),
        ("Cards with Cost Data", held_with_cost, False),
        ("Cost Basis (held)", held_cost, False),
        ("PSA Estimate (held)", held_est, False),
        ("Unrealized G/L (Est - Cost)", held_est - held_cost, False),
        ("", "", False),
        ("ACTIVE LISTINGS", "", True),
        ("Cards Currently Listed", len(vault_listed), False),
        ("Total Listing Price", total_listed_price, False),
    ]

    for i, (label, value, is_header) in enumerate(summary, 1):
        ws.cell(row=i, column=1, value=label)
        cell = ws.cell(row=i, column=2, value=value)
        if isinstance(value, float) and value != 0:
            cell.number_format = money_fmt
        if is_header:
            ws.cell(row=i, column=1).font = Font(bold=True, size=13, color="1F4E79")
        if "P&L" in label and isinstance(value, (int, float)) and value != 0 and "CALCULATION" not in label and "REALIZED" not in label:
            ws.cell(row=i, column=1).font = Font(bold=True, size=12)
            cell.font = Font(bold=True, size=12, color="006100" if value >= 0 else "9C0006")
            cell.fill = green_fill if value >= 0 else red_fill
            cell.number_format = money_fmt
        if "Unrealized" in label and isinstance(value, (int, float)):
            cell.font = Font(color="006100" if value >= 0 else "9C0006")
            cell.number_format = money_fmt

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 20

    # ── Vault Sales with P&L ──
    ws_sold = wb.create_sheet("Sales P&L")
    ws_sold.sheet_properties.tabColor = "70AD47"
    make_header(ws_sold, [
        "Item", "Cert", "Grader", "Grade", "My Cost", "Cost Source",
        "Sold Price", "Fees", "Net Proceeds", "P&L ($)", "P&L (%)", "Sold On"
    ], "375623")

    vault_sold_sorted = sorted(vault_sold, key=lambda x: x["sold_proceeds"], reverse=True)
    for r, v in enumerate(vault_sold_sorted, 2):
        pnl = v["sold_proceeds"] - v["my_cost"] if v["my_cost"] > 0 else 0
        pnl_pct = pnl / v["my_cost"] if v["my_cost"] > 0 else 0

        ws_sold.cell(row=r, column=1, value=v["item"])
        ws_sold.cell(row=r, column=2, value=v["cert"])
        ws_sold.cell(row=r, column=3, value=v["grader"])
        ws_sold.cell(row=r, column=4, value=v["grade"])
        cost_cell = ws_sold.cell(row=r, column=5, value=v["my_cost"])
        cost_cell.number_format = money_fmt
        src = v.get("cost_source", "unknown")
        src_cell = ws_sold.cell(row=r, column=6, value=src)
        if src == "matched":
            src_cell.fill = yellow_fill
        elif src == "vault":
            src_cell.fill = green_fill

        ws_sold.cell(row=r, column=7, value=v["sold_price"]).number_format = money_fmt
        ws_sold.cell(row=r, column=8, value=v["sold_fees"]).number_format = money_fmt
        ws_sold.cell(row=r, column=9, value=v["sold_proceeds"]).number_format = money_fmt

        pnl_cell = ws_sold.cell(row=r, column=10, value=pnl)
        pnl_cell.number_format = money_fmt
        if v["my_cost"] > 0:
            pnl_cell.font = green_font if pnl >= 0 else red_font
            pnl_cell.fill = green_fill if pnl >= 0 else red_fill

        pct_cell = ws_sold.cell(row=r, column=11, value=pnl_pct)
        pct_cell.number_format = pct_fmt
        if v["my_cost"] > 0:
            pct_cell.font = green_font if pnl_pct >= 0 else red_font

        ws_sold.cell(row=r, column=12, value=v.get("sold_on", ""))

        for c in range(1, 13):
            ws_sold.cell(row=r, column=c).border = thin_border

    for col, w in zip("ABCDEFGHIJKL", [60, 14, 8, 8, 12, 10, 12, 10, 12, 12, 10, 14]):
        ws_sold.column_dimensions[col].width = w
    ws_sold.freeze_panes = "A2"
    ws_sold.auto_filter.ref = f"A1:L{len(vault_sold_sorted)+1}"

    # ── Current Inventory ──
    ws_inv = wb.create_sheet("Current Inventory")
    ws_inv.sheet_properties.tabColor = "FFC000"
    make_header(ws_inv, [
        "Item", "Cert", "Grader", "Grade", "My Cost", "Cost Source",
        "PSA Estimate", "Unrealized G/L", "Listing Status", "Listing Price", "Days Vaulted"
    ], "BF8F00")

    vault_held_sorted = sorted(vault_held, key=lambda x: x["my_cost"], reverse=True)
    for r, v in enumerate(vault_held_sorted, 2):
        unreal = v["psa_estimate"] - v["my_cost"] if v["my_cost"] > 0 and v["psa_estimate"] > 0 else 0

        ws_inv.cell(row=r, column=1, value=v["item"])
        ws_inv.cell(row=r, column=2, value=v["cert"])
        ws_inv.cell(row=r, column=3, value=v["grader"])
        ws_inv.cell(row=r, column=4, value=v["grade"])
        ws_inv.cell(row=r, column=5, value=v["my_cost"]).number_format = money_fmt
        src = v.get("cost_source", "unknown")
        src_cell = ws_inv.cell(row=r, column=6, value=src)
        if src == "matched":
            src_cell.fill = yellow_fill
        elif src == "vault":
            src_cell.fill = green_fill
        ws_inv.cell(row=r, column=7, value=v["psa_estimate"]).number_format = money_fmt

        gl_cell = ws_inv.cell(row=r, column=8, value=unreal)
        gl_cell.number_format = money_fmt
        if v["my_cost"] > 0 and v["psa_estimate"] > 0:
            gl_cell.font = green_font if unreal >= 0 else red_font

        ws_inv.cell(row=r, column=9, value=v["listing_status"])
        ws_inv.cell(row=r, column=10, value=v["listing_price"]).number_format = money_fmt
        ws_inv.cell(row=r, column=11, value=v.get("days_vaulted", 0))

        for c in range(1, 12):
            ws_inv.cell(row=r, column=c).border = thin_border

    for col, w in zip("ABCDEFGHIJK", [60, 14, 8, 8, 12, 10, 12, 12, 14, 12, 10]):
        ws_inv.column_dimensions[col].width = w
    ws_inv.freeze_panes = "A2"
    ws_inv.auto_filter.ref = f"A1:K{len(vault_held_sorted)+1}"

    # ── Match Details Sheet ──
    ws_match = wb.create_sheet("Match Details")
    ws_match.sheet_properties.tabColor = "9DC3E6"
    make_header(ws_match, [
        "Vault Item", "Vault Cert", "eBay Title", "eBay Item ID",
        "Purchase Price", "Total (w/ Ship)", "Purchase Date", "Method", "Confidence"
    ], "2E75B6")

    matches_sorted = sorted(matches, key=lambda x: x["total"], reverse=True)
    for r, m in enumerate(matches_sorted, 2):
        ws_match.cell(row=r, column=1, value=m["vault_item"])
        ws_match.cell(row=r, column=2, value=m["vault_cert"])
        ws_match.cell(row=r, column=3, value=m["ebay_title"])
        ws_match.cell(row=r, column=4, value=m["ebay_item_id"])
        ws_match.cell(row=r, column=5, value=m["price"]).number_format = money_fmt
        ws_match.cell(row=r, column=6, value=m["total"]).number_format = money_fmt
        if m["date"]:
            ws_match.cell(row=r, column=7, value=m["date"]).number_format = "MM/DD/YYYY"
        ws_match.cell(row=r, column=8, value=m["method"])

        conf_cell = ws_match.cell(row=r, column=9, value=m["confidence"])
        conf_cell.number_format = pct_fmt
        if m["confidence"] >= 0.8:
            conf_cell.fill = green_fill
        elif m["confidence"] >= 0.5:
            conf_cell.fill = yellow_fill
        else:
            conf_cell.fill = red_fill

        for c in range(1, 10):
            ws_match.cell(row=r, column=c).border = thin_border

    for col, w in zip("ABCDEFGHI", [55, 14, 55, 16, 12, 12, 14, 10, 12]):
        ws_match.column_dimensions[col].width = w
    ws_match.freeze_panes = "A2"
    ws_match.auto_filter.ref = f"A1:I{len(matches_sorted)+1}"

    # ── Unmatched Purchases (high-value) ──
    ws_unmatched = wb.create_sheet("Unmatched Purchases")
    ws_unmatched.sheet_properties.tabColor = "FF6600"
    make_header(ws_unmatched, ["Date", "eBay Item ID", "Title", "Price", "Total", "Seller"], "FF6600")

    matched_ids = {m["ebay_item_id"] for m in matches}
    # Also exclude purchases that match items already having vault cost
    unmatched_purchases = [p for p in purchases if p["item_id"] not in matched_ids]
    unmatched_purchases.sort(key=lambda x: x["total"], reverse=True)

    for r, p in enumerate(unmatched_purchases[:200], 2):
        if p["date"]:
            ws_unmatched.cell(row=r, column=1, value=p["date"]).number_format = "MM/DD/YYYY"
        ws_unmatched.cell(row=r, column=2, value=p["item_id"])
        ws_unmatched.cell(row=r, column=3, value=p["title"])
        ws_unmatched.cell(row=r, column=4, value=p["price"]).number_format = money_fmt
        ws_unmatched.cell(row=r, column=5, value=p["total"]).number_format = money_fmt
        ws_unmatched.cell(row=r, column=6, value=p["seller"])

    for col, w in zip("ABCDEF", [18, 16, 70, 14, 14, 18]):
        ws_unmatched.column_dimensions[col].width = w
    ws_unmatched.freeze_panes = "A2"

    wb.save(OUT)
    print(f"Saved to: {OUT}")
    return wb


if __name__ == "__main__":
    PURCHASE_HTML = "/home/user/sports-card-agent/data/ebay_reports/ebayReports/reports/transactionreports/purchaseHistory.html"
    VAULT_CSV = "/home/user/sports-card-agent/data/psa_vault_raw.csv"

    print("Parsing eBay purchases...")
    purchases = parse_purchases(PURCHASE_HTML)
    print(f"  {len(purchases)} purchases loaded")

    print("Parsing vault items...")
    vault_items = parse_vault(VAULT_CSV)
    print(f"  {len(vault_items)} vault items loaded")

    items_with_cost = len([v for v in vault_items if v["my_cost"] > 0])
    items_without_cost = len([v for v in vault_items if v["my_cost"] == 0 and not v["cert"].startswith("VIH")])
    print(f"  {items_with_cost} already have cost, {items_without_cost} need matching")

    print("\nRunning matching engine...")
    matches = match_purchases_to_vault(purchases, vault_items)

    cert_matches = [m for m in matches if m["method"] == "cert_exact"]
    fuzzy_matches = [m for m in matches if m["method"] == "fuzzy"]
    high_conf = [m for m in fuzzy_matches if m["confidence"] >= 0.7]
    med_conf = [m for m in fuzzy_matches if 0.5 <= m["confidence"] < 0.7]
    low_conf = [m for m in fuzzy_matches if m["confidence"] < 0.5]

    print(f"\n  Matches found: {len(matches)}")
    print(f"    Cert exact:     {len(cert_matches)}")
    print(f"    Fuzzy (high):   {len(high_conf)}")
    print(f"    Fuzzy (med):    {len(med_conf)}")
    print(f"    Fuzzy (low):    {len(low_conf)}")

    total_matched_cost = sum(m["total"] for m in matches)
    print(f"    Total cost matched: ${total_matched_cost:,.2f}")

    new_items_with_cost = items_with_cost + len(matches)
    print(f"\n  Cost coverage: {items_with_cost} -> {new_items_with_cost} items ({new_items_with_cost}/{len(vault_items)})")

    print("\nBuilding updated P&L Excel...")
    update_excel_with_costs(matches, vault_items)

    # Final P&L
    vault_sold = [v for v in vault_items if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    sold_cost = sum(v["my_cost"] for v in vault_sold if v["my_cost"] > 0)
    sold_proceeds = sum(v["sold_proceeds"] for v in vault_sold)
    vault_held = [v for v in vault_items if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    held_est = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)

    print(f"\n{'='*60}")
    print(f"  UPDATED P&L (WITH MATCHED COSTS)")
    print(f"")
    print(f"  REALIZED (SOLD)")
    print(f"    Sold Proceeds:      ${sold_proceeds:>12,.2f}")
    print(f"    Cost Basis (sold):  ${sold_cost:>12,.2f}")
    print(f"    Realized P&L:       ${sold_proceeds - sold_cost:>12,.2f}")
    print(f"")
    print(f"  UNREALIZED (HELD)")
    print(f"    Held Cost Basis:    ${held_cost:>12,.2f}")
    print(f"    PSA Estimate:       ${held_est:>12,.2f}")
    print(f"    Unrealized G/L:     ${held_est - held_cost:>12,.2f}")
    print(f"")
    print(f"  TOTAL")
    total_pnl = (sold_proceeds - sold_cost) + (held_est - held_cost)
    print(f"    Total P&L (est):    ${total_pnl:>12,.2f}")
    print(f"{'='*60}")
