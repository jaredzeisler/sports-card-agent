"""Build eBay-ready listing data from a Card record.

Generates titles, descriptions, item specifics (aspects), and condition
info optimized for sports card selling on eBay.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.card import Card

# eBay title limit
MAX_TITLE_LEN = 80

# Grading company display names
GRADING_DISPLAY = {
    "PSA": "PSA",
    "BGS": "BGS Beckett",
    "SGC": "SGC",
    "CGC": "CGC",
}

# eBay condition IDs for trading cards
# See: https://developer.ebay.com/devzone/finding/callref/Enums/conditionIdList.html
CONDITION_MAP = {
    "graded": "4000",       # Ungraded - Sports Trading Cards (eBay uses this for graded too)
    "ungraded_nm": "4000",
    "ungraded_ex": "5000",
    "ungraded_vg": "6000",
}


def build_listing_title(card: Card) -> str:
    """Build an optimized eBay listing title (max 80 chars).

    Format: YEAR BRAND SET PLAYER VARIATION GRADE #NUMBER
    Prioritizes searchability — most important keywords first.
    """
    parts = []

    if card.year:
        parts.append(str(card.year))

    if card.brand:
        parts.append(card.brand)

    if card.set_name and card.set_name != card.brand:
        parts.append(card.set_name)

    parts.append(card.player)

    if card.variation:
        parts.append(card.variation)

    if card.graded and card.grade is not None:
        company = card.grading_company or "PSA"
        grade_str = str(int(card.grade)) if card.grade == int(card.grade) else str(card.grade)
        parts.append(f"{company} {grade_str}")

    if card.card_number:
        num = card.card_number
        if not num.startswith("#"):
            num = f"#{num}"
        parts.append(num)

    title = " ".join(parts)

    # Truncate to 80 chars if needed, cutting from the end
    if len(title) > MAX_TITLE_LEN:
        title = title[:MAX_TITLE_LEN - 1].rsplit(" ", 1)[0]

    return title


def build_item_aspects(card: Card) -> dict[str, list[str]]:
    """Build eBay item specifics (aspects) from card data.

    These are the structured attributes buyers filter by on eBay.
    """
    aspects: dict[str, list[str]] = {}

    aspects["Sport"] = [card.sport.title() if card.sport else "Basketball"]

    if card.player:
        aspects["Player/Athlete"] = [card.player]

    if card.year:
        aspects["Season"] = [str(card.year)]
        aspects["Year Manufactured"] = [str(card.year)]

    if card.brand:
        aspects["Manufacturer"] = [card.brand]

    if card.set_name:
        aspects["Set"] = [card.set_name]

    if card.card_number:
        aspects["Card Number"] = [card.card_number.lstrip("#")]

    if card.variation:
        aspects["Parallel/Variety"] = [card.variation]

    if card.graded and card.grade is not None:
        company = card.grading_company or "PSA"
        aspects["Professional Grader"] = [GRADING_DISPLAY.get(company, company)]
        grade_str = str(int(card.grade)) if card.grade == int(card.grade) else str(card.grade)
        aspects["Grade"] = [grade_str]

    if card.cert_number:
        aspects["Certification Number"] = [card.cert_number]

    aspects["Card Condition"] = ["Graded" if card.graded else "Ungraded"]
    aspects["Type"] = ["Sports Trading Card"]
    aspects["Country/Region of Manufacture"] = ["United States"]

    return aspects


def build_description(card: Card, price: float | None = None) -> str:
    """Build an HTML description for the listing."""
    company = card.grading_company or "PSA"
    grade_str = ""
    if card.graded and card.grade is not None:
        grade_int = int(card.grade) if card.grade == int(card.grade) else card.grade
        grade_str = f"{company} {grade_int}"

    lines = []
    lines.append(f"<b>{build_listing_title(card)}</b>")
    lines.append("<br><br>")

    if grade_str:
        lines.append(f"<b>Grade:</b> {grade_str}<br>")
    if card.cert_number:
        lines.append(f"<b>Cert #:</b> {card.cert_number}<br>")
    if card.year:
        lines.append(f"<b>Year:</b> {card.year}<br>")
    if card.brand:
        lines.append(f"<b>Brand:</b> {card.brand}<br>")
    if card.set_name:
        lines.append(f"<b>Set:</b> {card.set_name}<br>")
    if card.variation:
        lines.append(f"<b>Variation:</b> {card.variation}<br>")
    if card.card_number:
        lines.append(f"<b>Card #:</b> {card.card_number}<br>")

    lines.append("<br>")
    lines.append("Ships securely in a bubble mailer with tracking. ")
    lines.append("Card will be well-protected for safe delivery.")
    lines.append("<br><br>")
    lines.append("Please check photos carefully. What you see is what you get.")

    return "".join(lines)


def build_card_listing(
    card: Card,
    image_urls: list[str] | None = None,
) -> dict:
    """Build complete eBay listing data from a Card record.

    Returns a dict ready to pass to EbayClient.create_listing():
        title, description, condition, condition_description, image_urls, aspects
    """
    title = build_listing_title(card)
    description = build_description(card)
    aspects = build_item_aspects(card)

    # eBay condition setup
    # Graded cards: conditionId 2750 with descriptors for grader + grade
    # Ungraded cards: conditionId 4000 (Near Mint or Better)
    condition_description = ""
    condition_descriptors = []

    if card.graded and card.grade is not None:
        condition = "2750"  # Graded condition ID
        company = card.grading_company or "PSA"
        grade_val = int(card.grade) if card.grade == int(card.grade) else card.grade

        # Condition descriptor for Professional Grader (ID 27501)
        condition_descriptors.append({
            "name": "27501",
            "values": [company],
        })
        # Condition descriptor for Grade (ID 27502)
        condition_descriptors.append({
            "name": "27502",
            "values": [str(grade_val)],
        })
        condition_description = (
            f"Professionally graded by {company}. Grade: {grade_val}. "
            f"Card is in a sealed {company} holder."
        )
        if card.cert_number:
            condition_description += f" Cert #{card.cert_number}"
    else:
        condition = "4000"  # Ungraded — Near Mint or Better
        condition_descriptors.append({
            "name": "400010",  # Near Mint or Better
            "values": ["Near Mint or Better"],
        })

    return {
        "title": title,
        "description": description,
        "condition": condition,
        "condition_description": condition_description,
        "condition_descriptors": condition_descriptors,
        "image_urls": image_urls or [],
        "aspects": aspects,
    }


def calculate_list_price(
    card: Card,
    target_margin: float = 0.20,
    fee_rate: float = 0.1625,
) -> dict:
    """Calculate a recommended listing price based on cost basis and target margin.

    Returns: {
        list_price: recommended ask price,
        auto_accept: auto-accept threshold (slightly below list),
        auto_decline: auto-decline threshold (at cost basis),
        est_fees: estimated eBay fees,
        est_net: estimated net after fees,
        est_profit: estimated profit,
        cost_basis: purchase price,
    }
    """
    cost = card.purchase_price or 0

    # Price that yields target margin after fees
    # net = list_price * (1 - fee_rate)
    # profit = net - cost = target_margin * cost
    # list_price * (1 - fee_rate) = cost * (1 + target_margin)
    if cost > 0:
        list_price = cost * (1 + target_margin) / (1 - fee_rate)
    elif card.current_fmv:
        list_price = card.current_fmv
    else:
        list_price = 0

    list_price = round(list_price, 2)
    est_fees = round(list_price * fee_rate, 2)
    est_net = round(list_price - est_fees, 2)

    # Auto-accept at ~10% margin (minimum acceptable)
    if cost > 0:
        auto_accept = round(cost * 1.10 / (1 - fee_rate), 2)
    else:
        auto_accept = round(list_price * 0.90, 2)

    # Auto-decline below cost basis (would lose money)
    if cost > 0:
        auto_decline = round(cost / (1 - fee_rate), 2)
    else:
        auto_decline = round(list_price * 0.75, 2)

    return {
        "list_price": list_price,
        "auto_accept": auto_accept,
        "auto_decline": auto_decline,
        "est_fees": est_fees,
        "est_net": est_net,
        "est_profit": round(est_net - cost, 2),
        "cost_basis": cost,
    }
