#!/usr/bin/env python3
"""Batch process Fanatics Collect sale results into the inventory DB."""

import sqlite3
from datetime import datetime

DB = "sports_cards.db"

# Each sale: (cert, player_desc, date_sold, sale_price, fees, net, card_id_match, platform)
# card_id_match is the DB card ID we matched to.
# For duplicate certs (same card sold twice), only keep the LATEST sale.
# platform: "fanatics" for most, "dcsports" for $0-fee entries

SALES = [
    # --- Feb 2026 sales ---
    ("106320018", "2018 Bowman RC #49 Shohei Ohtani PSA 10", "2026-02-26", 335.00, 43.55, 291.45, 242, "fanatics"),
    ("56470867", "1997 Topps Chrome #109 Shaquille O'Neal PSA 9", "2026-02-26", 20.00, 5.60, 14.40, 2053, "fanatics"),
    ("99762809", "2002 Topps Chrome Chinese RC #146 Yao Ming PSA 10", "2026-02-25", 280.00, 36.40, 243.60, 709, "fanatics"),
    ("113452247", "2024 Panini Absolute Kaboom #10 Marvin Harrison Jr PSA 10", "2026-02-24", 600.00, 72.00, 528.00, 326, "fanatics"),
    ("28616428", "2015 Panini Prizm Auto #KPZ Kristaps Porzingis PSA 10", "2026-02-24", 100.00, 13.00, 87.00, 2019, "fanatics"),
    # Wemby Blue Sparkle [#79/124] — dup cert, latest sale Feb 24
    ("101026554", "2024 NSCC VIP Gold Rookies Blue Sparkle RC1 Victor Wembanyama PSA 10", "2026-02-24", 399.99, 52.00, 347.99, 2063, "fanatics"),
    ("100782933", "2024 Topps Update #US100 Paul Skenes PSA 9", "2026-02-23", 24.70, 6.21, 18.49, None, "fanatics"),  # NOT FOUND in DB
    ("44396216", "2019 Bowman Chrome Auto Refractor [#/499] Julio Rodriguez PSA 10", "2026-02-23", 2150.00, 215.00, 1935.00, 1063, "fanatics"),
    ("136950950", "2020 NT Collegiate 150th [#1/5] #4 Isaiah Simmons PSA 9", "2026-02-23", 638.02, 0.00, 638.02, 1411, "dcsports"),
    ("0013677890", "2018-19 Panini Noir #271 LeBron James/Kobe Bryant BGS 9", "2026-02-22", 530.00, 63.60, 466.40, 427, "fanatics"),
    ("1595267", "2024-25 Bowman U Chrome Orange Shimmer 56/65 #48 Kon Knueppel SGC 10", "2026-02-22", 110.50, 14.37, 96.13, None, "fanatics"),  # NOT FOUND
    ("137904728", "2025 Topps Season Tip Off Gold Foilboard [#12/50] #195 Victor Wembanyama PSA 9", "2026-02-22", 229.50, 29.84, 199.66, 246, "fanatics"),
    ("133014025", "2024 Topps Chrome Sapphire Red [#2/5] Tyrese Maxey PSA 9", "2026-02-14", 141.37, 18.38, 122.99, 493, "fanatics"),
    ("94863780", "2023 Bowman U Chrome Prime Signatures Superfractor 1/1 Zayden High PSA 9", "2026-02-20", 42.00, 8.46, 33.54, 1069, "fanatics"),
    ("07017312", "1994 Finest Refractor W/Coating #331 Michael Jordan PSA 9", "2026-02-19", 1999.00, 199.90, 1799.10, 741, "fanatics"),
    ("0013598019", "2018-19 Panini Prizm Pink Ice #296 Giannis Antetokounmpo BGS 9", "2026-02-15", 50.00, 9.50, 40.50, 1110, "fanatics"),
    # Gavi Zebra [#8/25] — dup cert, latest Feb 17
    ("101804340", "2023-24 Panini Select FIFA Zebra [#8/25] #24 Gavi PSA 8", "2026-02-17", 20.00, 5.60, 14.40, 539, "fanatics"),
    ("92600001", "2020 Panini Select Gold Die-Cut [#3/10] #169 Anthony Edwards PSA 10", "2026-02-16", 4999.00, 449.91, 4549.09, 900, "fanatics"),
    ("97314648", "2022 Spectra Illustrious Legends Meta [#15/25] Allen Iverson PSA 10", "2026-02-15", 426.00, 55.38, 370.62, 2418, "fanatics"),
    ("136530176", "2024 Panini Flawless Gold [#5/5] #186 Anthony Davis PSA 9", "2026-02-15", 115.50, 15.02, 100.48, 22, "fanatics"),
    ("0013581734", "2018-19 Spectra Rising Stars Neon Pink #17 Luka Doncic BGS 8.5", "2026-02-08", 1875.00, 187.50, 1687.50, 730, "fanatics"),
    ("100461721", "2023 Topps Chrome Sapphire Red [#5/5] Tyrese Maxey PSA 10", "2026-02-15", 260.00, 33.80, 226.20, 23, "fanatics"),
    # VJ Edgecombe Orange Rainbow [#7/25] — dup cert, latest Feb 14
    ("136812784", "2025 Topps New School Orange Rainbow [#7/25] NS-3 VJ Edgecombe PSA 9", "2026-02-14", 266.59, 34.66, 231.93, 24, "fanatics"),
    ("110820055", "2024 Prizm Draft Picks Gold [#7/10] #74 Matthew Stafford PSA 9", "2026-02-15", 94.00, 15.22, 78.78, 25, "fanatics"),
    ("96133541", "2024 NSCC VIP Gold Rookies Red Sparkle [#142/149] RC1 Victor Wembanyama PSA 9", "2026-02-14", 107.50, 13.98, 93.52, 1124, "fanatics"),
    ("133151892", "2024 Bowman U Best Superfractor 1/1 #77 Jeremy Fears PSA 9", "2026-02-15", 535.00, 64.20, 470.80, 388, "fanatics"),
    ("125452165", "1997 Ultra Star Power #1 Michael Jordan PSA 8", "2026-02-15", 100.00, 13.00, 87.00, 1173, "fanatics"),
    ("133299869", "2011 UD Exquisite Endorsements Dual Auto [#18/20] Magic Johnson/Michael Jordan PSA Auth", "2026-02-15", 7023.00, 491.61, 6531.39, 574, "fanatics"),
    ("117603401", "2004 UD Exquisite Masterpieces Printing Plate 1/1 LeBron James PSA 9", "2026-02-15", 2200.00, 220.00, 1980.00, 936, "fanatics"),
    ("11163934", "1996 Bowman's Best RC #R23 Kobe Bryant PSA 10", "2026-02-15", 900.00, 108.00, 792.00, 1004, "fanatics"),
    ("55245374", "2020 Prizm Draft Picks Auto Red Ice Pat Spencer PSA 10", "2026-02-14", 305.00, 39.65, 265.35, 983, "fanatics"),
    ("53699831", "2018 Donruss Optic Purple RC #162 Shai Gilgeous-Alexander PSA 9", "2026-02-13", 105.00, 13.65, 91.35, 374, "fanatics"),
    ("16985163", "2000 Playoff Momentum RC [#/750] #180 Tom Brady PSA 9", "2026-02-13", 7000.00, 490.00, 6510.00, 1035, "fanatics"),
    # Andrew Wiggins Gold Refractor [#27/50] — dup cert, latest Feb 7
    ("99816830", "2023 Topps Chrome Auto Gold Refractor [#27/50] Andrew Wiggins PSA 10", "2026-02-07", 20.05, 5.61, 14.44, 629, "fanatics"),
    ("112556200", "2023 Origins Universal Auto Pink [#8/15] Nikola Jokic PSA 8", "2026-02-11", 450.00, 58.50, 391.50, 2227, "fanatics"),
    ("137699520", "1998 Upper Deck Jordan Tribute MJ Reflections #MJ81 Michael Jordan PSA 10", "2026-02-10", 250.00, 32.50, 217.50, 171, "fanatics"),
    # Dwyane Wade Mojo — dup cert, latest Feb 9
    ("125808926", "2024 Prizm Deca Mojo [#16/25] #217 Dwyane Wade PSA 10", "2026-02-09", 132.50, 17.23, 115.27, 453, "fanatics"),
    ("89633897", "2003 Topps Chrome RC #111 LeBron James PSA 9", "2026-02-09", 2400.00, 240.00, 2160.00, 1042, "fanatics"),
    ("127163019", "2025 Topps Chrome Black Auto Orange Refractor [#2/25] Rod Carew PSA 9", "2026-02-07", 53.00, 9.89, 43.11, 761, "fanatics"),
    ("0015739310", "2002-03 Topps Finest #182 Dwayne Wade BGS 9", "2026-02-08", 26.00, 6.38, 19.62, None, "fanatics"),  # NOT FOUND
    ("91362449", "2023 Topps Chrome Update Blue Refractor [#137/150] Anthony Volpe PSA 10", "2026-02-08", 48.31, 0.00, 48.31, 768, "dcsports"),
    # Caitlin Clark Blue Sparkle — dup cert, latest Feb 7
    ("109566108", "2024 NSCC VIP Gold Blue Sparkle [#71/124] #1 Caitlin Clark PSA 9", "2026-02-07", 143.83, 18.70, 125.13, 484, "fanatics"),
    ("97357257", "2024 Topps Finest Blue Checkerboard [#35/99] #50 Yoshinobu Yamamoto PSA 10", "2026-02-07", 258.00, 33.54, 224.46, 1171, "fanatics"),
    ("106386900", "2024 Panini Origins #103 JJ McCarthy PSA 9", "2026-02-07", 15.44, 0.00, 15.44, 1195, "dcsports"),
    # --- Jan 2026 sales ---
    ("58987774", "2015 Panini Select Silver Prizm RC #128 Nikola Jokic PSA 9", "2026-01-28", 649.99, 78.00, 571.99, 2263, "fanatics"),
    ("137112634", "2025 Topps All Kings #AK-13 Jalen Brunson PSA 10", "2026-01-18", 1650.00, 165.00, 1485.00, 1624, "fanatics"),
    ("113900753", "2023 Donruss Optic Purple Shock #225 Victor Wembanyama PSA 10", "2026-01-11", 198.28, 25.78, 172.50, 1403, "fanatics"),
    ("100039277", "2024 NSCC VIP Gold Rookies National [#14/44] RC1 Victor Wembanyama PSA 9", "2026-01-11", 144.50, 18.79, 125.71, 2117, "fanatics"),
    ("116440011", "2015 Panini Prizm RC #335 Nikola Jokic PSA 9", "2026-01-14", 429.99, 55.90, 374.09, None, "fanatics"),  # No base Prizm 335 PSA 9 in DB
    ("135445914", "2022 Panini National Gold [#2/10] #22 LeBron James PSA 9", "2026-01-11", 152.50, 19.83, 132.67, 2125, "fanatics"),
    ("122921499", "2023 National VIP Gold Purple Sparkle [#27/50] #22 LeBron James PSA 10", "2026-01-11", 535.00, 64.20, 470.80, 2229, "fanatics"),
    ("2853984", "2022-23 Bowman U Inception Auto Fuchsia Foil Juju Watkins SGC 10", "2026-01-11", 284.79, 37.02, 247.77, 1238, "fanatics"),
    ("55081112", "2016 Spectra Catalysts Relic Pink [#/49] #12 Stephen Curry PSA 9", "2026-01-11", 155.50, 20.22, 135.28, 2135, "fanatics"),
    ("136323062", "2025 Topps All Kings #AK-4 Giannis Antetokounmpo PSA 9", "2026-01-11", 422.00, 54.86, 367.14, 1318, "fanatics"),
    ("106858277", "2023 Prizm Draft Picks Purple Wave #2 Victor Wembanyama PSA 10", "2026-01-11", 102.50, 13.33, 89.17, 2196, "fanatics"),
    ("113385380", "1994 Upper Deck MJ Rare Air #61 Michael Jordan PSA 10", "2026-01-10", 855.00, 102.60, 752.40, 2414, "fanatics"),
    # Dwyane Wade Mojo dup — earlier sale Jan 11 (keeping Feb 9 as latest)
    # Caitlin Clark WNBA Prizm PSA 8
    ("122169763", "2024 Panini Prizm WNBA #145 Caitlin Clark PSA 8", "2026-01-11", 20.50, 5.67, 14.83, 2050, "fanatics"),
    ("120329065", "2024 Prizm Deca Purple [#1/99] #285 Victor Wembanyama PSA 9", "2026-01-11", 67.00, 11.71, 55.29, None, "fanatics"),  # No specific match
    ("98729840", "2024 NSCC VIP Gold Rookies Green Sparkle [#14/99] RC1 Victor Wembanyama PSA 10", "2026-01-11", 256.00, 33.28, 222.72, 2190, "fanatics"),
    ("117358254", "2024 Bowman Chrome U Black Wave #16 Cooper Flagg PSA 10", "2026-01-04", 152.50, 19.83, 132.67, None, "fanatics"),  # No Black Wave Flagg PSA 10 match
    # Caitlin Clark Blue Sparkle earlier sale Jan 11 — dup, skip
    ("66746356", "2018 Panini National VIP Cracked Ice [#42/50] #64 Stephen Curry PSA 9", "2026-01-11", 126.56, 16.45, 110.11, 485, "fanatics"),
    ("91743475", "2023 Prizm Draft Picks Silver Prizm #2 Victor Wembanyama PSA 10", "2026-01-11", 87.85, 14.42, 73.43, 488, "fanatics"),
    ("84478457", "2023 National VIP Gold Blue Yellow Green [#25/25] #39 Nikola Jokic PSA 10", "2026-01-11", 157.50, 20.48, 137.02, 2198, "fanatics"),
    ("0015014867", "2012-13 Prestige True Colors Materials #25 Stephen Curry BGS 9", "2026-01-11", 134.49, 17.48, 117.01, 1142, "fanatics"),
    # Wemby Blue Sparkle earlier sale Jan 11 — dup, skip
    # VJ Edgecombe Orange Rainbow earlier sale Jan 11 — dup, skip
    ("76397134", "2020 Absolute Tools of Trade Swatch Signatures [#184/199] Tyrese Maxey PSA 8", "2026-01-10", 169.50, 22.04, 147.46, 537, "fanatics"),
    ("0014057613", "2020-21 Panini One & One Rookie Jersey Auto Gold #23 Tyrese Maxey BGS 9.5", "2026-01-08", 1801.87, 180.19, 1621.68, 538, "fanatics"),
    # Gavi Zebra earlier sale Jan 10 — dup, skip
    ("120984639", "2024 Topps 50/50 Chrome-Gold Refractor [#17/50] #89 Shohei Ohtani PSA 9", "2026-01-10", 433.00, 56.29, 376.71, 1552, "fanatics"),
    ("107743034", "2024 Prizm Draft Picks Auto Gold [#10/10] Angel Reese PSA 10", "2026-01-09", 499.00, 64.87, 434.13, 2301, "fanatics"),
    ("119326026", "2024 Bowman Chrome U Purple Lava #16 Cooper Flagg PSA 10", "2026-01-05", 126.50, 16.45, 110.05, 575, "fanatics"),
    ("00017158162", "2023 Donruss Elite WWE Elite Deck Auto #7 Hulk Hogan BGS Auth", "2026-01-07", 178.19, 23.16, 155.03, 1885, "fanatics"),
    ("98748914", "2024 NSCC VIP Gold Rookies Pink Sparkle [#35/88] RC9 Caitlin Clark PSA 8", "2026-01-06", 199.00, 25.87, 173.13, 1788, "fanatics"),
    ("135559564", "2025 Topps Generation Now Gold Holo Foil [#50/50] GN-3 VJ Edgecombe PSA 10", "2026-01-06", 1779.00, 177.90, 1601.10, 2245, "fanatics"),
    ("0013681672", "2021 Leaf Valiant Here Comes the Boom Orange Micah Parsons BGS 9.5", "2026-01-04", 50.00, 9.50, 40.50, 1348, "fanatics"),
    ("121411265", "2024 Bowman U Best Field Day Shimmer Refractor #FD1 Cooper Flagg PSA 10", "2026-01-04", 87.56, 14.38, 73.18, 2331, "fanatics"),
    ("84948779", "2023 Pokemon CLV Venusaur & Lugia ex Deck #017 Lugia EX PSA 9", "2026-01-04", 14.50, 4.89, 9.61, None, "fanatics"),  # NOT FOUND - no Pokemon in DB
    ("121409132", "2024 Panini Prizm Monopoly WNBA Red Classic #27 Caitlin Clark PSA 10", "2026-01-04", 152.50, 19.83, 132.67, 1283, "fanatics"),
    ("122806794", "2024 Bowman Chrome U Black Wave #48 Kon Knueppel PSA 10", "2026-01-04", 55.00, 10.15, 44.85, 2325, "fanatics"),
    ("116429307", "2024 Bowman Chrome U Eye Test Auto Kon Knueppel PSA 10", "2026-01-04", 345.00, 44.85, 300.15, 1666, "fanatics"),
    ("83967802", "2022 Panini Recon Vector #5 Stephen Curry PSA Auth", "2026-01-04", 510.00, 61.20, 448.80, 1640, "fanatics"),
    ("92939022", "2023 Bowman U Chrome Auto #68 Tetairoa McMillan PSA 9", "2026-01-04", 58.77, 10.64, 48.13, 1575, "fanatics"),
    ("121924750", "2021 Select Prime Selections Signatures Gold [#2/10] Trevor Lawrence PSA 8", "2026-01-04", 649.99, 78.00, 571.99, 1025, "fanatics"),
    ("119580743", "2023 National VIP Gold Green Sparkle [#53/99] #25 Stephen Curry PSA 10", "2026-01-02", 69.00, 11.97, 57.03, 630, "fanatics"),
    # Andrew Wiggins dup earlier sale Jan 2 — skip
    ("64980720", "2020 Panini Prizm Fast Break Blue [#130/175] #159 Stephen Curry PSA 9", "2026-01-02", 50.99, 9.63, 41.36, 1141, "fanatics"),
    ("130356466", "2024 Immaculate Signatures [#78/99] John Stockton PSA 9", "2026-01-02", 122.50, 15.93, 106.57, 1679, "fanatics"),
    ("64535469", "2014 National VIP Party Patch Cracked Ice [#7/10] #62 Stephen Curry PSA 9", "2026-01-02", 853.00, 102.36, 750.64, None, "fanatics"),  # 2014 Curry not found
    ("112732631", "2024 Bowman Chrome U Final Exam Auto Cooper Flagg PSA 10", "2026-01-01", 1999.00, 199.90, 1799.10, 2260, "fanatics"),
    ("120767319", "2024 Bowman Draft Chrome Auto Refractor [#343/499] Konnor Griffin PSA 9", "2026-01-01", 850.00, 102.00, 748.00, 1040, "fanatics"),
    ("120714939", "2024 Panini Prizm Silver Prizm #329 Drake Maye PSA 10", "2026-01-01", 1649.00, 164.90, 1484.10, 1036, "fanatics"),
    # --- Dec 2025 sales ---
    ("135273042", "2025 NSCC VIP Gold Gold [#9/10] #42 Paul Skenes PSA 10", "2025-12-31", 399.00, 51.87, 347.13, None, "fanatics"),  # No PSA 10 Skenes NSCC match
    ("121400528", "2025 Topps All Kings #AK10 Vladimir Guerrero Jr PSA 10", "2025-12-30", 850.00, 102.00, 748.00, 1597, "fanatics"),
    ("121377348", "2024 Bowman U Best Let It Rain Relic Auto Orange Geometric [#13/25] Cooper Flagg PSA 9", "2025-12-30", 1680.00, 168.00, 1512.00, 2306, "fanatics"),
    ("101977266", "2023 Panini Mosaic Gold [#5/10] #31 Luka Doncic PSA 10", "2025-12-28", 379.00, 49.27, 329.73, 1215, "fanatics"),
    ("97742028", "2023 Panini Mosaic Gold [#6/10] #285 Luka Doncic PSA 10", "2025-12-28", 379.00, 49.27, 329.73, None, "fanatics"),  # Only 1 Mosaic Gold in DB, already used
    ("137587976", "2024 Prizm Black Red Power [#74/75] #7 Stephen Curry PSA 10", "2025-12-27", 549.00, 65.88, 483.12, 1084, "fanatics"),
    ("78888824", "2022 Prizm Purple Fast Break [#50/75] #101 Stephen Curry PSA 10", "2025-12-27", 172.08, 0.00, 172.08, 1168, "dcsports"),
    ("0007246971", "2010-11 National Treasures Century Materials Signatures Kobe Bryant/99 BGS 9", "2025-12-25", 1399.00, 139.90, 1259.10, 2121, "fanatics"),
]


def main():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    results = []
    not_found = []
    total_revenue = 0
    total_fees = 0
    total_net = 0
    total_cost = 0
    total_profit = 0
    used_ids = set()

    for cert, desc, date_sold, sale_price, fees, net, card_id, platform in SALES:
        total_revenue += sale_price
        total_fees += fees
        total_net += net

        if card_id is None:
            not_found.append((cert, desc, sale_price, fees, net))
            continue

        if card_id in used_ids:
            not_found.append((cert, f"[DUP ID] {desc}", sale_price, fees, net))
            continue
        used_ids.add(card_id)

        # Look up card
        c.execute("SELECT id, player, year, brand, set_name, variation, grade, grading_company, purchase_price, status FROM cards WHERE id = ?", (card_id,))
        card = c.fetchone()
        if not card:
            not_found.append((cert, f"[ID NOT FOUND] {desc}", sale_price, fees, net))
            continue

        card_id_db, player, year, brand, set_name, variation, grade, grading_co, purchase_price, status = card
        paid = purchase_price or 0
        profit = net - paid

        # Record sell transaction
        c.execute("""INSERT INTO transactions (card_id, transaction_type, price, fees, platform, ebay_order_id, notes, executed_at)
                     VALUES (?, 'SELL', ?, ?, ?, ?, ?, ?)""",
                  (card_id, sale_price, fees, platform, cert, f"Sold {date_sold} on {platform}", date_sold + "T12:00:00"))

        # Mark card as sold
        c.execute("UPDATE cards SET status = 'SOLD' WHERE id = ?", (card_id,))

        # Update cert_number
        try:
            c.execute("UPDATE cards SET cert_number = ? WHERE id = ? AND (cert_number IS NULL OR cert_number = '')", (cert, card_id))
        except sqlite3.IntegrityError:
            pass  # cert already exists on another card

        total_cost += paid
        total_profit += profit

        results.append({
            "id": card_id,
            "cert": cert,
            "player": player[:35],
            "year": year,
            "grade": f"{grading_co or ''} {grade or ''}".strip(),
            "paid": paid,
            "sold": sale_price,
            "fees": fees,
            "net": net,
            "profit": profit,
            "date": date_sold,
            "platform": platform,
        })

    conn.commit()

    # Print results table
    print(f"\n{'='*140}")
    print(f"{'SALE RESULTS — P&L BY CARD':^140}")
    print(f"{'='*140}")
    print(f"{'ID':>5} | {'Player':<35} | {'Year':>4} | {'Grade':<8} | {'Paid':>10} | {'Sold':>10} | {'Fees':>8} | {'Net':>10} | {'Profit':>10} | {'Date':<10} | {'Platform':<9}")
    print(f"{'-'*140}")

    for r in results:
        profit_marker = "+" if r["profit"] >= 0 else ""
        print(f"{r['id']:>5} | {r['player']:<35} | {r['year'] or '':>4} | {r['grade']:<8} | ${r['paid']:>9,.2f} | ${r['sold']:>9,.2f} | ${r['fees']:>7,.2f} | ${r['net']:>9,.2f} | {profit_marker}${r['profit']:>8,.2f} | {r['date']:<10} | {r['platform']:<9}")

    print(f"{'-'*140}")
    matched_cost = sum(r["paid"] for r in results)
    matched_net = sum(r["net"] for r in results)
    matched_profit = sum(r["profit"] for r in results)
    matched_sold = sum(r["sold"] for r in results)
    matched_fees = sum(r["fees"] for r in results)
    print(f"{'MATCHED TOTALS':>47} | ${matched_cost:>9,.2f} | ${matched_sold:>9,.2f} | ${matched_fees:>7,.2f} | ${matched_net:>9,.2f} | {'+'if matched_profit>=0 else ''}${matched_profit:>8,.2f}")

    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}")
    print(f"  Cards matched & recorded:  {len(results)}")
    print(f"  Cards NOT matched:         {len(not_found)}")
    print(f"  Total Sale Revenue:        ${total_revenue:>12,.2f}")
    print(f"  Total Fees:                ${total_fees:>12,.2f}")
    print(f"  Total Net Proceeds:        ${total_net:>12,.2f}")
    print(f"  Total Cost Basis (matched):${matched_cost:>12,.2f}")
    print(f"  Total Net (matched):       ${matched_net:>12,.2f}")
    print(f"  Total Profit (matched):    ${matched_profit:>12,.2f}")
    print(f"  Avg Margin (matched):      {(matched_profit/matched_cost*100) if matched_cost else 0:>11.1f}%")
    print(f"{'='*80}")

    if not_found:
        print(f"\n  UNMATCHED SALES ({len(not_found)}):")
        for cert, desc, sp, f, n in not_found:
            print(f"    Cert #{cert}: {desc} — Sold ${sp:,.2f}, Fees ${f:,.2f}, Net ${n:,.2f}")

    # Verify
    c.execute("SELECT COUNT(*) FROM cards WHERE status = 'SOLD'")
    print(f"\n  DB Verification: {c.fetchone()[0]} cards now marked SOLD")
    c.execute("SELECT COUNT(*) FROM transactions WHERE transaction_type = 'SELL'")
    print(f"  DB Verification: {c.fetchone()[0]} sell transactions recorded")

    conn.close()


if __name__ == "__main__":
    main()
