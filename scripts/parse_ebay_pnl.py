"""Parse eBay HTML reports and generate a P&L Excel workbook."""

from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter
from datetime import datetime
import re
import os

BASE = "/home/user/sports-card-agent/data/ebay_reports/ebayReports/reports/transactionreports"
OUT = "/home/user/sports-card-agent/Inventory/eBay_PnL.xlsx"


def parse_cells_in_chunks(soup, chunk_size):
    """Parse all td.bottomBorder cells in fixed-size chunks (no reliance on <tr>)."""
    all_cells = soup.find_all("td", class_=re.compile(r"bottomBorder"))
    texts = [c.get_text(strip=True) for c in all_cells]
    chunks = []
    for i in range(0, len(texts), chunk_size):
        chunk = texts[i:i + chunk_size]
        if len(chunk) == chunk_size:
            chunks.append(chunk)
    return chunks


def parse_float(s):
    try:
        return float(s.replace(",", "")) if s else 0
    except ValueError:
        return 0


def parse_int(s):
    try:
        return int(s) if s else 1
    except ValueError:
        return 1


def parse_date(s):
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y %I:%M%p", "%b %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_purchase_history(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    chunks = parse_cells_in_chunks(soup, 9)
    purchases = []
    for cells in chunks:
        date_str, item_id, title, price_str, qty_str, shipping_str, total_str, currency, seller = cells

        price = parse_float(price_str)
        shipping = parse_float(shipping_str)
        total = parse_float(total_str)
        qty = parse_int(qty_str)
        date = parse_date(date_str)

        if title and (price > 0 or total > 0):
            purchases.append({
                "date": date,
                "item_id": item_id,
                "title": title,
                "price": price,
                "qty": qty,
                "shipping": shipping,
                "total": total if total > 0 else price + shipping,
                "currency": currency,
                "seller": seller,
            })
    return purchases


def parse_selling_history(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    chunks = parse_cells_in_chunks(soup, 8)
    sales = []
    for cells in chunks:
        date_str, item_id, title, price_str, qty_str, shipping_str, currency, buyer = cells
        price = parse_float(price_str)
        shipping = parse_float(shipping_str)
        qty = parse_int(qty_str)
        date = parse_date(date_str)

        if title and price > 0:
            sales.append({
                "date": date,
                "item_id": item_id,
                "title": title,
                "price": price,
                "qty": qty,
                "shipping": shipping,
                "total": price + shipping,
                "currency": currency,
                "buyer": buyer,
            })
    return sales


def parse_vault_data(path):
    """Parse PSA Vault CSV for all items with cost/sale data.
    Columns: 0=Item Status, 1=Item, 2=Cert Number, 3=Grade, 4=Issuer Grade,
    5=Autograph Grade, 6=Year, 7=Set, 8=Card Number, 9=Subject, 10=Variety,
    11=Serial, 12=My Cost, 13=PSA Estimate, 14=Gain/Loss, 15=My Value,
    16=Date Acquired, 17=Source, 18=My Notes, 19=Vault Status,
    20=Vaulted Date, 21=Days Vaulted, 22=Listing Status, 23=Listing Date,
    24=Listing Price, 25=Sold Status, 26=Sold On, 27=Sold Date,
    28=Sold Price, 29=Sold Fees, 30=Sold Proceeds, 31=Payment Date
    """
    import csv
    items = []
    header_skipped = False
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
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

            item = {
                "status": val(0),
                "item": val(1),
                "cert": val(2),
                "grader": "",
                "grade": val(3),
                "issuer_grade": val(4),
                "auto_grade": val(5),
                "year": val(6),
                "set": val(7),
                "card_number": val(8),
                "subject": val(9),
                "variety": val(10),
                "serial": val(11),
                "my_cost": parse_float(val(12)),
                "psa_estimate": parse_float(val(13)),
                "gain_loss": parse_float(val(14)),
                "my_value": parse_float(val(15)),
                "date_acquired": val(16),
                "source": val(17),
                "vault_status": val(19),
                "days_vaulted": parse_int(val(21)) if val(21) else 0,
                "listing_status": val(22),
                "listing_price": parse_float(val(24)),
                "sold_status": val(25),
                "sold_on": val(26),
                "sold_date": val(27),
                "sold_price": parse_float(val(28)),
                "sold_fees": parse_float(val(29)),
                "sold_proceeds": parse_float(val(30)),
            }

            cert = item["cert"]
            if cert.startswith("VIH"):
                item["grader"] = "VIH"
            elif cert.startswith("00"):
                item["grader"] = "BGS"
            elif "E+" in cert or "E+0" in cert:
                item["grader"] = "PSA"
            else:
                try:
                    int(cert)
                    item["grader"] = "PSA"
                except ValueError:
                    item["grader"] = "SGC" if cert else "Unknown"

            if item["item"]:
                items.append(item)
    return items


def parse_returns(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    rows = soup.find_all("tr")
    returns = []
    for row in rows:
        cells = row.find_all("td", class_="td")
        if len(cells) >= 6:
            buyer = cells[0].get_text(strip=True)
            seller = cells[1].get_text(strip=True)
            title = cells[2].get_text(strip=True)
            status = cells[3].get_text(strip=True)
            reason = cells[4].get_text(strip=True)
            closure = cells[5].get_text(strip=True)

            refund_type = ""
            refund_amount = 0
            refund_currency = "USD"
            if len(cells) > 6:
                refund_type = cells[6].get_text(strip=True)
            if len(cells) > 7:
                try:
                    refund_amount = float(cells[7].get_text(strip=True).replace(",", ""))
                except ValueError:
                    refund_amount = 0
            if len(cells) > 8:
                refund_currency = cells[8].get_text(strip=True)

            if title:
                returns.append({
                    "buyer": buyer,
                    "seller": seller,
                    "title": title,
                    "status": status,
                    "reason": reason,
                    "closure": closure,
                    "refund_type": refund_type,
                    "refund_amount": refund_amount,
                    "currency": refund_currency,
                })
    return returns


def make_header(ws, headers, fill_color="1F4E79"):
    header_font = Font(bold=True, color="FFFFFF", size=11)
    fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = header_font
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")


def build_workbook(purchases, sales, returns, vault_items=None):
    vault_items = vault_items or []
    wb = Workbook()

    money_fmt = '#,##0.00'
    date_fmt = 'MM/DD/YYYY'
    pct_fmt = '0.0%'
    thin_border = Border(bottom=Side(style="thin", color="CCCCCC"))
    green_font = Font(color="006100")
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_font = Font(color="9C0006")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

    # ── Separate vault items ──
    vault_sold = [v for v in vault_items if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    vault_with_cost = [v for v in vault_items if v["my_cost"] > 0]
    vault_held = [v for v in vault_items if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    vault_listed = [v for v in vault_items if v["listing_status"] == "Fixed Price" and v["sold_price"] == 0]

    # ── Compute totals ──
    total_ebay_bought = sum(p["total"] for p in purchases)
    total_ebay_card_price = sum(p["price"] for p in purchases)
    total_ebay_shipping = sum(p["shipping"] for p in purchases)
    num_ebay_purchases = len(purchases)

    total_vault_cost = sum(v["my_cost"] for v in vault_with_cost)
    total_vault_sold_price = sum(v["sold_price"] for v in vault_sold)
    total_vault_sold_proceeds = sum(v["sold_proceeds"] for v in vault_sold)
    total_vault_fees = sum(v["sold_fees"] for v in vault_sold)
    num_vault_sold = len(vault_sold)

    total_ebay_sold = sum(s["price"] for s in sales)
    num_ebay_sold = len(sales)

    total_refunds = sum(r["refund_amount"] for r in returns)
    num_returns = len(returns)

    total_held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    total_held_estimate = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)
    total_listed_price = sum(v["listing_price"] for v in vault_listed)
    num_held = len(vault_held)
    num_listed = len(vault_listed)

    # ── P&L Summary Sheet ──
    ws_sum = wb.active
    ws_sum.title = "P&L Summary"
    ws_sum.sheet_properties.tabColor = "1F4E79"

    summary_data = [
        ("COMPLETE P&L SUMMARY", "", True),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M"), False),
        ("", "", False),
        ("EBAY PURCHASES", "", True),
        ("Total eBay Purchases", num_ebay_purchases, False),
        ("Total Card Cost (eBay)", total_ebay_card_price, False),
        ("Total Shipping Paid", total_ebay_shipping, False),
        ("Total Spent on eBay", total_ebay_bought, False),
        ("Average Purchase Price", total_ebay_card_price / max(num_ebay_purchases, 1), False),
        ("", "", False),
        ("VAULT COST BASIS", "", True),
        ("Cards with Cost Recorded", len(vault_with_cost), False),
        ("Total Cost Basis (Vault)", total_vault_cost, False),
        ("", "", False),
        ("SALES (VIA PSA VAULT / EBAY)", "", True),
        ("Vault Items Sold", num_vault_sold, False),
        ("Total Sold Price (Vault)", total_vault_sold_price, False),
        ("Total Fees Paid (Vault)", total_vault_fees, False),
        ("Total Net Proceeds (Vault)", total_vault_sold_proceeds, False),
        ("eBay Direct Sales", num_ebay_sold, False),
        ("eBay Direct Revenue", total_ebay_sold, False),
        ("", "", False),
        ("RETURNS & REFUNDS", "", True),
        ("Total Returns", num_returns, False),
        ("Total Refunded", total_refunds, False),
        ("", "", False),
        ("P&L CALCULATION", "", True),
        ("Total Revenue (All Sales)", total_vault_sold_price + total_ebay_sold, False),
        ("Total Fees", total_vault_fees, False),
        ("Total Net Proceeds", total_vault_sold_proceeds + total_ebay_sold, False),
        ("Total Cost Basis", total_vault_cost, False),
        ("Gross P&L (Proceeds - Cost of Sold)", 0, False),
        ("Net P&L (After Fees & Refunds)", 0, False),
        ("", "", False),
        ("CURRENT INVENTORY", "", True),
        ("Cards in Vault (unsold)", num_held, False),
        ("Cost Basis of Held Cards", total_held_cost, False),
        ("PSA Estimate of Held Cards", total_held_estimate, False),
        ("Unrealized Gain (Est - Cost)", total_held_estimate - total_held_cost, False),
        ("Cards Currently Listed", num_listed, False),
        ("Total Listing Price", total_listed_price, False),
        ("Total Vault Items", len(vault_items), False),
    ]

    sold_costs = sum(v["my_cost"] for v in vault_sold if v["my_cost"] > 0)
    gross_pnl = total_vault_sold_proceeds + total_ebay_sold - sold_costs
    net_pnl = gross_pnl - total_refunds

    for i, (label, value, is_header) in enumerate(summary_data, 1):
        ws_sum.cell(row=i, column=1, value=label)
        cell = ws_sum.cell(row=i, column=2)

        if label == "Gross P&L (Proceeds - Cost of Sold)":
            value = gross_pnl
        elif label == "Net P&L (After Fees & Refunds)":
            value = net_pnl

        cell.value = value

        if isinstance(value, float) and value != 0:
            cell.number_format = money_fmt
        if is_header:
            ws_sum.cell(row=i, column=1).font = Font(bold=True, size=13, color="1F4E79")
        if "P&L" in label and "CALCULATION" not in label and isinstance(value, (int, float)) and value != 0:
            ws_sum.cell(row=i, column=1).font = Font(bold=True, size=12)
            cell.font = Font(bold=True, size=12, color="006100" if value >= 0 else "9C0006")
            cell.fill = green_fill if value >= 0 else red_fill
            cell.number_format = money_fmt
        if "Unrealized" in label and isinstance(value, (int, float)):
            cell.font = Font(color="006100" if value >= 0 else "9C0006")
            cell.number_format = money_fmt

    ws_sum.column_dimensions["A"].width = 40
    ws_sum.column_dimensions["B"].width = 20

    # ── eBay Purchases Sheet ──
    ws_buy = wb.create_sheet("eBay Purchases")
    ws_buy.sheet_properties.tabColor = "4472C4"
    make_header(ws_buy, ["Date", "eBay Item ID", "Title", "Price", "Qty", "Shipping", "Total Cost", "Currency", "Seller"])

    purchases_sorted = sorted(purchases, key=lambda x: x["date"] or datetime.min, reverse=True)
    for r, p in enumerate(purchases_sorted, 2):
        ws_buy.cell(row=r, column=1, value=p["date"]).number_format = date_fmt
        ws_buy.cell(row=r, column=2, value=p["item_id"])
        ws_buy.cell(row=r, column=3, value=p["title"])
        ws_buy.cell(row=r, column=4, value=p["price"]).number_format = money_fmt
        ws_buy.cell(row=r, column=5, value=p["qty"])
        ws_buy.cell(row=r, column=6, value=p["shipping"]).number_format = money_fmt
        ws_buy.cell(row=r, column=7, value=p["total"]).number_format = money_fmt
        ws_buy.cell(row=r, column=8, value=p["currency"])
        ws_buy.cell(row=r, column=9, value=p["seller"])
        for c in range(1, 10):
            ws_buy.cell(row=r, column=c).border = thin_border

    for col, w in zip("ABCDEFGHI", [20, 16, 70, 14, 6, 12, 14, 10, 18]):
        ws_buy.column_dimensions[col].width = w
    ws_buy.freeze_panes = "A2"
    ws_buy.auto_filter.ref = f"A1:I{len(purchases_sorted)+1}"

    # ── Vault Sold Items Sheet ──
    ws_vsold = wb.create_sheet("Vault Sales")
    ws_vsold.sheet_properties.tabColor = "70AD47"
    make_header(ws_vsold, [
        "Item", "Cert", "Grader", "Grade", "My Cost", "Sold Price",
        "Fees", "Net Proceeds", "P&L", "P&L %", "Sold On", "Channel"
    ], "375623")

    vault_sold_sorted = sorted(vault_sold, key=lambda x: x["sold_proceeds"], reverse=True)
    for r, v in enumerate(vault_sold_sorted, 2):
        pnl = v["sold_proceeds"] - v["my_cost"] if v["my_cost"] > 0 else 0
        pnl_pct = pnl / v["my_cost"] if v["my_cost"] > 0 else 0

        ws_vsold.cell(row=r, column=1, value=v["item"])
        ws_vsold.cell(row=r, column=2, value=v["cert"])
        ws_vsold.cell(row=r, column=3, value=v["grader"])
        ws_vsold.cell(row=r, column=4, value=v["grade"])
        ws_vsold.cell(row=r, column=5, value=v["my_cost"]).number_format = money_fmt
        ws_vsold.cell(row=r, column=6, value=v["sold_price"]).number_format = money_fmt
        ws_vsold.cell(row=r, column=7, value=v["sold_fees"]).number_format = money_fmt
        ws_vsold.cell(row=r, column=8, value=v["sold_proceeds"]).number_format = money_fmt

        pnl_cell = ws_vsold.cell(row=r, column=9, value=pnl)
        pnl_cell.number_format = money_fmt
        if v["my_cost"] > 0:
            pnl_cell.font = green_font if pnl >= 0 else red_font
            pnl_cell.fill = green_fill if pnl >= 0 else red_fill

        pct_cell = ws_vsold.cell(row=r, column=10, value=pnl_pct)
        pct_cell.number_format = pct_fmt
        if v["my_cost"] > 0:
            pct_cell.font = green_font if pnl_pct >= 0 else red_font

        ws_vsold.cell(row=r, column=11, value=v["sold_on"])
        ws_vsold.cell(row=r, column=12, value=v.get("channel", ""))

        for c in range(1, 13):
            ws_vsold.cell(row=r, column=c).border = thin_border

    for col, w in zip("ABCDEFGHIJKL", [60, 14, 8, 8, 12, 12, 10, 12, 12, 10, 14, 10]):
        ws_vsold.column_dimensions[col].width = w
    ws_vsold.freeze_panes = "A2"
    ws_vsold.auto_filter.ref = f"A1:L{len(vault_sold_sorted)+1}"

    # ── Current Inventory Sheet ──
    ws_inv = wb.create_sheet("Current Inventory")
    ws_inv.sheet_properties.tabColor = "FFC000"
    make_header(ws_inv, [
        "Item", "Cert", "Grader", "Grade", "My Cost", "PSA Estimate",
        "Unrealized G/L", "Listing Status", "Listing Price", "Days Vaulted"
    ], "BF8F00")

    vault_held_sorted = sorted(vault_held, key=lambda x: x["my_cost"], reverse=True)
    for r, v in enumerate(vault_held_sorted, 2):
        unreal = v["psa_estimate"] - v["my_cost"] if v["my_cost"] > 0 and v["psa_estimate"] > 0 else 0

        ws_inv.cell(row=r, column=1, value=v["item"])
        ws_inv.cell(row=r, column=2, value=v["cert"])
        ws_inv.cell(row=r, column=3, value=v["grader"])
        ws_inv.cell(row=r, column=4, value=v["grade"])
        ws_inv.cell(row=r, column=5, value=v["my_cost"]).number_format = money_fmt
        ws_inv.cell(row=r, column=6, value=v["psa_estimate"]).number_format = money_fmt

        gl_cell = ws_inv.cell(row=r, column=7, value=unreal)
        gl_cell.number_format = money_fmt
        if v["my_cost"] > 0 and v["psa_estimate"] > 0:
            gl_cell.font = green_font if unreal >= 0 else red_font

        ws_inv.cell(row=r, column=8, value=v["listing_status"])
        ws_inv.cell(row=r, column=9, value=v["listing_price"]).number_format = money_fmt
        ws_inv.cell(row=r, column=10, value=v["days_vaulted"])

        for c in range(1, 11):
            ws_inv.cell(row=r, column=c).border = thin_border

    for col, w in zip("ABCDEFGHIJ", [60, 14, 8, 8, 12, 12, 12, 14, 12, 10]):
        ws_inv.column_dimensions[col].width = w
    ws_inv.freeze_panes = "A2"
    ws_inv.auto_filter.ref = f"A1:J{len(vault_held_sorted)+1}"

    # ── Returns Sheet ──
    ws_ret = wb.create_sheet("Returns & Refunds")
    ws_ret.sheet_properties.tabColor = "C00000"
    make_header(ws_ret, ["Buyer", "Seller", "Title", "Status", "Reason", "Closure", "Refund Type", "Refund Amount", "Currency"], "C00000")

    for r, ret in enumerate(returns, 2):
        ws_ret.cell(row=r, column=1, value=ret["buyer"])
        ws_ret.cell(row=r, column=2, value=ret["seller"])
        ws_ret.cell(row=r, column=3, value=ret["title"])
        ws_ret.cell(row=r, column=4, value=ret["status"])
        ws_ret.cell(row=r, column=5, value=ret["reason"])
        ws_ret.cell(row=r, column=6, value=ret["closure"])
        ws_ret.cell(row=r, column=7, value=ret["refund_type"])
        ws_ret.cell(row=r, column=8, value=ret["refund_amount"]).number_format = money_fmt
        ws_ret.cell(row=r, column=9, value=ret["currency"])
        for c in range(1, 10):
            ws_ret.cell(row=r, column=c).border = thin_border

    for col, w in zip("ABCDEFGHI", [18, 18, 70, 14, 25, 20, 18, 14, 10]):
        ws_ret.column_dimensions[col].width = w
    ws_ret.freeze_panes = "A2"
    ws_ret.auto_filter.ref = f"A1:I{len(returns)+1}"

    # ── Monthly P&L Sheet ──
    ws_monthly = wb.create_sheet("Monthly P&L")
    ws_monthly.sheet_properties.tabColor = "ED7D31"
    make_header(ws_monthly, ["Month", "eBay Purchases", "Vault Sales (Proceeds)", "Gross P&L", "Cumulative P&L"], "C55A11")

    monthly_buys = {}
    for p in purchases:
        if p["date"]:
            key = p["date"].strftime("%Y-%m")
            monthly_buys[key] = monthly_buys.get(key, 0) + p["total"]

    monthly_vault_sales = {}
    for v in vault_sold:
        sd = v.get("sold_date", "")
        if sd and len(sd) >= 7:
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
                try:
                    dt = datetime.strptime(sd, fmt)
                    key = dt.strftime("%Y-%m")
                    monthly_vault_sales[key] = monthly_vault_sales.get(key, 0) + v["sold_proceeds"]
                    break
                except ValueError:
                    continue

    all_months = sorted(set(list(monthly_buys.keys()) + list(monthly_vault_sales.keys())))

    cumulative = 0
    for r, month in enumerate(all_months, 2):
        bought = monthly_buys.get(month, 0)
        sold = monthly_vault_sales.get(month, 0)
        gross = sold - bought
        cumulative += gross

        ws_monthly.cell(row=r, column=1, value=month)
        ws_monthly.cell(row=r, column=2, value=bought).number_format = money_fmt
        ws_monthly.cell(row=r, column=3, value=sold).number_format = money_fmt

        gross_cell = ws_monthly.cell(row=r, column=4, value=gross)
        gross_cell.number_format = money_fmt
        gross_cell.font = green_font if gross >= 0 else red_font
        gross_cell.fill = green_fill if gross >= 0 else red_fill

        cum_cell = ws_monthly.cell(row=r, column=5, value=cumulative)
        cum_cell.number_format = money_fmt
        cum_cell.font = Font(bold=True, color="006100" if cumulative >= 0 else "9C0006")

        for c in range(1, 6):
            ws_monthly.cell(row=r, column=c).border = thin_border

    for c in range(1, 6):
        ws_monthly.column_dimensions[get_column_letter(c)].width = 20
    ws_monthly.freeze_panes = "A2"

    # ── Top 50 Purchases Sheet ──
    ws_top = wb.create_sheet("Top 50 Purchases")
    ws_top.sheet_properties.tabColor = "7030A0"
    make_header(ws_top, ["Rank", "Date", "Title", "Total Cost", "Seller"], "7030A0")

    top_purchases = sorted(purchases, key=lambda x: x["total"], reverse=True)[:50]
    for r, p in enumerate(top_purchases, 2):
        ws_top.cell(row=r, column=1, value=r - 1)
        ws_top.cell(row=r, column=2, value=p["date"]).number_format = date_fmt
        ws_top.cell(row=r, column=3, value=p["title"])
        ws_top.cell(row=r, column=4, value=p["total"]).number_format = money_fmt
        ws_top.cell(row=r, column=5, value=p["seller"])

    for col, w in zip("ABCDE", [6, 20, 70, 14, 18]):
        ws_top.column_dimensions[col].width = w
    ws_top.freeze_panes = "A2"

    # ── Top Sales Sheet ──
    ws_topsales = wb.create_sheet("Top 50 Sales")
    ws_topsales.sheet_properties.tabColor = "00B050"
    make_header(ws_topsales, ["Rank", "Item", "Sold Price", "Fees", "Net Proceeds", "My Cost", "P&L"], "00B050")

    top_sales = sorted(vault_sold, key=lambda x: x["sold_price"], reverse=True)[:50]
    for r, v in enumerate(top_sales, 2):
        pnl = v["sold_proceeds"] - v["my_cost"] if v["my_cost"] > 0 else 0
        ws_topsales.cell(row=r, column=1, value=r - 1)
        ws_topsales.cell(row=r, column=2, value=v["item"])
        ws_topsales.cell(row=r, column=3, value=v["sold_price"]).number_format = money_fmt
        ws_topsales.cell(row=r, column=4, value=v["sold_fees"]).number_format = money_fmt
        ws_topsales.cell(row=r, column=5, value=v["sold_proceeds"]).number_format = money_fmt
        ws_topsales.cell(row=r, column=6, value=v["my_cost"]).number_format = money_fmt
        pnl_cell = ws_topsales.cell(row=r, column=7, value=pnl)
        pnl_cell.number_format = money_fmt
        if v["my_cost"] > 0:
            pnl_cell.font = green_font if pnl >= 0 else red_font
            pnl_cell.fill = green_fill if pnl >= 0 else red_fill

    for col, w in zip("ABCDEFG", [6, 60, 14, 12, 14, 12, 14]):
        ws_topsales.column_dimensions[col].width = w
    ws_topsales.freeze_panes = "A2"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    wb.save(OUT)
    return wb


VAULT_CSV = "/home/user/sports-card-agent/data/psa_vault_raw.csv"

if __name__ == "__main__":
    print("Parsing eBay purchase history...")
    purchases = parse_purchase_history(f"{BASE}/purchaseHistory.html")
    print(f"  Found {len(purchases)} eBay purchases")

    print("Parsing eBay selling history...")
    sales = parse_selling_history(f"{BASE}/sellingHistory.html")
    print(f"  Found {len(sales)} eBay direct sales")

    print("Parsing returns & refunds...")
    returns = parse_returns(f"{BASE}/returnsAndRefunds.html")
    print(f"  Found {len(returns)} returns/disputes")

    print("Parsing PSA Vault data...")
    vault_items = parse_vault_data(VAULT_CSV)
    vault_sold = [v for v in vault_items if v["sold_price"] > 0 or v["sold_proceeds"] > 0]
    vault_with_cost = [v for v in vault_items if v["my_cost"] > 0]
    print(f"  Found {len(vault_items)} total vault items")
    print(f"  {len(vault_sold)} sold items")
    print(f"  {len(vault_with_cost)} items with cost recorded")

    print("\nBuilding P&L workbook...")
    build_workbook(purchases, sales, returns, vault_items)

    total_spent = sum(p["total"] for p in purchases)
    total_vault_cost = sum(v["my_cost"] for v in vault_with_cost)
    total_vault_proceeds = sum(v["sold_proceeds"] for v in vault_sold)
    total_vault_sold_price = sum(v["sold_price"] for v in vault_sold)
    total_vault_fees = sum(v["sold_fees"] for v in vault_sold)
    sold_cost_basis = sum(v["my_cost"] for v in vault_sold if v["my_cost"] > 0)
    total_refunds = sum(r["refund_amount"] for r in returns)

    print(f"\n{'='*60}")
    print(f"  EBAY PURCHASES")
    print(f"    Total eBay Purchases:     {len(purchases):,} cards")
    print(f"    Total Spent on eBay:      ${total_spent:>12,.2f}")
    print(f"")
    print(f"  PSA VAULT SALES")
    print(f"    Items Sold:               {len(vault_sold):,}")
    print(f"    Gross Sale Price:         ${total_vault_sold_price:>12,.2f}")
    print(f"    Fees Paid:                ${total_vault_fees:>12,.2f}")
    print(f"    Net Proceeds:             ${total_vault_proceeds:>12,.2f}")
    print(f"    Cost Basis (sold items):  ${sold_cost_basis:>12,.2f}")
    print(f"")
    print(f"  RETURNS")
    print(f"    Total Refunded:           ${total_refunds:>12,.2f}")
    print(f"")
    print(f"  P&L")
    gross_pnl = total_vault_proceeds - sold_cost_basis
    net_pnl = gross_pnl - total_refunds
    print(f"    Gross P&L:                ${gross_pnl:>12,.2f}")
    print(f"    Net P&L (after refunds):  ${net_pnl:>12,.2f}")
    print(f"")
    print(f"  CURRENT HOLDINGS")
    vault_held = [v for v in vault_items if v["vault_status"] == "Vaulted" and v["sold_price"] == 0]
    held_cost = sum(v["my_cost"] for v in vault_held if v["my_cost"] > 0)
    held_est = sum(v["psa_estimate"] for v in vault_held if v["psa_estimate"] > 0)
    print(f"    Cards in Vault:           {len(vault_held):,}")
    print(f"    Cost Basis (held):        ${held_cost:>12,.2f}")
    print(f"    PSA Estimate (held):      ${held_est:>12,.2f}")
    print(f"    Unrealized G/L:           ${held_est - held_cost:>12,.2f}")
    print(f"{'='*60}")
    print(f"\nSaved to: {OUT}")
