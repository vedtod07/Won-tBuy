"""Tools the lab agents call. The numbers live here, not in the model."""

from langchain_core.tools import tool

from app.impressions import sample_impressions, targeting_accuracy, wasted_spend
from app.models import Campaign, Targeting


@tool
def run_sampler(targeting: dict, leak_roles: list[str] | None = None) -> dict:
    """Simulate 80 paid impressions (seed 42). Return the in-target percentage.

    The model must not invent this percentage. Accuracy drops when a leak role is targeted.
    """
    parsed = Targeting.model_validate(targeting)
    leaks = set(leak_roles or ["student"])
    impressions = sample_impressions(parsed, leak_roles=leaks)
    accuracy = targeting_accuracy(impressions)
    waste = wasted_spend(impressions)
    return {
        "n": len(impressions),
        "seed": 42,
        "targeting_accuracy": accuracy,
        "impressions": impressions,
        "waste": waste,
    }


def shopper_is_reached(
    persona_id: str,
    targeting: dict,
    leak_ids: list[str] | None = None,
    leak_roles: list[str] | None = None,
) -> bool:
    """Leak shoppers are reached only when a leak role is targeted. Intended buyers stay in-target."""
    roles = [str(role) for role in targeting.get("roles", [])]
    leaks = leak_roles or ["student"]
    ids = leak_ids or ["jules", "leak"]
    if persona_id in ids:
        return any(role in roles for role in leaks)
    return True


def campaign_as_dict(campaign: Campaign) -> dict:
    return campaign.model_dump(mode="json")
