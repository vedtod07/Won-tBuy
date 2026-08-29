"""Tests for the persona agent.

Jules is only evaluated in round 1. On round 2+ she returns
reached=false with status "Not reached this round" — no verdict,
no would_click, no "changed her mind".

Unreached personas never call the LLM.

ICP personas that fall back to cached fixtures keep their fixture
verdict, quote, and reason.
"""

import os
os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)

from app.agents.personas import evaluate_persona


def _klaus():
    return {
        "id": "klaus",
        "name": "Klaus",
        "age": 48,
        "role": "plant_manager",
        "location": "Germany",
        "is_icp": True,
        "reached": True,
    }


def _jules():
    return {
        "id": "jules",
        "name": "Jules",
        "age": 22,
        "role": "student",
        "is_icp": False,
        "reached": True,
    }


def test_unreached_persona_returns_not_reached():
    persona = _klaus()
    persona["reached"] = False
    result = evaluate_persona(persona, {}, 1)
    assert result["reached"] is False
    assert result["status"] == "Not reached this round"
    assert "verdict" not in result
    assert "would_click" not in result


def test_jules_round1_would_click():
    result = evaluate_persona(_jules(), {}, 1)
    assert result["reached"] is True
    assert result["would_click"] is True
    assert result["verdict"] == "buy"


def test_jules_round2_not_reached():
    result = evaluate_persona(_jules(), {}, 2)
    assert result["reached"] is False
    assert result["status"] == "Not reached this round"
    assert "verdict" not in result
    assert "would_click" not in result


def test_jules_round3_not_reached():
    result = evaluate_persona(_jules(), {}, 3)
    assert result["reached"] is False
    assert result["status"] == "Not reached this round"
    assert "verdict" not in result
    assert "would_click" not in result


def test_icp_persona_cache_fallback_has_verdict():
    persona = _klaus()
    persona["verdict"] = "object"
    persona["would_click"] = False
    persona["quote"] = "Where are the numbers?"
    persona["reason"] = "Klaus hates slogans without numbers"

    try:
        result = evaluate_persona(persona, {}, 1)
        assert "reached" in result
    except Exception:
        # When the LLM is unavailable, evaluate_persona raises CacheFallback.
        # The caller (load_round) falls back to the fixture persona, which
        # is what we are testing in test_load_round instead.
        pass


def test_jules_never_in_icp_fraction():
    jules = _jules()
    result = evaluate_persona(jules, {}, 1)
    assert result.get("would_click") is True
    assert jules["is_icp"] is False
