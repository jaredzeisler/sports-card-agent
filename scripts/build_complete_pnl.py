"""Build complete P&L across eBay purchases, PSA Vault sales, and Goldin consignment sales."""

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

def parse_goldin_balance(path):
    deposits = []
    withdrawals = []
    adjustments = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            op = row["operation_type"].strip()
            amt = float(row["amount_changed"])
            desc = row.get("description", "").strip()
            ts = row["timestamp"][:7]
            if op == "deposit":
                deposits.append({"amount": amt, "description": desc, "month": ts})
            elif op == "withdrawal":
                withdrawals.append({"amount": amt, "description": desc, "month": ts})
            elif op == "adjustment":
                adjustments.append({"amount": amt, "description": desc, "month": ts})
    return {
        "deposits": deposits,
        "withdrawals": withdrawals,
        "adjustments": adjustments,
        "total_proceeds": sum(d["amount"] for d in deposits),
        "total_payouts": abs(sum(w["amount"] for w in withdrawals)),
        "total_adjustments": sum(a["amount"] for a in adjustments),
    }


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


def parse_fanatics_collect(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get("title", "").strip()
            if not title:
                continue
            sale_cents = int(row["sale_price_in_cents"]) if row.get("sale_price_in_cents") else 0
            net_cents = int(row["seller_net_in_cents"]) if row.get("seller_net_in_cents") else 0
            fee_pct = float(row["seller_fee_percentage"]) if row.get("seller_fee_percentage") else 0
            status = row.get("payout_status", "").strip()
            sale_date = row.get("sale_date", "")[:10]
            cert = row.get("certification_number", "").strip()
            items.append({
                "title": title, "cert": cert,
                "sale_price": sale_cents / 100, "net_proceeds": net_cents / 100,
                "fee_pct": fee_pct, "status": status, "date": sale_date,
            })
    total_sale = sum(i["sale_price"] for i in items)
    total_net = sum(i["net_proceeds"] for i in items)
    return {"items": items, "total_sale": total_sale, "total_net": total_net}


def parse_wheelhouse(path):
    from openpyxl import load_workbook as lwb
    wb = lwb(path, read_only=True, data_only=True)
    items = []
    for sheet_name in wb.sheetnames:
        if sheet_name == "TOTALS":
            continue
        ws = wb[sheet_name]
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            if not row or row[0] is None:
                continue
            title = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            hammer = float(row[2]) if len(row) > 2 and row[2] else 0
            gross = float(row[4]) if len(row) > 4 and row[4] else 0
            cgc_fee = float(row[5]) if len(row) > 5 and row[5] else 0
            net = float(row[6]) if len(row) > 6 and row[6] else 0
            status = str(row[7]) if len(row) > 7 and row[7] else ""
            sale_date = str(row[8])[:10] if len(row) > 8 and row[8] else ""
            if "TOTALS" in title or not title:
                continue
            if hammer == 0 and "Cancelled" in status:
                continue
            items.append({
                "title": title, "hammer": hammer, "gross": gross,
                "fee": cgc_fee or 0, "net": net,
                "status": status, "date": sale_date, "auction": sheet_name,
            })
    wb.close()
    total_net = sum(i["net"] for i in items)
    total_hammer = sum(i["hammer"] for i in items)
    total_gross = sum(i["gross"] for i in items)
    return {"items": items, "total_net": total_net, "total_hammer": total_hammer, "total_gross": total_gross}


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


def build_pnl(ebay_purchases, goldin, vault_items, returns, vault_bank_total=0, vault_bank_txns=0,
              goldin_balance=None, fanatics=None, wheelhouse=None):
    wb = Workbook()

    goldin_sold = goldin["sold"]
    goldin_pending = goldin["pending_auth"] + goldin["pending_placement"]
    goldin_live = goldin["live"] + goldin["upcoming"] + goldin["buy_now"]

    vault_sold = [v for v in vault_items if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    vault_held = [v for v in vault_items if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    vault_listed = [v for v in vault_items if v["listing_status"] == "Fixed Price" and v["sold_price"] == 0]

    if goldin_balance is None:
        goldin_balance = {"deposits": [], "withdrawals": [], "adjustments": [],
                          "total_proceeds": 0, "total_payouts": 0, "total_adjustments": 0}
    if fanatics is None:
        fanatics = {"items": [], "total_sale": 0, "total_net": 0}
    if wheelhouse is None:
        wheelhouse = {"items": [], "total_net": 0, "total_hammer": 0, "total_gross": 0}

    goldin_sale_proceeds = goldin_balance["total_proceeds"]
    goldin_fees = abs(goldin_balance["total_adjustments"])
    goldin_net_proceeds = goldin_sale_proceeds - goldin_fees
    goldin_sale_count = len(goldin_balance["deposits"])
    wh_net = wheelhouse["total_net"]
    wh_count = len(wheelhouse["items"])
    fc_sale = fanatics["total_sale"]
    fc_net = fanatics["total_net"]
    fc_count = len(fanatics["items"])

    # Totals
    total_ebay_spent = sum(p["total"] for p in ebay_purchases)
    total_goldin_sold_price = sum(g["price"] for g in goldin_sold)
    total_vault_sold_price = sum(v["sold_price"] for v in vault_sold)
    total_vault_proceeds = vault_bank_total if vault_bank_total > 0 else sum(v["sold_proceeds"] for v in vault_sold)
    total_vault_fees = sum(v["sold_fees"] for v in vault_sold)
    total_vault_cost = sum(v["my_cost"] for v in vault_items if v["my_cost"] > 0)
    held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    held_est = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)
    listed_price = sum(v["listing_price"] for v in vault_listed)
    total_refunds = sum(r["refund_amount"] for r in returns)
    total_all_revenue = total_vault_proceeds + goldin_sale_proceeds + wh_net

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

    add_row(r, "SELLING (Fanatics Collect / PSA Vault)", "", True); r += 1
    add_row(r, "Stripe Deposit Transactions", vault_bank_txns if vault_bank_txns else len(vault_sold), False, False, False); r += 1
    add_row(r, "Total Deposited to Bank", total_vault_proceeds); r += 1
    add_row(r, "Fanatics Buy Now Sales (detail)", fc_count, False, False, False); r += 1
    add_row(r, "Fanatics Gross Sale Price", fc_sale); r += 1
    add_row(r, "Fanatics Net (after fees)", fc_net); r += 2

    add_row(r, "SELLING (Goldin Consignment Sales)", "", True); r += 1
    add_row(r, "Goldin Sale Transactions", goldin_sale_count, False, False, False); r += 1
    add_row(r, "Gross Sale Proceeds", goldin_sale_proceeds); r += 1
    add_row(r, "Goldin Fees (grading/adjustments)", -goldin_fees); r += 1
    add_row(r, "Net Goldin Proceeds", goldin_net_proceeds); r += 2

    add_row(r, "SELLING (Wheelhouse Auctions)", "", True); r += 1
    add_row(r, "Wheelhouse Lots Sold", wh_count, False, False, False); r += 1
    add_row(r, "Total Hammer Price", wheelhouse["total_hammer"]); r += 1
    add_row(r, "JZ Net Proceeds", wh_net); r += 2

    add_row(r, "TOTAL ALL REVENUE", "", True); r += 1
    add_row(r, "Fanatics/PSA Vault Deposits", total_vault_proceeds); r += 1
    add_row(r, "Goldin Net Proceeds", goldin_net_proceeds); r += 1
    add_row(r, "Wheelhouse Net Proceeds", wh_net); r += 1
    add_row(r, "Combined Revenue", total_all_revenue, False, True); r += 2

    add_row(r, "RETURNS & REFUNDS", "", True); r += 1
    add_row(r, "Total Returns", len(returns), False, False, False); r += 1
    add_row(r, "Total Refunded", total_refunds); r += 2

    sold_cost = sum(v["my_cost"] for v in vault_sold if v["my_cost"] > 0)
    realized_pnl = total_all_revenue - sold_cost
    add_row(r, "REALIZED P&L", "", True); r += 1
    add_row(r, "Total Revenue (all platforms)", total_all_revenue); r += 1
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
    add_row(r, "Total Cash Out (all platforms)", total_all_revenue); r += 1
    add_row(r, "Cash Position (Out - In)", total_all_revenue - total_all_spent, False, True); r += 1
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

    # ── 7. Goldin Sales ──
    ws7 = wb.create_sheet("Goldin Sales")
    ws7.sheet_properties.tabColor = "E97132"
    make_header(ws7, ["Date", "Card", "Proceeds"], "E97132")
    goldin_sales_sorted = sorted(goldin_balance["deposits"], key=lambda x: x["amount"], reverse=True)
    for r, d in enumerate(goldin_sales_sorted, 2):
        desc = d["description"]
        if desc.startswith("Proceeds from "):
            desc = desc[len("Proceeds from "):]
        ws7.cell(row=r, column=1, value=d["month"])
        ws7.cell(row=r, column=2, value=desc)
        ws7.cell(row=r, column=3, value=d["amount"]).number_format = MONEY
    ws7.column_dimensions["A"].width = 12
    ws7.column_dimensions["B"].width = 100
    ws7.column_dimensions["C"].width = 14
    ws7.freeze_panes = "A2"
    ws7.auto_filter.ref = f"A1:C{len(goldin_sales_sorted)+1}"

    # ── 8. Fanatics Collect Sales ──
    ws8 = wb.create_sheet("Fanatics Collect Sales")
    ws8.sheet_properties.tabColor = "00A3E0"
    make_header(ws8, ["Date", "Card", "Cert", "Sale Price", "Fee %", "Net Proceeds", "Status"], "00A3E0")
    fc_sorted = sorted(fanatics["items"], key=lambda x: x["sale_price"], reverse=True)
    for r, item in enumerate(fc_sorted, 2):
        ws8.cell(row=r, column=1, value=item["date"])
        ws8.cell(row=r, column=2, value=item["title"])
        ws8.cell(row=r, column=3, value=item["cert"])
        ws8.cell(row=r, column=4, value=item["sale_price"]).number_format = MONEY
        ws8.cell(row=r, column=5, value=item["fee_pct"] / 100 if item["fee_pct"] else 0).number_format = PCT
        ws8.cell(row=r, column=6, value=item["net_proceeds"]).number_format = MONEY
        ws8.cell(row=r, column=7, value=item["status"])
    for col, w in zip("ABCDEFG", [12, 80, 14, 12, 8, 12, 22]):
        ws8.column_dimensions[col].width = w
    ws8.freeze_panes = "A2"
    ws8.auto_filter.ref = f"A1:G{len(fc_sorted)+1}"

    # ── 9. Wheelhouse Sales ──
    ws9 = wb.create_sheet("Wheelhouse Sales")
    ws9.sheet_properties.tabColor = "2E75B6"
    make_header(ws9, ["Auction", "Card", "Hammer", "JZ Gross", "CGC Fee", "JZ Net", "Status"], "2E75B6")
    wh_sorted = sorted(wheelhouse["items"], key=lambda x: x["net"], reverse=True)
    for r, item in enumerate(wh_sorted, 2):
        ws9.cell(row=r, column=1, value=item["auction"])
        ws9.cell(row=r, column=2, value=item["title"])
        ws9.cell(row=r, column=3, value=item["hammer"]).number_format = MONEY
        ws9.cell(row=r, column=4, value=item["gross"]).number_format = MONEY
        ws9.cell(row=r, column=5, value=item["fee"]).number_format = MONEY
        ws9.cell(row=r, column=6, value=item["net"]).number_format = MONEY
        ws9.cell(row=r, column=7, value=item["status"])
    for col, w in zip("ABCDEFG", [10, 80, 12, 12, 10, 12, 18]):
        ws9.column_dimensions[col].width = w
    ws9.freeze_panes = "A2"
    ws9.auto_filter.ref = f"A1:G{len(wh_sorted)+1}"

    # ── 10. Top 50 All Purchases ──
    ws10 = wb.create_sheet("Top 50 All Purchases")
    ws10.sheet_properties.tabColor = "C00000"
    make_header(ws10, ["Rank", "Platform", "Title", "Amount"], "C00000")
    all_buys = []
    for p in ebay_purchases:
        all_buys.append({"platform": "eBay", "title": p["title"], "amount": p["total"]})
    for g in goldin_sold:
        all_buys.append({"platform": "Goldin", "title": g["title"], "amount": g["price"]})
    all_buys.sort(key=lambda x: x["amount"], reverse=True)
    for r, b in enumerate(all_buys[:50], 2):
        ws10.cell(row=r, column=1, value=r - 1)
        ws10.cell(row=r, column=2, value=b["platform"])
        ws10.cell(row=r, column=3, value=b["title"])
        ws10.cell(row=r, column=4, value=b["amount"]).number_format = MONEY
    ws10.column_dimensions["A"].width = 6
    ws10.column_dimensions["B"].width = 10
    ws10.column_dimensions["C"].width = 90
    ws10.column_dimensions["D"].width = 14
    ws10.freeze_panes = "A2"

    OUT = "/home/user/sports-card-agent/Inventory/eBay_PnL.xlsx"
    wb.save(OUT)
    return OUT


if __name__ == "__main__":
    PURCHASE_HTML = "/home/user/sports-card-agent/data/ebay_reports/ebayReports/reports/transactionreports/purchaseHistory.html"
    RETURNS_HTML = "/home/user/sports-card-agent/data/ebay_reports/ebayReports/reports/transactionreports/returnsAndRefunds.html"
    VAULT_CSV = "/home/user/sports-card-agent/data/psa_vault_raw.csv"
    GOLDIN_XLSX = "/home/user/sports-card-agent/data/goldin_full_history.xlsx"
    BALANCE_CSV = "/home/user/sports-card-agent/data/psa_vault_balance_history.csv"
    GOLDIN_BAL_CSV = "/home/user/sports-card-agent/data/goldin_balance_transactions.csv"
    FANATICS_CSV = "/home/user/sports-card-agent/data/fanatics_collect_sales.csv"
    WHEELHOUSE_XLSX = "/home/user/sports-card-agent/data/wheelhouse_sales.xlsx"

    print("Parsing eBay purchases...")
    ebay = parse_ebay_purchases(PURCHASE_HTML)
    print(f"  {len(ebay)} purchases, ${sum(p['total'] for p in ebay):,.2f}")

    print("Parsing Goldin history...")
    goldin = parse_goldin(GOLDIN_XLSX)
    print(f"  {len(goldin['sold'])} sold (purchased), ${sum(g['price'] for g in goldin['sold']):,.2f}")
    print(f"  {len(goldin['pending_auth'])} pending auth, {len(goldin['pending_placement'])} pending placement")
    print(f"  {len(goldin['live'])} live, {len(goldin['upcoming'])} upcoming")

    print("Parsing PSA Vault inventory...")
    vault = parse_vault(VAULT_CSV)
    vault_sold = [v for v in vault if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    vault_held = [v for v in vault if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    print(f"  {len(vault)} total, {len(vault_sold)} sold, {len(vault_held)} held")

    print("Parsing PSA Vault balance history (bank deposits)...")
    import csv as csv2
    vault_payments = []
    vault_payouts_total = 0
    from collections import defaultdict as dd
    monthly_vault = dd(lambda: {"gross": 0, "count": 0})
    with open(BALANCE_CSV) as f:
        reader = csv2.DictReader(f)
        for row in reader:
            if row["Type"] == "payment":
                amt = float(row["Amount"])
                vault_payments.append({"amount": amt, "date": row["Created (UTC)"]})
                monthly_vault[row["Created (UTC)"][:7]]["gross"] += amt
                monthly_vault[row["Created (UTC)"][:7]]["count"] += 1
            elif row["Type"] == "payout":
                vault_payouts_total += abs(float(row["Amount"]))
    total_vault_bank = sum(p["amount"] for p in vault_payments)
    print(f"  {len(vault_payments)} sale payments, ${total_vault_bank:,.2f} deposited to bank")

    print("Parsing Goldin balance transactions (consignment sales)...")
    goldin_bal = parse_goldin_balance(GOLDIN_BAL_CSV)
    print(f"  {len(goldin_bal['deposits'])} sales, ${goldin_bal['total_proceeds']:,.2f} gross proceeds")
    print(f"  ${goldin_bal['total_payouts']:,.2f} paid out to bank")
    print(f"  ${abs(goldin_bal['total_adjustments']):,.2f} in fees/adjustments")

    print("Parsing Fanatics Collect sales...")
    fc = parse_fanatics_collect(FANATICS_CSV)
    print(f"  {len(fc['items'])} sales, ${fc['total_sale']:,.2f} gross, ${fc['total_net']:,.2f} net")

    print("Parsing Wheelhouse auction sales...")
    wh = parse_wheelhouse(WHEELHOUSE_XLSX)
    print(f"  {len(wh['items'])} lots, ${wh['total_hammer']:,.2f} hammer, ${wh['total_net']:,.2f} net proceeds")

    print("Parsing returns...")
    returns = parse_returns(RETURNS_HTML)
    print(f"  {len(returns)} returns")

    print("\nBuilding complete P&L...")
    out = build_pnl(ebay, goldin, vault, returns,
                    vault_bank_total=total_vault_bank, vault_bank_txns=len(vault_payments),
                    goldin_balance=goldin_bal, fanatics=fc, wheelhouse=wh)

    total_ebay = sum(p["total"] for p in ebay)
    total_goldin = sum(g["price"] for g in goldin["sold"])
    held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    held_est = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)
    pipeline = len(goldin["pending_auth"]) + len(goldin["pending_placement"]) + len(goldin["live"]) + len(goldin["upcoming"])
    total_all_revenue = total_vault_bank + goldin_bal["total_proceeds"] + wh["total_net"]

    print(f"\n{'='*70}")
    print(f"  COMPLETE P&L ACROSS ALL PLATFORMS")
    print(f"{'='*70}")
    print(f"")
    print(f"  CAPITAL IN (PURCHASES)")
    print(f"    eBay Purchases:       {len(ebay):>5,} cards   ${total_ebay:>12,.2f}")
    print(f"    Goldin Purchases:     {len(goldin['sold']):>5,} cards   ${total_goldin:>12,.2f}")
    print(f"    ─────────────────────────────────────────────────")
    print(f"    TOTAL DEPLOYED:       {len(ebay)+len(goldin['sold']):>5,} cards   ${total_ebay+total_goldin:>12,.2f}")
    print(f"")
    print(f"  CAPITAL OUT (ALL PLATFORMS)")
    print(f"    Fanatics/PSA Vault:   {len(vault_payments):>5,} txns    ${total_vault_bank:>12,.2f}")
    print(f"      (detail: {len(fc['items'])} Buy Now items, ${fc['total_sale']:,.0f} gross / ${fc['total_net']:,.0f} net)")
    print(f"    Goldin Consignment:   {len(goldin_bal['deposits']):>5,} sales   ${goldin_bal['total_proceeds']:>12,.2f}")
    print(f"    Goldin Fees:                          ${-abs(goldin_bal['total_adjustments']):>12,.2f}")
    print(f"    Wheelhouse Auctions:  {len(wh['items']):>5,} lots    ${wh['total_net']:>12,.2f}")
    print(f"    ─────────────────────────────────────────────────")
    print(f"    TOTAL REVENUE:                        ${total_all_revenue:>12,.2f}")
    print(f"")
    print(f"  CASH FLOW")
    cash = total_all_revenue - total_ebay - total_goldin
    print(f"    Total Out - Total In:                 ${cash:>12,.2f}")
    print(f"")
    print(f"  CURRENT ASSETS")
    print(f"    Vault Inventory:      {len(vault_held):>5,} cards")
    print(f"      Cost Basis:                         ${held_cost:>12,.2f}")
    print(f"      PSA Estimate:                       ${held_est:>12,.2f}")
    print(f"    Goldin Pipeline:      {pipeline:>5,} cards   (pending/live/upcoming)")
    ebay_listed = [v for v in vault if v['listing_status'] == 'Fixed Price' and v['sold_price'] == 0]
    print(f"    eBay Listed:          {len(ebay_listed):>5,} cards   ${sum(v['listing_price'] for v in ebay_listed):>12,.2f}")
    print(f"")
    print(f"  MONTHLY FANATICS/PSA VAULT SALES")
    for m in sorted(monthly_vault.keys()):
        d = monthly_vault[m]
        print(f"    {m}:  {d['count']:>3} sales   ${d['gross']:>10,.2f}")
    print(f"    ─────────────────────────────────")
    print(f"    TOTAL:   {len(vault_payments):>3} sales   ${total_vault_bank:>10,.2f}")
    print(f"")

    monthly_goldin = defaultdict(lambda: {"gross": 0, "count": 0})
    for d in goldin_bal["deposits"]:
        monthly_goldin[d["month"]]["gross"] += d["amount"]
        monthly_goldin[d["month"]]["count"] += 1
    print(f"  MONTHLY GOLDIN CONSIGNMENT SALES")
    for m in sorted(monthly_goldin.keys()):
        d = monthly_goldin[m]
        print(f"    {m}:  {d['count']:>3} sales   ${d['gross']:>10,.2f}")
    print(f"    ─────────────────────────────────")
    print(f"    TOTAL:   {len(goldin_bal['deposits']):>3} sales   ${goldin_bal['total_proceeds']:>10,.2f}")
    print(f"")

    monthly_wh = defaultdict(lambda: {"net": 0, "count": 0})
    for item in wh["items"]:
        m = item["date"][:7] if item["date"] and len(item["date"]) >= 7 else "Unknown"
        monthly_wh[m]["net"] += item["net"]
        monthly_wh[m]["count"] += 1
    print(f"  MONTHLY WHEELHOUSE AUCTION SALES")
    for m in sorted(monthly_wh.keys()):
        d = monthly_wh[m]
        print(f"    {m}:  {d['count']:>3} lots    ${d['net']:>10,.2f}")
    print(f"    ─────────────────────────────────")
    print(f"    TOTAL:   {len(wh['items']):>3} lots    ${wh['total_net']:>10,.2f}")

    print(f"{'='*70}")
    print(f"\nSaved to: {out}")
