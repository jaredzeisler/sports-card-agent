#!/usr/bin/env python3
"""Goldin Pipeline Pull Analysis — June 2026.

Flags which cards in the Goldin pipeline (Pending Authentication, Pending Auction
Placement, Upcoming, Buy It Now) should NOT go to Goldin based on loss patterns
observed in ~79 completed Goldin sales.

Key findings from completed sales:
  - 31% overall win rate, -$1,345 net P&L (-1.8%)
  - Giannis autos: consistently -40-70% loss
  - Chet Holmgren: every card lost money
  - Paolo Banchero: trending down, soft market
  - Legacy HOF non-flagships (Ray Allen, Gilbert Arenas, etc.): big losses
  - LeBron/Curry secondary inserts: underperform vs. eBay cost
  - Cards bought at eBay retail premium: rarely recoup at Goldin

Seller proceeds formula: hammer × 1.15 (seller gets 15% of 22% buyer premium)
"""

# ═══════════════════════════════════════════════════════════════════════════════
# RED FLAG — PULL THESE FROM GOLDIN (31 cards, ~$17,720 cost basis at risk)
# Estimated loss if sent: -$5,000 to -$7,000
# ═══════════════════════════════════════════════════════════════════════════════

PULL_FROM_GOLDIN = [
    # ── GIANNIS ANTETOKOUNMPO (13 cards, ~$7,976 at risk) ──
    # Every Giannis auto lost 40-70% in completed sales. Oversaturated at Goldin.
    "2018-19 Panini Threads Signage Premium Gold #36 Giannis Antetokounmpo Signed Card (#1/5)",
    "2017-18 Panini Contenders MVP Contenders Autographs Gold #MVP-GA Giannis Antetokounmpo Signed Card (#09/10)",
    "2015-16 Panini Immaculate Collection Autographs Blue #17 Giannis Antetokounmpo Signed Card (#03/10)",
    "2025-26 Topps All Kings #AK-4 Giannis Antetokounmpo",
    "2018-19 Panini Opulence City of Gold Signatures Holo Gold #CG-GAN Giannis Antetokounmpo Signed Card (#24/25)",
    "2024-25 Panini Immaculate Collection Patch Autographs International Red #PAU-GAN Giannis Antetokounmpo Signed Patch Card (#1/5)",
    "2025 Panini The National VIP Gold Signatures Gold Pulsar #22 Giannis Antetokounmpo Signed Card (#01/10)",
    "2018-19 Panini Opulence Opulent Autographs Gold #OA-GAN Giannis Antetokounmpo Signed Card (#03/25)",
    "2024-25 Panini Select Signatures Blue Prizm #SIG-GIA Giannis Antetokounmpo Signed Card (#07/49)",
    "2024-25 Panini Prizm Black Prizmatrix Signatures #PS-GIA Giannis Antetokounmpo Signed Card",
    "2024-25 Panini Flawless Dual Patches Ruby #DP-GNA Giannis Antetokounmpo Patch Card (#15/15)",
    "2017-18 Panini National Treasures All-Decade Memorabilia Signatures #ADMS-GAN Giannis Antetokounmpo Signed Relic Card (#25/25)",
    "2024-25 Panini Prizm Black Dual Autographs Mojo #DA-MIL Damian Lillard/Giannis Antetokounmpo Dual-Signed Card (#06/25)",

    # ── PAOLO BANCHERO (3 cards, ~$3,709 at risk) ──
    # Paolo trending down hard. Secondary market very soft.
    "2023-24 Panini Immaculate Collection Patch Autographs Jersey Number #IPA-PAO Paolo Banchero Signed Patch Card (#5/5)",
    "2024-25 Panini Immaculate Collection Moden Marks Gold #MM-PBA Paolo Banchero Signed Card (#05/10)",
    "2022-23 Panini National Treasures Treasured Moments #TM-PBC Paolo Banchero Signed Rookie Card (#59/99)",

    # ── CHET HOLMGREN (1 card, ~$1,005) ──
    # Every Chet card lost money. Even as a 1/1, risk is high.
    "2024-25 Panini Select Snake Skin Black Pulsar FOTL Prizm #128 Chet Holmgren (#1/1)",

    # ── DWYANE WADE (1 card, ~$1,556) ──
    # Legacy HOF at high cost basis = loss at Goldin
    "2007-08 Upper Deck Exquisite Collection #4 Dwyane Wade (#132/225)",

    # ── NICHE / LOW-DEMAND PLAYERS ──
    "2025 Bowman Chrome U Sapphire Selections Autograph #SS-FM Fernando Mendoza Signed Rookie Card (#20/25)",
    "2023-24 Panini Flawless Finishes #FF-KYG Keyonte George Signed Rookie Card (#23/25)",
    "2024-25 Panini Flawless Memorabilia #FM-DGL Darius Garland Relic Card (#1/5)",
    "2024-25 Topps Finest Electrifying Signatures Geometric SuperFractor #ES-CS Cam Spencer Signed Rookie Card (#1/1)",
    "2021-22 Panini Origins Rookie Jersey Autographs Red #JA-CUN Cade Cunningham Signed Patch Rookie Card (#09/49)",
    "2023-24 Panini Immaculate Collection Immaculate Patch Autographs Red #IPA-GBT Gilbert Arenas Signed Patch Card (#16/25)",
    "2023-24 Panini Immaculate Collection Clutch Time Signatures #CTS-GIL Gilbert Arenas Signed Card (#39/99)",
    "2023-24 Panini Immaculate Collection Patch Autographs Gold #IPA-GBT Gilbert Arenas Signed Patch Card (#03/10)",
    "2022-23 Panini Contenders Veteran Ticket Autographs Cracked Ice '25 Black Box #VT-PBC Paul Pierce Signed Card (#1/1)",
    "2024-25 Panini Immaculate Collection Heralded Signatures #HRS-RAY Ray Allen Signed Card (#15/25)",
    "2024-25 Panini Immaculate Collection Immaculate Legends #IL-LEN Ray Allen Signed Card (#49/49)",
    "2025-26 Topps 1980-81 Topps Basketball Autographs Orange Rainbow #80CA2-JW Jaylen Wells Signed Card (#01/25)",
    "2021-22 Panini Contenders Rookie Season Ticket Autographs Cracked Ice Ticket #162 Austin Reaves Signed Rookie Card (#24/25)",
]


# ═══════════════════════════════════════════════════════════════════════════════
# YELLOW FLAG — WATCH CLOSELY (top 30 highest-risk from 106 total)
# These match partial loss patterns — monitor and pull if bid softens
# ═══════════════════════════════════════════════════════════════════════════════

WATCH_CLOSELY = [
    # High cost basis + relic-only (no auto) = Goldin discounts these
    "2024-25 Panini Flawless Vault Memorabilia #FVM-DML Damian Lillard Patch Card (#09/14) - PSA NM 7",
    "2020-21 Panini Flawless Patches #PT-LBJ LeBron James Patch Card (#20/20)",
    "2023-24 Panini Flawless Premium Memorabilia #PRM-LJA LeBron James Patch Card (#10/10)",
    "2023-24 Panini Flawless Premium Memorabilia #PRM-LBJ LeBron James Patch Card (#10/10)",
    "2024-25 Panini Flawless Flawless Memorabilia #FM-LBJ Lebron James Game-Used Patch Card (#3/5)",
    "2020-21 Panini Flawless Dual Patch #DP-JTT Jayson Tatum Patch Card",
    "2025-26 Topps Flagship Real One Relics Red Rainbow #FRO-SC Stephen Curry Patch Card (#1/5)",
    "2025-26 Topps Flagship Real One Relics Gold Rainbow #FRO-SC Stephen Curry Relic Card (#16/50)",
    "2018-19 Panini National Treasures Rookie Triple Materials #RT-SGA Shai Gilgeous-Alexander Relic Rookie Card (#21/99)",
    "2015-16 Panini National Treasures Rookie Jumbo Materials #31 Nikola Jokic Relic Rookie Card (#36/99)",

    # Cade Cunningham (7 cards in pipeline) — niche demand, limited Goldin audience
    "2024-25 Panini Select Snake Skin Black Pulsar FOTL Prizm #224 Cade Cunningham (#1/1)",
    "2024-25 Panini Silhouette Veteran Season Ticket FOTL Red #VST-CAD Cade Cunningham Signed Card (#2/7)",
    "2024-25 Panini Prizm Signatures Snakeskin Prizm #SIG-CAD Cade Cunningham Signed Card (#15/15)",
    "2024-25 Panini Donruss Net Marvel Signatures #NMS-CCP Cade Cunningham Signed Card (#20/49)",
    "2024-25 Panini Flawless Focus Autographs #FFA-CP Cade Cunningham Signed Card (#25/25)",

    # Remaining Paolo cards
    "2024-25 Panini Prizm Black Signatures Silver Prizm #117 Paolo Banchero Signed Card",
    "2024-25 Panini Prizm Black Autograph Silver Prizm #117 Paolo Banchero Signed Card",

    # Legacy HOF at risk
    "2017-18 Panini Opulence Gold Records Signatures #GR-BRS Bill Russell Signed Card (#18/25)",
    "2017-18 Panini Flawless Signature Prime Materials Ruby #SM-DN Dirk Nowitzki Signed Patch Card (#08/15)",
    "2021-22 Panini Immaculate Collection Patch Autographs #PA-DNZ Dirk Nowitzki Signed Patch Card (#49/49)",

    # High cost + secondary set
    "2018-19 Panini Contenders Rookie Ticket Autographs Playoff Ticket #106 Shai Gilgeous-Alexander Signed Rookie Card (#63/65)",
    "2024-25 Panini Noir Spotlight Signatures Horizontal #SSH-JAM Ja Morant Signed Card (#12/99)",
    "2023 Panini The National VIP Gold Pandora Relic #21 Luka Doncic Relic Card (#02/10)",

    # Ausar Thompson (5 cards) — very limited star power
    "2023-24 Panini Immaculate Collection Immaculate Rookie Patches FOTL #IRP-ATP Ausar Thompson Signed Patch Rookie Card (#15/15)",
    "2023-24 Panini Noir Rookie Autographs #382 Ausar Thompson Signed Rookie Card (#83/99)",
    "2024-25 Panini Flawless Finishes Gold #FF-ATP Ausar Thompson Signed Card (#01/10)",
    "2024-25 Panini Immaculate Collection Patch Autographs Blue #PAU-AUS Ausar Thompson Signed Patch Card (#14/25)",

    # Yves Missi, Jalen Suggs — very soft market
    "2024-25 Panini Flawless Autographs Gold #FA-YMP Yves Missi Signed Rookie Card (#10/10)",
    "2021-22 Panini Prizm Draft Picks Sensational Signatures Nebula Circles Prizm #SS-JSU Jalen Suggs Signed Rookie Card (#4/5)",
]


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
#
# PIPELINE TOTALS:
#   411 cards total in Goldin pipeline
#     31 PULL   (~$17,720 cost basis — est. -$5,000 to -$7,000 loss if sold)
#    106 WATCH  (~$108,405 cost basis — risky, needs monitoring)
#    274 KEEP   (~$314,746 cost basis — should be fine at Goldin)
#
# TOP PULL PRIORITIES (by estimated loss):
#   1. ALL 13 Giannis cards   — $7,976 at risk, est. -$3,000+ loss
#   2. Paolo Banchero 3 cards — $3,709 at risk, trending down
#   3. D-Wade Exquisite       — $1,556 at risk, legacy at high cost
#   4. Chet Holmgren 1/1      — $1,005 at risk, player cooling off
#   5. Austin Reaves Cracked  — $686 at risk, niche role player
#
# WHAT TO DO WITH PULLED CARDS:
#   - eBay auction or Buy It Now — you paid eBay prices, sell eBay prices
#   - Hold for player performance inflection (Giannis playoff run, etc.)
#   - Private sale / card shows — avoid the 22% Goldin tax
#
# GOLDIN WORKS BEST FOR:
#   - Rising stars: Wemby, Flagg, Roki Sasaki, VJ Edgecombe (if cost is right)
#   - Iconic grails: Jordan, Kobe, Messi, Mahomes
#   - 1/1 and ultra-low serial of blue-chip players
#   - Cards bought well below eBay market (your margin IS Goldin's premium)
#
# GOLDIN DOES NOT WORK FOR:
#   - Cards bought at full eBay retail
#   - Giannis anything (oversaturated seller market)
#   - Cooling players (Chet, Paolo, Cade secondary)
#   - Legacy HOF non-flagship autos (Ray Allen, Gilbert Arenas, etc.)
#   - Relic-only cards without auto (bidders want ink)
#   - Raw/ungraded cards over $500 (Goldin bidders discount for no slab)
#
# NOTE: eBay cost matching is automated and may be imprecise for players
# with many purchases (LeBron, Curry, etc.). Verify costs manually for
# high-value cards before making pull decisions.
