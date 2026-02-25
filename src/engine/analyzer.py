"""Deal analyzer that scores listings and recommends actions."""

from config.settings import get_settings
from src.engine.pricing import EBAY_SELLER_FEE_RATE


class DealAnalyzer:
    """Analyzes a potential card deal and returns a score + recommendation."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def analyze(
        self,
        listing_price: float,
        estimated_fmv: float,
        fmv_confidence: float = 50,
        trend: str = "stable",
        population: int = 0,
    ) -> dict:
        """Score a deal from 0–100 and recommend an action.

        Returns: score, action (buy/skip/hold), reasons list, profit estimate
        """
        if estimated_fmv <= 0 or listing_price <= 0:
            return {
                "score": 0,
                "action": "skip",
                "reasons": ["Insufficient pricing data"],
                "estimated_profit": 0,
                "profit_margin": 0,
            }

        # Calculate profit after fees
        sell_fees = estimated_fmv * EBAY_SELLER_FEE_RATE
        net_profit = estimated_fmv - sell_fees - listing_price
        margin = net_profit / listing_price if listing_price > 0 else 0

        score = 0.0
        reasons = []

        # Margin component (0-40 points)
        if margin >= 0.50:
            score += 40
            reasons.append(f"Excellent margin: {margin:.0%}")
        elif margin >= 0.30:
            score += 30
            reasons.append(f"Strong margin: {margin:.0%}")
        elif margin >= 0.15:
            score += 20
            reasons.append(f"Decent margin: {margin:.0%}")
        elif margin >= 0:
            score += 5
            reasons.append(f"Thin margin: {margin:.0%}")
        else:
            reasons.append(f"Negative margin: {margin:.0%}")

        # Confidence component (0-25 points)
        confidence_score = (fmv_confidence / 100) * 25
        score += confidence_score
        if fmv_confidence < 30:
            reasons.append("Low data confidence")

        # Trend component (0-20 points)
        if trend == "up":
            score += 20
            reasons.append("Price trending up")
        elif trend == "stable":
            score += 10
        elif trend == "down":
            score += 0
            reasons.append("Price trending down — risky")

        # Risk checks (0-15 points, or penalties)
        if listing_price > self.settings.max_single_card:
            score -= 15
            reasons.append(f"Exceeds max single card limit (${self.settings.max_single_card})")

        if margin < self.settings.min_profit_margin:
            score -= 10
            reasons.append(f"Below minimum margin threshold ({self.settings.min_profit_margin:.0%})")

        # Population rarity bonus
        if population > 0 and population < 50:
            score += 10
            reasons.append(f"Low population ({population}) — scarce")
        elif population >= 50:
            score += 5

        score = max(0, min(100, score))

        # Decision
        if score >= 65 and margin >= self.settings.min_profit_margin:
            action = "buy"
        elif score >= 40:
            action = "hold"
        else:
            action = "skip"

        return {
            "score": round(score, 1),
            "action": action,
            "reasons": reasons,
            "estimated_profit": round(net_profit, 2),
            "profit_margin": round(margin * 100, 1),
        }

    def should_sell(
        self,
        purchase_price: float,
        current_fmv: float,
        trend: str = "stable",
    ) -> dict:
        """Evaluate whether to sell a card currently in inventory."""
        sell_fees = current_fmv * EBAY_SELLER_FEE_RATE
        net_profit = current_fmv - sell_fees - purchase_price
        margin = net_profit / purchase_price if purchase_price > 0 else 0

        if margin >= 0.20 and trend != "up":
            action = "sell"
            reason = f"Profitable ({margin:.0%} margin) and not trending up — sell now"
        elif margin >= 0.30 and trend == "up":
            action = "sell"
            reason = f"Strong profit ({margin:.0%}) even though trending up — lock in gains"
        elif margin >= 0.15 and trend == "down":
            action = "sell"
            reason = f"Decent margin ({margin:.0%}) but trending down — sell before further decline"
        elif trend == "up" and margin > 0:
            action = "hold"
            reason = f"Price trending up — hold for more profit (current margin {margin:.0%})"
        elif margin < 0:
            action = "hold"
            reason = f"Currently at a loss ({margin:.0%}) — hold and wait for recovery"
        else:
            action = "hold"
            reason = f"Margin too thin ({margin:.0%}) — hold for better opportunity"

        return {
            "action": action,
            "reason": reason,
            "net_profit": round(net_profit, 2),
            "margin_pct": round(margin * 100, 1),
        }
