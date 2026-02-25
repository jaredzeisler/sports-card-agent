"""Flag cards whose FMV looks wrong (likely bad API match).

Common causes:
  - SportsCardsPro matched a base card instead of a parallel/variation
  - Card has no FMV data at all despite a non-trivial purchase price
  - Non-card items (grading fees, supplies) slipped into the collection
  - FMV is suspiciously high relative to purchase price (wrong product)
"""

from src.models.database import get_session, init_db
from src.models.card import Card, CardStatus


# ── Thresholds ──────────────────────────────────────────────────────

# FMV is less than this fraction of purchase price → suspect
LOW_FMV_THRESHOLD = 0.30  # FMV < 30% of paid

# FMV exceeds purchase price by this multiple → suspect
HIGH_FMV_THRESHOLD = 5.0  # FMV > 5× paid

# Only flag cards above this purchase price (ignore cheap base cards)
MIN_PAID_TO_FLAG = 25.0


def flag_mismatches(
    min_paid: float = MIN_PAID_TO_FLAG,
    low_threshold: float = LOW_FMV_THRESHOLD,
    high_threshold: float = HIGH_FMV_THRESHOLD,
) -> dict:
    """Scan all cards and return categorised mismatch lists.

    Returns dict with keys:
      suspect_low   – FMV suspiciously low vs purchase price
      suspect_high  – FMV suspiciously high vs purchase price
      missing_fmv   – No FMV at all despite purchase price
      non_cards     – Rows that aren't actual cards (grading fees etc.)
      summary       – { total_cards, flagged, clean }
    """
    init_db()
    session = get_session()

    suspect_low = []
    suspect_high = []
    missing_fmv = []
    non_cards = []

    try:
        cards = (
            session.query(Card)
            .filter(Card.status == CardStatus.IN_COLLECTION)
            .order_by(Card.id)
            .all()
        )

        total = len(cards)

        for card in cards:
            paid = card.purchase_price or 0
            fmv = card.current_fmv or 0
            has_variation = bool(card.variation)

            row = {
                "id": card.id,
                "player": card.player,
                "year": card.year,
                "brand": card.brand,
                "set_name": card.set_name,
                "variation": card.variation,
                "grade": card.grade,
                "graded": card.graded,
                "purchase_price": paid,
                "current_fmv": fmv,
                "diff_pct": ((fmv - paid) / paid * 100) if paid > 0 else 0,
                "has_variation": has_variation,
            }

            # Non-card items (grading fees, supplies, etc.)
            non_card_keywords = [
                "psa grading", "grading", "supplies", "shipping",
                "case", "sleeve", "top loader", "penny",
            ]
            if any(kw in card.player.lower() for kw in non_card_keywords):
                row["reason"] = "Non-card item in collection"
                non_cards.append(row)
                continue

            if card.notes and "[NOT A CARD]" in card.notes:
                row["reason"] = "Tagged as not a card"
                non_cards.append(row)
                continue

            if paid < min_paid:
                continue

            # Missing FMV entirely
            if fmv == 0:
                row["reason"] = "No FMV data"
                missing_fmv.append(row)
                continue

            ratio = fmv / paid if paid > 0 else 0

            # FMV suspiciously LOW
            if ratio < low_threshold:
                reasons = []
                if has_variation:
                    reasons.append(
                        f"Has '{card.variation}' variation — API likely matched base card"
                    )
                else:
                    reasons.append(
                        f"FMV is {row['diff_pct']:+.0f}% vs purchase price"
                    )
                if paid >= 500:
                    reasons.append(f"High-value card (paid ${paid:.2f})")
                row["reason"] = "; ".join(reasons)
                suspect_low.append(row)
                continue

            # FMV suspiciously HIGH
            if ratio > high_threshold:
                row["reason"] = (
                    f"FMV ${fmv:.2f} is {ratio:.1f}× purchase price ${paid:.2f}"
                )
                suspect_high.append(row)
                continue

        # Sort by dollar impact (largest losses first)
        suspect_low.sort(key=lambda r: r["purchase_price"] - r["current_fmv"], reverse=True)
        suspect_high.sort(key=lambda r: r["current_fmv"] - r["purchase_price"], reverse=True)
        missing_fmv.sort(key=lambda r: r["purchase_price"], reverse=True)

        flagged = len(suspect_low) + len(suspect_high) + len(missing_fmv) + len(non_cards)

    finally:
        session.close()

    return {
        "suspect_low": suspect_low,
        "suspect_high": suspect_high,
        "missing_fmv": missing_fmv,
        "non_cards": non_cards,
        "summary": {
            "total_cards": total,
            "flagged": flagged,
            "clean": total - flagged,
        },
    }
