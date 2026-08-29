"""Tests for the full round-loading pipeline.

Verifies the integrated load_round function returns all required keys,
correct metrics per round, Jules behavior across rounds, and that
the agent feed is populated.
"""

import os
os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)

import pytest

from app.main import (
    activate_custom_lab,
    build_custom_campaign,
    extract_price,
    load_round,
    reset_lab,
)
from app.agents.brief import interpret_brief


@pytest.fixture(autouse=True)
def _reset_lab_state():
    reset_lab()
    yield
    reset_lab()


def test_round_one_keys():
    data = load_round(1)
    assert "campaign" in data
    assert "personas" in data
    assert "impressions" in data
    assert "targeting_accuracy" in data
    assert "critic_summary" in data
    assert "agent_feed" in data
    assert "agent_turns" in data
    assert "chapter" in data
    assert data["chapter"]["eyes"] == "Wrong eyes"
    assert data["chapter"]["words"] == "Wrong words"


def test_round_one_accuracy_is_40():
    assert load_round(1)["targeting_accuracy"] == 40.0


def test_round_two_accuracy_is_85():
    assert load_round(2)["targeting_accuracy"] == 85.0


def test_round_three_accuracy_stays_85():
    assert load_round(3)["targeting_accuracy"] == 85.0


def test_round_one_jules_would_click():
    personas = load_round(1)["personas"]
    jules = next(p for p in personas if p["id"] == "jules")
    assert jules["reached"] is True
    assert jules["would_click"] is True


def test_round_two_jules_not_reached():
    personas = load_round(2)["personas"]
    jules = next(p for p in personas if p["id"] == "jules")
    assert jules["reached"] is False
    assert jules["status"] == "Not reached this round"
    assert "would_click" not in jules


def test_round_three_jules_not_reached():
    personas = load_round(3)["personas"]
    jules = next(p for p in personas if p["id"] == "jules")
    assert jules["reached"] is False
    assert jules["status"] == "Not reached this round"
    assert "would_click" not in jules


def test_round_one_icp_purchase_rate_zero():
    personas = load_round(1)["personas"]
    icp_reached = [p for p in personas if p.get("is_icp") and p.get("reached")]
    icp_clicked = [p for p in icp_reached if p.get("would_click")]
    assert len(icp_clicked) == 0


def test_round_three_icp_purchase_rate_three():
    personas = load_round(3)["personas"]
    icp_reached = [p for p in personas if p.get("is_icp") and p.get("reached")]
    icp_clicked = [p for p in icp_reached if p.get("would_click")]
    assert len(icp_clicked) == 3


def test_round_two_copy_identical_to_round_one():
    r1 = load_round(1)["campaign"]
    r2 = load_round(2)["campaign"]
    assert r1["ad"] == r2["ad"]
    assert r1["page"] == r2["page"]


def test_round_three_copy_differs_from_round_two():
    r2 = load_round(2)["campaign"]
    r3 = load_round(3)["campaign"]
    assert r3["ad"].get("cta") == "Book a demo"
    assert r3["page"].get("cta") == "Book a demo"
    assert r3["page"].get("price") == "from €199/mo"


def test_round_three_targeting_matches_round_two():
    r2 = load_round(2)["campaign"]
    r3 = load_round(3)["campaign"]
    assert r2["targeting"] == r3["targeting"]


def test_agent_feed_is_populated():
    feed = load_round(1)["agent_feed"]
    assert len(feed) > 0
    assert any("Sampler" in line for line in feed)
    assert any("Persona" in line for line in feed)


def test_agent_turns_follow_graph_order():
    turns = load_round(1)["agent_turns"]
    roles = [row["role"] for row in turns]
    assert roles[0] == "Optimizer"
    assert "Sampler" in roles
    assert roles.count("Persona") == 4
    assert roles[-1] == "Critic"


def test_critic_summary_present():
    assert load_round(1)["critic_summary"] is not None
    assert isinstance(load_round(1)["critic_summary"], str)


def test_impressions_count_is_80():
    assert len(load_round(1)["impressions"]) == 80


def test_round_two_chapter_is_right_eyes_wrong_words():
    data = load_round(2)
    assert data["chapter"]["eyes"] == "Right eyes"
    assert data["chapter"]["words"] == "Wrong words"
    assert data["icp_purchase_rate"] == "0/3"


def test_round_three_chapter_is_right_eyes_right_words():
    data = load_round(3)
    assert data["chapter"]["eyes"] == "Right eyes"
    assert data["chapter"]["words"] == "Right words"
    assert data["icp_purchase_rate"] == "3/3"


def test_extract_price_from_brief():
    assert extract_price("Acme from $49/mo for plants") == "from $49/mo"
    assert extract_price("From €199/mo. Proof: 40 plants.") == "from €199/mo"
    assert extract_price("49 pounds per moth") == "from £49/mo"
    assert extract_price("49 pounds per month") == "from £49/mo"
    assert extract_price("no number here") is None


def test_custom_round_one_is_leaky():
    campaign = build_custom_campaign("Acme: downtime board for plant managers. From $49/mo.")
    assert "student" in campaign.targeting.roles
    assert campaign.page.price is None
    assert "#1" in campaign.ad.headline
    assert campaign.ad.cta == "Learn more"


def test_custom_three_steps_match_northline_story():
    brief = "Acme: downtime board for plant managers. From $49/mo."
    briefing = interpret_brief(brief, use_cache=True)
    activate_custom_lab(briefing)

    round_one = load_round(1)
    assert round_one["lab"] == "custom"
    assert round_one["chapter"]["eyes"] == "Wrong eyes"
    assert round_one["chapter"]["words"] == "Wrong words"
    leak = next(row for row in round_one["personas"] if row.get("is_icp") is False)
    assert leak["reached"] is True
    assert leak["would_click"] is True
    assert round_one["icp_purchase_rate"] == "0/3"
    assert round_one["agent_turns"][0]["role"] == "Brief"
    assert round_one["briefing"]["price"] == "from $49/mo"

    round_two = load_round(2)
    assert round_two["chapter"]["eyes"] == "Right eyes"
    assert round_two["chapter"]["words"] == "Wrong words"
    leak_two = next(row for row in round_two["personas"] if row.get("is_icp") is False)
    assert leak_two["reached"] is False
    assert round_two["campaign"]["ad"] == round_one["campaign"]["ad"]
    assert round_two["campaign"]["page"]["price"] is None
    assert round_two["icp_purchase_rate"] == "0/3"

    round_three = load_round(3)
    assert round_three["chapter"]["words"] == "Right words"
    assert round_three["campaign"]["page"]["price"] == "from $49/mo"
    assert round_three["campaign"]["ad"]["cta"] == "Book a demo"
    assert round_three["icp_purchase_rate"] == "3/3"
    copy = " ".join(
        [
            round_three["campaign"]["ad"]["headline"],
            round_three["campaign"]["ad"]["body"],
            round_three["campaign"]["page"]["headline"],
            round_three["campaign"]["page"]["body"],
        ]
    ).lower()
    assert "#1" not in copy
