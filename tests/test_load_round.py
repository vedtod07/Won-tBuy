"""Tests for the full round-loading pipeline.

Verifies the integrated load_round function returns all required keys,
correct metrics per round, Jules behavior across rounds, and that
the agent feed is populated.
"""

import os
os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)

from app.main import load_round


def test_round_one_keys():
    data = load_round(1)
    assert "campaign" in data
    assert "personas" in data
    assert "impressions" in data
    assert "targeting_accuracy" in data
    assert "critic_summary" in data
    assert "agent_feed" in data


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


def test_critic_summary_present():
    assert load_round(1)["critic_summary"] is not None
    assert isinstance(load_round(1)["critic_summary"], str)


def test_impressions_count_is_80():
    assert len(load_round(1)["impressions"]) == 80
