"""Campaign-fitness-v1 is the lab's own ship/iterate gate, not an industry CTR table."""

import os

os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)

from app.benchmark import GATES, SHIP_THRESHOLD, WEIGHTS, campaign_fitness
from app.main import load_round, reset_lab


def test_weights_and_threshold_are_explicit():
    assert WEIGHTS["audience_fit"] + WEIGHTS["buyer_response"] + WEIGHTS["campaign_readiness"] == 1.0
    assert SHIP_THRESHOLD == 80.0
    assert GATES["audience_fit"] == 80.0


def test_round_one_iterates_on_audience_and_copy():
    reset_lab()
    fitness = load_round(1)["benchmark"]
    assert fitness["version"] == "campaign-fitness-v1"
    assert fitness["decision"] == "iterate"
    assert "audience_fit" in fitness["failed_gates"]
    assert "campaign_readiness" in fitness["failed_gates"]


def test_round_two_audience_passes_buyers_still_fail():
    reset_lab()
    fitness = load_round(2)["benchmark"]
    assert fitness["decision"] == "iterate"
    assert "audience_fit" not in fitness["failed_gates"]
    assert "buyer_response" in fitness["failed_gates"]
    r1 = load_round(1)["benchmark"]["components"]["campaign_readiness"]["score"]
    assert fitness["components"]["campaign_readiness"]["score"] == r1


def test_round_three_ships():
    reset_lab()
    fitness = load_round(3)["benchmark"]
    assert fitness["passed"] is True
    assert fitness["decision"] == "ship"
    assert fitness["score"] >= SHIP_THRESHOLD
    assert fitness["failed_gates"] == []


def test_fitness_does_not_need_a_full_round():
    campaign = {
        "company": "Clayfolk",
        "targeting": {
            "industries": ["consumer"],
            "roles": ["home_cook"],
            "company_sizes": ["1-49"],
            "regions": ["europe"],
        },
        "ad": {"headline": "Mugs with a price", "body": "Handmade. from £18.", "cta": "Shop now"},
        "page": {
            "headline": "Clayfolk",
            "body": "Fired in Stoke",
            "bullets": ["Batch of 40"],
            "proof": "Fired in small batches in Stoke",
            "cta": "Shop now",
            "price": "from £18",
        },
    }
    personas = [
        {"is_icp": True, "reached": True, "would_click": True},
        {"is_icp": True, "reached": True, "would_click": True},
        {"is_icp": True, "reached": True, "would_click": True},
        {"is_icp": False, "reached": False},
    ]
    fitness = campaign_fitness(campaign, targeting_accuracy=85, personas=personas)
    assert fitness["passed"] is True
    assert fitness["decision"] == "ship"
