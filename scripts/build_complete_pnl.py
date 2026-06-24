"""Build complete P&L across eBay purchases, PSA Vault sales, and Goldin consignments."""

import csv
import re
from collections import defaultdict
from datetime import datetime

from bs4 import BeautifulSoup
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ── Parsing helpers ──

def pf(s):
    try:
        return float(str(s).replace(",", "").replace("$", "").strip()) if s else 0
    except (ValueError, TypeError):
        return 0

def pi(s):
    try:
        return int(s) if s else 0
    except (ValueError, TypeError):
        return 0

def parse_date(s):
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y %I:%M%p", "%b %d, %Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None

def normalize(s):
    s = str(s).upper()
    s = re.sub(r'[^A-Z0-9/ ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ── Parse eBay purchases ──

def parse_ebay_purchases(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")
    cells = soup.find_all("td", class_=re.compile(r"bottomBorder"))
    texts = [c.get_text(strip=True) for c in cells]
    items = []
    for i in range(0, len(texts), 9):
        ch = texts[i:i+9]
        if len(ch) != 9:
            continue
        price = pf(ch[3])
        total = pf(ch[6])
        if ch[2] and (price > 0 or total > 0):
            items.append({
                "date": parse_date(ch[0]),
                "item_id": ch[1],
                "title": ch[2],
                "price": price,
                "shipping": pf(ch[5]),
                "total": total if total > 0 else price + pf(ch[5]),
                "seller": ch[8],
                "source": "eBay",
            })
    return items


# ── Parse Goldin history ──

def parse_goldin(path):
    wb = load_workbook(path, read_only=True)
    ws = wb.active

    section = None
    sold = []
    live = []
    pending_auth = []
    pending_placement = []
    upcoming = []
    buy_now = []

    for row in ws.iter_rows(min_row=1, values_only=True):
        if not row or len(row) < 2:
            continue
        auction = str(row[0]).strip() if row[0] else ""
        title = str(row[1]).strip() if row[1] else ""
        price = pf(row[2]) if len(row) > 2 and row[2] else 0

        if title in ("Sold", "Live", "Buy It Now", "Upcoming", "Pending Authentication", "Pending Auction Placement"):
            section = title
            continue
        if title in ("Title", "") or not title:
            continue

        item = {
            "auction": auction,
            "title": title,
            "price": price,
            "source": "Goldin",
        }

        if section == "Sold":
            sold.append(item)
        elif section == "Live":
            live.append(item)
        elif section == "Buy It Now":
            buy_now.append(item)
        elif section == "Upcoming":
            upcoming.append(item)
        elif section == "Pending Authentication":
            pending_auth.append(item)
        elif section == "Pending Auction Placement":
            pending_placement.append(item)

    wb.close()
    return {
        "sold": sold,
        "live": live,
        "buy_now": buy_now,
        "upcoming": upcoming,
        "pending_auth": pending_auth,
        "pending_placement": pending_placement,
    }


# ── Parse PSA Vault ──

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
            grader = "VIH" if cert.startswith("VIH") else ("BGS" if cert.startswith("00") else "PSA")

            items.append({
                "item": val(1), "cert": cert, "grader": grader,
                "grade": val(3), "year": val(6), "set": val(7),
                "subject": val(9), "my_cost": pf(val(12)),
                "psa_estimate": pf(val(13)), "vault_status": val(19),
                "listing_status": val(22), "listing_price": pf(val(24)),
                "sold_price": pf(val(28)), "sold_fees": pf(val(29)),
                "sold_proceeds": pf(val(30)), "sold_on": val(26),
            })
    return items


# ── Parse eBay returns ──

def parse_returns(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")
    rows = soup.find_all("tr")
    returns = []
    for row in rows:
        cells = row.find_all("td", class_="td")
        if len(cells) >= 6:
            title = cells[2].get_text(strip=True)
            refund = pf(cells[7].get_text(strip=True)) if len(cells) > 7 else 0
            if title:
                returns.append({"title": title, "refund_amount": refund})
    return returns


# ── Build Excel ──

def make_header(ws, headers, color="1F4E79"):
    hf = Font(bold=True, color="FFFFFF", size=11)
    fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = hf
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")

MONEY = '#,##0.00'
PCT = '0.0%'
DATE = 'MM/DD/YYYY'
GREEN_F = Font(color="006100")
GREEN_BG = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
RED_F = Font(color="9C0006")
RED_BG = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
YELLOW_BG = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
BORDER = Border(bottom=Side(style="thin", color="CCCCCC"))


def build_pnl(ebay_purchases, goldin, vault_items, returns):
    wb = Workbook()

    goldin_sold = goldin["sold"]
    goldin_pending = goldin["pending_auth"] + goldin["pending_placement"]
    goldin_live = goldin["live"] + goldin["upcoming"] + goldin["buy_now"]

    vault_sold = [v for v in vault_items if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    vault_held = [v for v in vault_items if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    vault_listed = [v for v in vault_items if v["listing_status"] == "Fixed Price" and v["sold_price"] == 0]

    # Totals
    total_ebay_spent = sum(p["total"] for p in ebay_purchases)
    total_goldin_sold_price = sum(g["price"] for g in goldin_sold)
    goldin_bp = total_goldin_sold_price * 0.20  # ~20% buyer's premium already in price
    total_vault_sold_price = sum(v["sold_price"] for v in vault_sold)
    total_vault_proceeds = sum(v["sold_proceeds"] for v in vault_sold)
    total_vault_fees = sum(v["sold_fees"] for v in vault_sold)
    total_vault_cost = sum(v["my_cost"] for v in vault_items if v["my_cost"] > 0)
    held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    held_est = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)
    listed_price = sum(v["listing_price"] for v in vault_listed)
    total_refunds = sum(r["refund_amount"] for r in returns)

    # ── 1. P&L Summary ──
    ws = wb.active
    ws.title = "P&L Summary"
    ws.sheet_properties.tabColor = "1F4E79"

    def add_row(r, label, value, is_header=False, is_pnl=False, is_money=True):
        ws.cell(row=r, column=1, value=label)
        cell = ws.cell(row=r, column=2, value=value)
        if is_money and isinstance(value, (int, float)) and value != 0:
            cell.number_format = MONEY
        if is_header:
            ws.cell(row=r, column=1).font = Font(bold=True, size=13, color="1F4E79")
        if is_pnl and isinstance(value, (int, float)):
            ws.cell(row=r, column=1).font = Font(bold=True, size=12)
            cell.font = Font(bold=True, size=12, color="006100" if value >= 0 else "9C0006")
            cell.fill = GREEN_BG if value >= 0 else RED_BG
            cell.number_format = MONEY

    r = 1
    add_row(r, "COMPLETE P&L - ALL PLATFORMS", "", True, False, False); r += 1
    add_row(r, "Generated", datetime.now().strftime("%Y-%m-%d %H:%M"), False, False, False); r += 2

    add_row(r, "BUYING (eBay)", "", True); r += 1
    add_row(r, "Total eBay Purchases", len(ebay_purchases), False, False, False); r += 1
    add_row(r, "Total Spent on eBay", total_ebay_spent); r += 1
    add_row(r, "Avg Purchase Price", total_ebay_spent / max(len(ebay_purchases), 1)); r += 2

    add_row(r, "BUYING (Goldin Auctions)", "", True); r += 1
    add_row(r, "Total Goldin Purchases (Sold to you)", len(goldin_sold), False, False, False); r += 1
    add_row(r, "Total Goldin Spend (hammer + BP)", total_goldin_sold_price); r += 1
    add_row(r, "Avg Goldin Purchase", total_goldin_sold_price / max(len(goldin_sold), 1)); r += 2

    total_all_spent = total_ebay_spent + total_goldin_sold_price
    add_row(r, "TOTAL ALL PURCHASES", "", True); r += 1
    add_row(r, "Combined Purchases", len(ebay_purchases) + len(goldin_sold), False, False, False); r += 1
    add_row(r, "Total Capital Deployed", total_all_spent, False, True); r += 2

    add_row(r, "SELLING (PSA Vault / eBay)", "", True); r += 1
    add_row(r, "Vault Items Sold", len(vault_sold), False, False, False); r += 1
    add_row(r, "Gross Sale Price", total_vault_sold_price); r += 1
    add_row(r, "Fees Paid", total_vault_fees); r += 1
    add_row(r, "Net Proceeds", total_vault_proceeds); r += 2

    add_row(r, "RETURNS & REFUNDS", "", True); r += 1
    add_row(r, "Total Returns", len(returns), False, False, False); r += 1
    add_row(r, "Total Refunded", total_refunds); r += 2

    sold_cost = sum(v["my_cost"] for v in vault_sold if v["my_cost"] > 0)
    realized_pnl = total_vault_proceeds - sold_cost
    add_row(r, "REALIZED P&L", "", True); r += 1
    add_row(r, "Sale Proceeds (net)", total_vault_proceeds); r += 1
    add_row(r, "Cost Basis of Sold Items", sold_cost); r += 1
    add_row(r, "Realized P&L", realized_pnl, False, True); r += 2

    add_row(r, "CURRENT INVENTORY", "", True); r += 1
    add_row(r, "Cards in Vault (unsold)", len(vault_held), False, False, False); r += 1
    add_row(r, "Cost Basis (held)", held_cost); r += 1
    add_row(r, "PSA Estimate (held)", held_est); r += 1
    unreal = held_est - held_cost
    add_row(r, "Unrealized G/L (Est vs Cost)", unreal, False, True); r += 1
    add_row(r, "Cards Listed on eBay", len(vault_listed), False, False, False); r += 1
    add_row(r, "Total Listing Price", listed_price); r += 2

    add_row(r, "GOLDIN PIPELINE", "", True); r += 1
    add_row(r, "Pending Authentication", len(goldin["pending_auth"]), False, False, False); r += 1
    add_row(r, "Pending Auction Placement", len(goldin["pending_placement"]), False, False, False); r += 1
    add_row(r, "Live Auctions", len(goldin["live"]), False, False, False); r += 1
    add_row(r, "Upcoming Auctions", len(goldin["upcoming"]), False, False, False); r += 1
    add_row(r, "Buy It Now", len(goldin["buy_now"]), False, False, False); r += 1
    total_pipeline = len(goldin["pending_auth"]) + len(goldin["pending_placement"]) + len(goldin["live"]) + len(goldin["upcoming"]) + len(goldin["buy_now"])
    add_row(r, "Total Pipeline Cards", total_pipeline, False, False, False); r += 2

    add_row(r, "OVERALL POSITION", "", True); r += 1
    add_row(r, "Total Capital In", total_all_spent); r += 1
    add_row(r, "Total Cash Out (proceeds)", total_vault_proceeds); r += 1
    add_row(r, "Cash Position (Out - In)", total_vault_proceeds - total_all_spent, False, True); r += 1
    add_row(r, "Held Inventory (PSA Est)", held_est); r += 1
    add_row(r, "Pipeline Cards (Goldin)", total_pipeline, False, False, False); r += 1

    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 22

    # ── 2. eBay Purchases ──
    ws2 = wb.create_sheet("eBay Purchases")
    ws2.sheet_properties.tabColor = "4472C4"
    make_header(ws2, ["Date", "eBay Item ID", "Title", "Price", "Shipping", "Total", "Seller"], "4472C4")
    ebay_sorted = sorted(ebay_purchases, key=lambda x: x["date"] or datetime.min, reverse=True)
    for r, p in enumerate(ebay_sorted, 2):
        if p["date"]:
            ws2.cell(row=r, column=1, value=p["date"]).number_format = DATE
        ws2.cell(row=r, column=2, value=p["item_id"])
        ws2.cell(row=r, column=3, value=p["title"])
        ws2.cell(row=r, column=4, value=p["price"]).number_format = MONEY
        ws2.cell(row=r, column=5, value=p["shipping"]).number_format = MONEY
        ws2.cell(row=r, column=6, value=p["total"]).number_format = MONEY
        ws2.cell(row=r, column=7, value=p["seller"])
    for col, w in zip("ABCDEFG", [18, 16, 70, 12, 10, 12, 18]):
        ws2.column_dimensions[col].width = w
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = f"A1:G{len(ebay_sorted)+1}"

    # ── 3. Goldin Purchases ──
    ws3 = wb.create_sheet("Goldin Purchases")
    ws3.sheet_properties.tabColor = "ED7D31"
    make_header(ws3, ["Auction", "Card", "Price Paid"], "ED7D31")
    goldin_sorted = sorted(goldin_sold, key=lambda x: x["price"], reverse=True)
    for r, g in enumerate(goldin_sorted, 2):
        ws3.cell(row=r, column=1, value=g["auction"])
        ws3.cell(row=r, column=2, value=g["title"])
        ws3.cell(row=r, column=3, value=g["price"]).number_format = MONEY
    ws3.column_dimensions["A"].width = 35
    ws3.column_dimensions["B"].width = 90
    ws3.column_dimensions["C"].width = 14
    ws3.freeze_panes = "A2"
    ws3.auto_filter.ref = f"A1:C{len(goldin_sorted)+1}"

    # ── 4. Vault Sales P&L ──
    ws4 = wb.create_sheet("Vault Sales P&L")
    ws4.sheet_properties.tabColor = "70AD47"
    make_header(ws4, ["Item", "Cert", "Grade", "My Cost", "Sold Price", "Fees",
                       "Net Proceeds", "P&L ($)", "P&L (%)", "Sold On"], "375623")
    vs = sorted(vault_sold, key=lambda x: x["sold_proceeds"], reverse=True)
    for r, v in enumerate(vs, 2):
        pnl = v["sold_proceeds"] - v["my_cost"] if v["my_cost"] > 0 else 0
        pnl_pct = pnl / v["my_cost"] if v["my_cost"] > 0 else 0
        ws4.cell(row=r, column=1, value=v["item"])
        ws4.cell(row=r, column=2, value=v["cert"])
        ws4.cell(row=r, column=3, value=v["grade"])
        ws4.cell(row=r, column=4, value=v["my_cost"]).number_format = MONEY
        ws4.cell(row=r, column=5, value=v["sold_price"]).number_format = MONEY
        ws4.cell(row=r, column=6, value=v["sold_fees"]).number_format = MONEY
        ws4.cell(row=r, column=7, value=v["sold_proceeds"]).number_format = MONEY
        pc = ws4.cell(row=r, column=8, value=pnl)
        pc.number_format = MONEY
        if v["my_cost"] > 0:
            pc.font = GREEN_F if pnl >= 0 else RED_F
            pc.fill = GREEN_BG if pnl >= 0 else RED_BG
        pp = ws4.cell(row=r, column=9, value=pnl_pct)
        pp.number_format = PCT
        ws4.cell(row=r, column=10, value=v["sold_on"])
    for col, w in zip("ABCDEFGHIJ", [60, 14, 8, 12, 12, 10, 12, 12, 10, 14]):
        ws4.column_dimensions[col].width = w
    ws4.freeze_panes = "A2"
    ws4.auto_filter.ref = f"A1:J{len(vs)+1}"

    # ── 5. Current Inventory ──
    ws5 = wb.create_sheet("Current Inventory")
    ws5.sheet_properties.tabColor = "FFC000"
    make_header(ws5, ["Item", "Cert", "Grade", "My Cost", "PSA Est",
                       "Unrealized G/L", "Listed?", "List Price"], "BF8F00")
    vh = sorted(vault_held, key=lambda x: x["my_cost"], reverse=True)
    for r, v in enumerate(vh, 2):
        u = v["psa_estimate"] - v["my_cost"] if v["my_cost"] > 0 and v["psa_estimate"] > 0 else 0
        ws5.cell(row=r, column=1, value=v["item"])
        ws5.cell(row=r, column=2, value=v["cert"])
        ws5.cell(row=r, column=3, value=v["grade"])
        ws5.cell(row=r, column=4, value=v["my_cost"]).number_format = MONEY
        ws5.cell(row=r, column=5, value=v["psa_estimate"]).number_format = MONEY
        gc = ws5.cell(row=r, column=6, value=u)
        gc.number_format = MONEY
        if v["my_cost"] > 0 and v["psa_estimate"] > 0:
            gc.font = GREEN_F if u >= 0 else RED_F
        ws5.cell(row=r, column=7, value=v["listing_status"])
        ws5.cell(row=r, column=8, value=v["listing_price"]).number_format = MONEY
    for col, w in zip("ABCDEFGH", [60, 14, 8, 12, 12, 12, 14, 12]):
        ws5.column_dimensions[col].width = w
    ws5.freeze_panes = "A2"
    ws5.auto_filter.ref = f"A1:H{len(vh)+1}"

    # ── 6. Goldin Pipeline ──
    ws6 = wb.create_sheet("Goldin Pipeline")
    ws6.sheet_properties.tabColor = "7030A0"
    make_header(ws6, ["Status", "Card"], "7030A0")
    pipeline = []
    for item in goldin["pending_auth"]:
        pipeline.append(("Pending Auth", item["title"]))
    for item in goldin["pending_placement"]:
        pipeline.append(("Pending Placement", item["title"]))
    for item in goldin["live"]:
        pipeline.append(("Live", item["title"]))
    for item in goldin["upcoming"]:
        pipeline.append(("Upcoming", item["title"]))
    for item in goldin["buy_now"]:
        pipeline.append(("Buy It Now", item["title"]))
    for r, (status, title) in enumerate(pipeline, 2):
        ws6.cell(row=r, column=1, value=status)
        ws6.cell(row=r, column=2, value=title)
    ws6.column_dimensions["A"].width = 20
    ws6.column_dimensions["B"].width = 100
    ws6.freeze_panes = "A2"
    ws6.auto_filter.ref = f"A1:B{len(pipeline)+1}"

    # ── 7. Top 50 All Purchases ──
    ws7 = wb.create_sheet("Top 50 All Purchases")
    ws7.sheet_properties.tabColor = "C00000"
    make_header(ws7, ["Rank", "Platform", "Title", "Amount"], "C00000")
    all_buys = []
    for p in ebay_purchases:
        all_buys.append({"platform": "eBay", "title": p["title"], "amount": p["total"]})
    for g in goldin_sold:
        all_buys.append({"platform": "Goldin", "title": g["title"], "amount": g["price"]})
    all_buys.sort(key=lambda x: x["amount"], reverse=True)
    for r, b in enumerate(all_buys[:50], 2):
        ws7.cell(row=r, column=1, value=r - 1)
        ws7.cell(row=r, column=2, value=b["platform"])
        ws7.cell(row=r, column=3, value=b["title"])
        ws7.cell(row=r, column=4, value=b["amount"]).number_format = MONEY
    ws7.column_dimensions["A"].width = 6
    ws7.column_dimensions["B"].width = 10
    ws7.column_dimensions["C"].width = 90
    ws7.column_dimensions["D"].width = 14
    ws7.freeze_panes = "A2"

    OUT = "/home/user/sports-card-agent/Inventory/eBay_PnL.xlsx"
    wb.save(OUT)
    return OUT


if __name__ == "__main__":
    PURCHASE_HTML = "/home/user/sports-card-agent/data/ebay_reports/ebayReports/reports/transactionreports/purchaseHistory.html"
    RETURNS_HTML = "/home/user/sports-card-agent/data/ebay_reports/ebayReports/reports/transactionreports/returnsAndRefunds.html"
    VAULT_CSV = "/home/user/sports-card-agent/data/psa_vault_raw.csv"
    GOLDIN_XLSX = "/home/user/sports-card-agent/data/goldin_full_history.xlsx"

    print("Parsing eBay purchases...")
    ebay = parse_ebay_purchases(PURCHASE_HTML)
    print(f"  {len(ebay)} purchases, ${sum(p['total'] for p in ebay):,.2f}")

    print("Parsing Goldin history...")
    goldin = parse_goldin(GOLDIN_XLSX)
    print(f"  {len(goldin['sold'])} sold (purchased), ${sum(g['price'] for g in goldin['sold']):,.2f}")
    print(f"  {len(goldin['pending_auth'])} pending auth")
    print(f"  {len(goldin['pending_placement'])} pending placement")
    print(f"  {len(goldin['live'])} live")
    print(f"  {len(goldin['upcoming'])} upcoming")

    print("Parsing PSA Vault...")
    vault = parse_vault(VAULT_CSV)
    vault_sold = [v for v in vault if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    vault_held = [v for v in vault if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    print(f"  {len(vault)} total, {len(vault_sold)} sold, {len(vault_held)} held")

    print("Parsing returns...")
    returns = parse_returns(RETURNS_HTML)
    print(f"  {len(returns)} returns")

    print("\nBuilding complete P&L...")
    out = build_pnl(ebay, goldin, vault, returns)

    total_ebay = sum(p["total"] for p in ebay)
    total_goldin = sum(g["price"] for g in goldin["sold"])
    total_vault_proceeds = sum(v["sold_proceeds"] for v in vault_sold)
    held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    held_est = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)
    pipeline = len(goldin["pending_auth"]) + len(goldin["pending_placement"]) + len(goldin["live"]) + len(goldin["upcoming"])

    print(f"\n{'='*65}")
    print(f"  COMPLETE P&L ACROSS ALL PLATFORMS")
    print(f"{'='*65}")
    print(f"")
    print(f"  CAPITAL IN")
    print(f"    eBay Purchases:       {len(ebay):>5,} cards   ${total_ebay:>12,.2f}")
    print(f"    Goldin Purchases:     {len(goldin['sold']):>5,} cards   ${total_goldin:>12,.2f}")
    print(f"    ─────────────────────────────────────────────")
    print(f"    TOTAL DEPLOYED:       {len(ebay)+len(goldin['sold']):>5,} cards   ${total_ebay+total_goldin:>12,.2f}")
    print(f"")
    print(f"  CAPITAL OUT")
    print(f"    Vault Sales (net):    {len(vault_sold):>5,} cards   ${total_vault_proceeds:>12,.2f}")
    print(f"")
    print(f"  CASH POSITION")
    cash = total_vault_proceeds - total_ebay - total_goldin
    print(f"    Cash In - Cash Out:                  ${cash:>12,.2f}")
    print(f"")
    print(f"  CURRENT ASSETS")
    print(f"    Vault Inventory:      {len(vault_held):>5,} cards")
    print(f"      Cost Basis:                        ${held_cost:>12,.2f}")
    print(f"      PSA Estimate:                      ${held_est:>12,.2f}")
    print(f"    Goldin Pipeline:      {pipeline:>5,} cards")
    print(f"")
    print(f"  NET POSITION (Cash + Held Est)")
    net = cash + held_est
    print(f"    ${net:>12,.2f}")
    print(f"{'='*65}")
    print(f"\nSaved to: {out}")
