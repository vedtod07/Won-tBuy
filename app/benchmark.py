"""Transparent benchmark used to decide whether a campaign should ship.

This is a product decision model, not an external industry benchmark. The
weights and gates are deliberately explicit so they can later be calibrated
against imported post-launch outcomes.
"""

from app.models import Campaign


BENCHMARK_VERSION = "campaign-fitness-v1"
SHIP_THRESHOLD = 80.0
WEIGHTS = {
    "audience_fit": 0.40,
    "buyer_response": 0.35,
    "campaign_readiness": 0.25,
}
GATES = {
    "audience_fit": 80.0,
    "buyer_response": 66.7,
    "campaign_readiness": 75.0,
}


def campaign_fitness(
    campaign: Campaign | dict,
    targeting_accuracy: float,
    personas: list[dict] | None,
) -> dict:
    """Score one campaign on audience, buyer response, and copy readiness."""
    model = campaign if isinstance(campaign, Campaign) else Campaign.model_validate(campaign)
    audience = max(0.0, min(float(targeting_accuracy or 0), 100.0))
    buyers = [row for row in (personas or []) if row.get("is_icp") and row.get("reached")]
    clicks = sum(1 for row in buyers if row.get("would_click"))
    buyer_response = round(clicks / len(buyers) * 100, 1) if buyers else 0.0
    readiness, checks = _campaign_readiness(model)

    components = {
        "audience_fit": _component(audience, WEIGHTS["audience_fit"]),
        "buyer_response": _component(buyer_response, WEIGHTS["buyer_response"]),
        "campaign_readiness": _component(readiness, WEIGHTS["campaign_readiness"]),
    }
    score = round(sum(row["weighted_points"] for row in components.values()), 1)
    failed_gates = [
        key for key, minimum in GATES.items()
        if components[key]["score"] < minimum
    ]
    passed = score >= SHIP_THRESHOLD and not failed_gates
    return {
        "version": BENCHMARK_VERSION,
        "score": score,
        "threshold": SHIP_THRESHOLD,
        "passed": passed,
        "decision": "ship" if passed else "iterate",
        "components": components,
        "readiness_checks": checks,
        "failed_gates": failed_gates,
        "next_action": _next_action(failed_gates, checks),
        "method": (
            "40% audience fit + 35% reached-ICP buyer response + 25% campaign readiness; "
            "the composite must reach 80 and every minimum gate must pass."
        ),
    }


def _component(score: float, weight: float) -> dict:
    return {
        "score": round(score, 1),
        "weight": weight,
        "weighted_points": round(score * weight, 1),
    }


def _campaign_readiness(campaign: Campaign) -> tuple[float, dict]:
    text = " ".join(
        [
            campaign.ad.headline,
            campaign.ad.body,
            campaign.page.headline,
            campaign.page.body,
            *(campaign.page.bullets or []),
        ]
    ).lower()
    cta = (campaign.ad.cta or "").strip().lower()
    weak_ctas = {"", "learn more", "click here", "read more"}
    checks = {
        "price_present": bool((campaign.page.price or "").strip()),
        "actionable_cta": cta not in weak_ctas and campaign.page.cta == campaign.ad.cta,
        "proof_present": bool((campaign.page.proof or "").strip()),
        "no_unsupported_ranking": "#1" not in text and "best in the world" not in text,
    }
    passed = sum(1 for value in checks.values() if value)
    return round(passed / len(checks) * 100, 1), checks


def _next_action(failed_gates: list[str], checks: dict) -> str:
    if "audience_fit" in failed_gates:
        return "Tighten targeting before changing the message."
    if "buyer_response" in failed_gates:
        return "Revise the proposition against buyer objections, then retest."
    if "campaign_readiness" in failed_gates:
        missing = [key.replace("_", " ") for key, passed in checks.items() if not passed]
        return "Fix campaign readiness: " + ", ".join(missing) + "."
    return "All benchmark gates passed; the campaign is ready for a controlled live test."
