"""Sale target finder — identifies cards in inventory worth selling."""

from datetime import datetime, timezone

from config.settings import get_settings
from src.api.cardladder import CardLadderClient
from src.engine.analyzer import DealAnalyzer
from src.engine.pricing import calculate_net_profit
from src.models.database import get_session
from src.models.card import Card, CardStatus


def find_sale_targets(min_profit_pct: float = 15.0) -> list[dict]:
    """Check all cards in inventory against current FMV and recommend sells.

    Args:
        min_profit_pct: Minimum profit percentage to include in results.

    Returns list of dicts with card info, FMV, profit, and recommendation.
    """
    settings = get_settings()
    cardladder = CardLadderClient(settings)
    analyzer = DealAnalyzer(settings)
    session = get_session()
    targets = []

    try:
        cards = (
            session.query(Card)
            .filter(Card.status == CardStatus.IN_COLLECTION)
            .all()
        )

        for card in cards:
            if not card.purchase_price or card.purchase_price <= 0:
                continue

            # Get current FMV
            cl_data = cardladder.get_fmv(
                player=card.player,
                year=card.year,
                brand=card.brand,
                set_name=card.set_name,
                grade=card.grade,
                sport=card.sport,
            )

            if not cl_data or cl_data["fmv"] <= 0:
                continue

            fmv = cl_data["fmv"]
            trend = cl_data.get("trend", "stable")

            # Update card's FMV in DB
            card.current_fmv = fmv
            card.fmv_updated_at = datetime.now(timezone.utc)

            # Calculate profit
            profit_data = calculate_net_profit(fmv, card.purchase_price)

            # Get sell recommendation
            sell_analysis = analyzer.should_sell(
                purchase_price=card.purchase_price,
                current_fmv=fmv,
                trend=trend,
            )

            if profit_data["margin_pct"] >= min_profit_pct or sell_analysis["action"] == "sell":
                targets.append({
                    "card_id": card.id,
                    "player": card.player,
                    "year": card.year,
                    "brand": card.brand,
                    "set_name": card.set_name,
                    "grade": card.grade,
                    "purchase_price": card.purchase_price,
                    "current_fmv": fmv,
                    "trend": trend,
                    "net_profit": profit_data["net"],
                    "fees": profit_data["fees"],
                    "margin_pct": profit_data["margin_pct"],
                    "action": sell_analysis["action"],
                    "reason": sell_analysis["reason"],
                })

        session.commit()
    finally:
        session.close()

    # Sort by margin descending
    targets.sort(key=lambda t: t["margin_pct"], reverse=True)
    return targets
