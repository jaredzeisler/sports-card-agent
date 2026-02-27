#!/usr/bin/env python3
"""Batch process Goldin auction sale results into the inventory DB."""

import sqlite3
from datetime import datetime

DB = "sports_cards.db"

# Each sale: (lot_no, title, hammer, split_pct, gross, cgc_fee, net, card_id, sale_date)
# gross = hammer * split_pct
# net = gross - cgc_fee  (= JZ Net Proceeds)
# For transaction: price = gross, fees = cgc_fee, platform = "goldin"
# All lots sold 21-Feb-26

SALES = [
    # --- 110% split tier ---
    (2555, "2022 NT Treasured Moments '25 Black Box Stephen Curry AUTO 1/1 #TM-SCY", 2600.00, 1.10, 2860.00, 0, 2860.00, 976, "2026-02-21"),
    (2922, "2024 Prizm Black Prizmatrix Gold Shimmer Luka Doncic AUTO 1/10 #PS-LUK", 1800.00, 1.10, 1980.00, 0, 1980.00, 977, "2026-02-21"),
    (2522, "2021 Flawless Draft Gem Luka Doncic AUTO /25 #DGS-LDD", 1050.00, 1.10, 1155.00, 0, 1155.00, 1204, "2026-02-21"),
    (2461, "2020 NT Horizontal '25 Black Box Tyrese Maxey RPA 1/1 #114", 1050.00, 1.10, 1155.00, 0, 1155.00, 1636, "2026-02-21"),
    (2460, "2020 NT Colossal White Box Tyrese Maxey RPA 1/1 #CM-TMX", 900.00, 1.10, 990.00, 0, 990.00, 1531, "2026-02-21"),
    (2510, "2021 One And One Timeless Moments Purple Nikola Jokic AUTO /35 #TM-NJK", 725.00, 1.10, 797.50, 0, 797.50, 1008, "2026-02-21"),
    (2810, "2024 Silhouette NBA Cup FOTL Red Stephen Curry AUTO 1/7 #CUP-CUR", 725.00, 1.10, 797.50, 0, 797.50, 872, "2026-02-21"),
    (1198, "2024 Topps Transcendent Showcase Blue Paul Skenes AUTO /10 #RSA-PS", 700.00, 1.10, 770.00, 0, 770.00, 874, "2026-02-21"),
    (2424, "2019 One And One 1st Team '25 Black Box Nikola Jokic AUTO 1/1 #FT-NJK", 675.00, 1.10, 742.50, 0, 742.50, 1211, "2026-02-21"),
    (2556, "2022 NT Clutch Factor '25 Black Box Paolo Banchero RPA 1/1", 550.00, 1.10, 605.00, 0, 605.00, 1050, "2026-02-21"),
    (1075, "2023 Topps Dynasty Silver Vladimir Guerrero Jr. PATCH AUTO /5 #DAPB-VGJ1", 460.00, 1.10, 506.00, 0, 506.00, 901, "2026-02-21"),
    (2515, "2021 Eminence Jumbo Gold Ja Morant PATCH AUTO 1/5 #JPA-JAM", 400.00, 1.10, 440.00, 0, 440.00, 1332, "2026-02-21"),
    (2860, "2024 Flawless All-NBA Diamond Gems Luka Doncic /10 #182", 360.00, 1.10, 396.00, 0, 396.00, 1468, "2026-02-21"),
    (2544, "2021 Select Black Snakeskin Pulsar Bones Hyland RPA 1/1 #RJ-BHY CGC AUTH", 310.00, 1.10, 341.00, 3, 338.00, 1334, "2026-02-21"),
    (1548, "2025 Topps All Kings Vladimir Guerrero Jr. #AK-10 CGC AUTH", 280.00, 1.10, 308.00, 3, 305.00, 1293, "2026-02-21"),
    (2540, "2021 Immaculate Massive Memorabilia Cade Cunningham PATCH 25/25 CGC AUTH", 280.00, 1.10, 308.00, 3, 305.00, 2099, "2026-02-21"),
    (2559, "2022 One And One Purple Paolo Banchero RPA 35/35 #RJA-PB5", 260.00, 1.10, 286.00, 0, 286.00, 622, "2026-02-21"),
    (3112, "2024 Origins Origin Stories Green Stephen Curry /5 #4 CGC AUTH", 230.00, 1.10, 253.00, 3, 250.00, 2096, "2026-02-21"),
    (2463, "2020 Spectra Astral Prizm Tyrese Maxey RPA 35/35 #204", 230.00, 1.10, 253.00, 0, 253.00, 1312, "2026-02-21"),
    (2509, "2021 One And One Red Alperen Sengun RPA 25/25 #RJ-ASG", 210.00, 1.10, 231.00, 0, 231.00, 623, "2026-02-21"),

    # --- 107.5% split tier ---
    (2513, "2025 National VIP Wave Nikola Jokic AUTO /10 #20 CGC AUTH", 190.00, 1.075, 204.25, 3, 201.25, 2158, "2026-02-21"),
    (5136, "2025 National VIP Gold Giannis Antetokounmpo /10 #22 CGC AUTH", 180.00, 1.075, 193.50, 3, 190.50, 2124, "2026-02-21"),
    (1179, "2024 Flawless Prime Sapphire Bobby Witt Jr. PATCH AUTO /15 #PPH-BWJ", 175.00, 1.075, 188.13, 0, 188.13, 1438, "2026-02-21"),
    (3090, "2024 Mosaic Elevate White Fluorescent Victor Wembanyama /10 #11 CGC AUTH", 170.00, 1.075, 182.75, 3, 179.75, 1473, "2026-02-21"),
    (2809, "2024 National VIP Diamond Gems Charles Barkley 1/1 #CB", 165.00, 1.075, 177.38, 0, 177.38, 2156, "2026-02-21"),
    (2421, "2019 Crown Royale Silhouettes Tyler Herro RPA 1/1 #132", 160.00, 1.075, 172.00, 0, 172.00, 1676, "2026-02-21"),
    (3101, "2024 NT Orange Ajay Mitchell RPA /75 #148 CGC AUTH", 160.00, 1.075, 172.00, 3, 169.00, 1611, "2026-02-21"),
    (2794, "2024 One And One Jumbo Red Jared McCain RPA /25 #RJJ-JAR", 150.00, 1.075, 161.25, 0, 161.25, 1506, "2026-02-21"),
    (3103, "2024 Noir Color Holo Gold Jared McCain RPA /25 #360 CGC AUTH", 135.00, 1.075, 145.13, 3, 142.13, 1951, "2026-02-21"),
    (3176, "2025 Topps '80-81 Silver Pack Gold Tracy McGrady AUTO /50 CGC AUTH", 125.00, 1.075, 134.38, 3, 131.38, 1720, "2026-02-21"),
    (2263, "2012 Panini Signatures Red Yao Ming AUTO /10 #200 CGC AUTH", 105.00, 1.075, 112.89, 3, 109.89, 461, "2026-02-21"),
    (3081, "2024 Immaculate Ink Gold John Stockton AUTO 10/10 #INK-JST CGC AUTH", 100.00, 1.075, 107.50, 3, 104.50, 1928, "2026-02-21"),
    (1332, "2025 Bowman Chrome Mega Box Purple Jesus Made AUTO /199 #BMA-JM", 90.00, 1.075, 96.75, 0, 96.75, 1064, "2026-02-21"),
    (1992, "2025 Topps Tier One Jumbo Ronald Acuna Jr. PATCH AUTO /75 CGC AUTH", 88.00, 1.075, 94.60, 3, 91.60, 1850, "2026-02-21"),
    (3080, "2024 Immaculate Dual Bronny/LeBron James PATCH /99 #IDM-BJJ CGC AUTH", 88.00, 1.075, 94.60, 3, 91.60, 1470, "2026-02-21"),
    (5134, "2025 National VIP Hello Cracked Ice Caitlin Clark /45 #CC CGC AUTH", 82.00, 1.075, 88.15, 3, 85.15, 2218, "2026-02-21"),
    (2796, "2024 One And One Of A Kind Green Damian Lillard AUTO /5 #OK-LIL", 82.00, 1.075, 88.15, 0, 88.15, 1343, "2026-02-21"),
    (2513, "2021 Instant Clear Vision Evan Mobley RPA 10/10 #CV-3", 74.00, 1.075, 79.55, 0, 79.55, 1371, "2026-02-21"),
    (2542, "2021 NT Evan Mobley RPA /99 #RMD-EVM CGC AUTH", 72.00, 1.075, 77.40, 3, 74.40, 1982, "2026-02-21"),
    (2790, "2024 One And One Jared McCain RPA /99 #RJA-JAR", 66.00, 1.075, 70.95, 0, 70.95, 1914, "2026-02-21"),
    (5027, "2024 Immaculate Modern Marks Silver Luis Suarez AUTO /25 CGC AUTH", 66.00, 1.075, 70.95, 3, 67.95, 1340, "2026-02-21"),
    (2858, "2024 Flawless Leaders Diamond Gems Gold Kevin Garnett /5 #169", 62.00, 1.075, 66.65, 0, 66.65, 1476, "2026-02-21"),
    (3066, "2024 Flawless Framework Emerald Isiah Thomas AUTO /5 CGC AUTH", 54.00, 1.075, 58.05, 3, 55.05, 1930, "2026-02-21"),
    (1120, "2022 Immaculate Collegiate Red Chet Holmgren RPA /15 #34 CGC AUTH", 54.00, 1.075, 58.05, 3, 55.05, 1097, "2026-02-21"),
    (5029, "2024 Immaculate Standard Gold Christian Pulisic PATCH 1/10 CGC AUTH", 52.00, 1.075, 55.90, 3, 52.90, 1466, "2026-02-21"),

    # --- 105% split tier ---
    (5039, "2024 Topps Chrome UEFA Gold Refractor Antoine Griezmann AUTO /50 CGC AUTH", 49.00, 1.05, 51.45, 3, 48.45, 545, "2026-02-21"),
    (5033, "2024 Select FIFA Equalizers Pink Lamine Yamal /25 #17 CGC AUTH", 47.00, 1.05, 49.35, 3, 46.35, 1107, "2026-02-21"),
    (4525, "2025 Leaf Vivid Prismatic Black Cameron Boozer AUTO 1/1 CGC AUTH", 46.00, 1.05, 48.30, 3, 45.30, 1264, "2026-02-21"),
    (2595, "2022 Court Kings Heir Apparent Ruby Jalen Williams AUTO /99 CGC AUTH", 45.00, 1.05, 47.25, 3, 44.25, 1798, "2026-02-21"),
    (2570, "2022 Flawless Collegiate Prime Gold Jabari Smith Jr. RPA /10 #PM-JSM", 45.00, 1.05, 47.25, 0, 47.25, 1881, "2026-02-21"),
    (3259, "2025 Topps Sole Ambition Stephen Curry #SA-3 CGC AUTH", 37.00, 1.05, 38.85, 3, 35.85, 1156, "2026-02-21"),
    (3151, "2025 Leaf Metal Independence Day Cameron Boozer RC AUTO 1/1", 34.00, 1.05, 35.70, 0, 35.70, 1249, "2026-02-21"),
    (3261, "2025 Topps Sole Ambition LeBron James #SA-1 CGC AUTH", 33.00, 1.05, 34.65, 3, 31.65, 1543, "2026-02-21"),
    (2571, "2022 Flawless Collegiate Star Swatch Jaren Jackson Jr. AUTO /25 #SS-JJJ", 31.00, 1.05, 32.55, 0, 32.55, 1272, "2026-02-21"),
    (2597, "2022 Immaculate Ink Steve Kerr AUTO /99 #II-SKR CGC AUTH", 30.00, 1.05, 31.50, 3, 28.50, 1271, "2026-02-21"),
    (3084, "2024 Immaculate Blue Jared McCain RPA /49 #122 CGC AUTH", 29.00, 1.05, 30.45, 3, 27.45, 1870, "2026-02-21"),
    (2612, "2023 One And One Green Jalen Johnson 5/5 #2", 26.00, 1.05, 27.30, 0, 27.30, 804, "2026-02-21"),
    (2813, "2024 One And One Orange Bronny James Jr. /49 #108", 19.00, 1.05, 19.95, 0, 19.95, 1472, "2026-02-21"),
    (2732, "2023 Topps Three Triple Gold Mikal Bridges PATCH AUTO 10/10 #TRA-MB", 16.00, 1.05, 16.80, 0, 16.80, 1561, "2026-02-21"),
]


def main():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    results = []
    not_found = []
    total_hammer = 0
    total_gross = 0
    total_cgc = 0
    total_net = 0
    total_cost = 0
    total_profit = 0
    used_ids = set()

    for lot, title, hammer, split_pct, gross, cgc_fee, net, card_id, sale_date in SALES:
        total_hammer += hammer
        total_gross += gross
        total_cgc += cgc_fee
        total_net += net

        if card_id is None:
            not_found.append((lot, title, hammer, gross, cgc_fee, net))
            continue

        if card_id in used_ids:
            not_found.append((lot, f"[DUP ID] {title}", hammer, gross, cgc_fee, net))
            continue
        used_ids.add(card_id)

        # Look up card
        c.execute("SELECT id, player, year, brand, set_name, variation, grade, grading_company, purchase_price, status FROM cards WHERE id = ?", (card_id,))
        card = c.fetchone()
        if not card:
            not_found.append((lot, f"[ID NOT FOUND] {title}", hammer, gross, cgc_fee, net))
            continue

        card_id_db, player, year, brand, set_name, variation, grade, grading_co, purchase_price, status = card
        if status == 'SOLD':
            not_found.append((lot, f"[ALREADY SOLD] {title}", hammer, gross, cgc_fee, net))
            continue

        paid = purchase_price or 0
        profit = net - paid

        # Record sell transaction
        # price = gross proceeds (hammer + buyer's premium)
        # fees = CGC auth fee ($0 or $3)
        c.execute("""INSERT INTO transactions (card_id, transaction_type, price, fees, platform, ebay_order_id, notes, executed_at)
                     VALUES (?, 'SELL', ?, ?, 'goldin', ?, ?, ?)""",
                  (card_id, gross, cgc_fee, f"Lot-{lot}", f"Goldin Lot #{lot} — Hammer ${hammer:,.0f} x {split_pct:.0%}", sale_date + "T12:00:00"))

        # Mark card as sold
        c.execute("UPDATE cards SET status = 'SOLD' WHERE id = ?", (card_id,))

        total_cost += paid
        total_profit += profit

        results.append({
            "lot": lot,
            "id": card_id,
            "player": player[:30],
            "year": year,
            "hammer": hammer,
            "split": split_pct,
            "gross": gross,
            "cgc": cgc_fee,
            "net": net,
            "paid": paid,
            "profit": profit,
        })

    conn.commit()

    # Print results table
    print(f"\n{'='*155}")
    print(f"{'GOLDIN AUCTION RESULTS — P&L BY LOT':^155}")
    print(f"{'='*155}")
    print(f"{'Lot':>5} | {'ID':>5} | {'Player':<30} | {'Year':>4} | {'Hammer':>10} | {'Split':>5} | {'Gross':>10} | {'CGC':>5} | {'Net':>10} | {'Paid':>10} | {'Profit':>10}")
    print(f"{'-'*155}")

    for r in results:
        pm = "+" if r["profit"] >= 0 else ""
        print(f"{r['lot']:>5} | {r['id']:>5} | {r['player']:<30} | {r['year'] or '':>4} | ${r['hammer']:>9,.2f} | {r['split']:.0%} | ${r['gross']:>9,.2f} | ${r['cgc']:>4} | ${r['net']:>9,.2f} | ${r['paid']:>9,.2f} | {pm}${r['profit']:>8,.2f}")

    print(f"{'-'*155}")
    matched_cost = sum(r["paid"] for r in results)
    matched_gross = sum(r["gross"] for r in results)
    matched_cgc = sum(r["cgc"] for r in results)
    matched_net = sum(r["net"] for r in results)
    matched_profit = sum(r["profit"] for r in results)
    matched_hammer = sum(r["hammer"] for r in results)
    pm = "+" if matched_profit >= 0 else ""
    print(f"{'MATCHED TOTALS':>44} | ${matched_hammer:>9,.2f} |       | ${matched_gross:>9,.2f} | ${matched_cgc:>4} | ${matched_net:>9,.2f} | ${matched_cost:>9,.2f} | {pm}${matched_profit:>8,.2f}")

    print(f"\n{'='*80}")
    print(f"  GOLDIN AUCTION SUMMARY")
    print(f"{'='*80}")
    print(f"  Lots matched & recorded:   {len(results)}")
    print(f"  Lots NOT matched:          {len(not_found)}")
    print(f"  Total Hammer Price:        ${total_hammer:>12,.2f}")
    print(f"  Total Gross (w/ premium):  ${total_gross:>12,.2f}")
    print(f"  Total CGC Auth Fees:       ${total_cgc:>12,.2f}")
    print(f"  Total Net Proceeds:        ${total_net:>12,.2f}")
    print(f"  Total Cost Basis (matched):${matched_cost:>12,.2f}")
    print(f"  Total Net (matched):       ${matched_net:>12,.2f}")
    print(f"  Total Profit (matched):    ${matched_profit:>12,.2f}")
    print(f"  Avg Margin (matched):      {(matched_profit/matched_cost*100) if matched_cost else 0:>11.1f}%")
    print(f"  Buyer Premium Collected:   ${(total_gross - total_hammer):>12,.2f}")
    print(f"{'='*80}")

    if not_found:
        print(f"\n  UNMATCHED LOTS ({len(not_found)}):")
        for lot, title, h, g, c_fee, n in not_found:
            print(f"    Lot #{lot}: {title} — Hammer ${h:,.2f}, Gross ${g:,.2f}, Net ${n:,.2f}")

    # Verify
    c.execute("SELECT COUNT(*) FROM cards WHERE status = 'SOLD'")
    print(f"\n  DB Verification: {c.fetchone()[0]} cards now marked SOLD")
    c.execute("SELECT COUNT(*) FROM transactions WHERE transaction_type = 'SELL'")
    print(f"  DB Verification: {c.fetchone()[0]} sell transactions recorded")

    conn.close()


if __name__ == "__main__":
    main()
