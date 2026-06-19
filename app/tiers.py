from dataclasses import dataclass
from datetime import datetime, timedelta
import re


@dataclass
class TierDefinition:
    name: str
    label: str
    min_score: int
    min_active_days: int
    color: str
    benefits: list[str]


TIERS: list[TierDefinition] = [
    TierDefinition("bronze", "Bronze", 0, 0, "#CD7F32", ["Connect a device", "Track daily wellness score"]),
    TierDefinition("silver", "Silver", 50, 15, "#C0C0C0", ["₹100 cashback", "10% gym membership coupon"]),
    TierDefinition(
        "gold", "Gold", 70, 22, "#FFD700",
        ["₹300 cashback", "15% pharmacy coupon", "Free health checkup"],
    ),
    TierDefinition(
        "platinum", "Platinum", 85, 26, "#E5E4E2",
        ["₹500 cashback", "20% wellness store coupon", "Priority insurer wellness benefits"],
    ),
]


def tier_rank(tier: str) -> int:
    return next(i for i, t in enumerate(TIERS) if t.name == tier)


def resolve_tier(avg_score: int, active_days: int, current_tier: str = "bronze") -> TierDefinition:
    best = TIERS[0]
    for tier in TIERS:
        if avg_score >= tier.min_score and active_days >= tier.min_active_days:
            best = tier
    if tier_rank(best.name) >= tier_rank(current_tier):
        return best
    return TIERS[tier_rank(current_tier)]


def rewards_for_tier(tier: str) -> list[dict]:
    definition = next(t for t in TIERS if t.name == tier)
    rewards = []
    for benefit in definition.benefits:
        is_cashback = "cashback" in benefit
        match = re.search(r"₹(\d+)", benefit)
        rewards.append(
            {
                "type": "cashback" if is_cashback else "coupon",
                "title": benefit,
                "value": int(match.group(1)) if match else None,
                "tier_required": tier,
            }
        )
    return rewards
