"""Custom briefs must carry their own brand, price, and audience — never Northline defaults."""

import os

os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)

import pytest

from app.agents.brief import BriefError, assemble_briefing, interpret_brief, parse_price
from app.main import activate_custom_lab, load_round, reset_lab


@pytest.fixture(autouse=True)
def _reset():
    reset_lab()
    yield
    reset_lab()


def test_pounds_per_moth_is_not_199():
    assert parse_price("i wrote 49 pounds per moth") == "from £49/mo"
    briefing = interpret_brief(
        "Brightside Dental: recall SMS for UK dentists. 49 pounds per moth.",
        use_cache=True,
    )
    assert briefing["price"] == "from £49/mo"
    assert "199" not in briefing["price"]
    assert briefing["company"].lower().startswith("brightside")
    assert "plant_manager" not in briefing["tight_targeting"]["roles"]
    assert "dentist" in briefing["audience_label"].lower()


def test_missing_price_does_not_invent_199():
    with pytest.raises(BriefError, match="will not invent"):
        interpret_brief("Helix is a floor ops board for plant managers.", use_cache=True)


def test_shoe_store_brief_is_not_factory_audience():
    briefing = interpret_brief(
        "Kicksly: stock alerts for independent shoe stores. 29 pounds per month.",
        use_cache=True,
    )
    roles = briefing["tight_targeting"]["roles"]
    assert briefing["price"] == "from £29/mo"
    assert "plant_manager" not in roles
    assert "dentist" not in roles
    assert "shoe" in briefing["audience_label"].lower()
    titles = " ".join(row["title"] for row in briefing["personas"] if row.get("is_icp"))
    assert "shoe" in titles.lower() or "store" in titles.lower()

    activate_custom_lab(briefing)
    round_one = load_round(1)
    assert round_one["briefing"]["price"] == "from £29/mo"
    assert "shoe" in round_one["agent_turns"][0]["text"].lower()


def test_florist_and_law_briefs_take_for_clause():
    florist = interpret_brief(
        "BloomDesk: booking for independent florist shop owners in Manchester. 15 pounds per month.",
        use_cache=True,
    )
    assert "plant_manager" not in florist["tight_targeting"]["roles"]
    assert florist["price"] == "from £15/mo"
    assert "florist" in florist["audience_label"].lower()

    law = interpret_brief(
        "Counselly: intake desk for US law firm partners. From $79/mo.",
        use_cache=True,
    )
    assert law["price"] == "from $79/mo"
    assert law["company"].lower().startswith("counselly")
    assert "plant_manager" not in law["tight_targeting"]["roles"]
    assert "partner" in law["audience_label"].lower() or "law" in law["audience_label"].lower()


def test_llm_payload_sets_audience_not_a_keyword_pack():
    llm = {
        "reasoning": "I read ReefBox as stock alerts for pet-shop owners at from £22/mo, not factory software.",
        "company": "ReefBox",
        "product": "stock alerts for aquarium shops",
        "price": "from £22/mo",
        "audience_label": "independent pet-shop owners",
        "tight_targeting": {
            "industries": ["pet_retail"],
            "roles": ["pet_shop_owner", "store_manager"],
            "regions": ["united_kingdom"],
        },
        "leak_role": "hobbyist",
        "buyers": [
            {"name": "Sam", "title": "Pet shop owner · Bristol", "objection": "proof"},
            {"name": "Dee", "title": "Store manager · Leeds", "objection": "price"},
            {"name": "Pat", "title": "Buyer · Cardiff", "objection": "ranking"},
        ],
        "leak": {"name": "Kai", "title": "Reef hobbyist — no shop"},
    }
    briefing = assemble_briefing(
        "ReefBox: stock for independent pet shops. 22 pounds per month.",
        "from £22/mo",
        llm,
    )
    assert briefing["interpreted_by"] == "llm"
    assert briefing["tight_targeting"]["industries"] == ["pet_retail"]
    assert briefing["personas"][0]["name"] == "Sam"
    assert "pet shop owner" in briefing["personas"][0]["title"].lower()
    assert briefing["personas"][-1]["name"] == "Kai"
    assert "factory" not in briefing["reasoning"].lower() or "not factory" in briefing["reasoning"].lower()
    assert "pet-shop" in briefing["audience_label"]


def test_three_brands_keep_their_own_price_and_audience_words():
    cases = [
        (
            "Brightside Dental: recall SMS for UK dentists. 49 pounds per month.",
            "from £49/mo",
            "brightside",
            "dentist",
        ),
        (
            "Northline: downtime dashboard for plant managers. From €199/mo.",
            "from €199/mo",
            "northline",
            "plant",
        ),
        (
            "Helix: classroom tools for UK headteachers. 12 pounds per month.",
            "from £12/mo",
            "helix",
            "headteacher",
        ),
    ]
    seen_prices = set()
    seen_labels = set()
    for brief, price, brand, marker in cases:
        reset_lab()
        briefing = interpret_brief(brief, use_cache=True)
        activate_custom_lab(briefing)
        round_one = load_round(1)
        round_three = load_round(3)
        assert briefing["price"] == price
        assert round_three["campaign"]["page"]["price"] == price
        assert brand in round_one["campaign"]["company"].lower()
        assert marker in briefing["audience_label"].lower()
        assert round_one["agent_turns"][0]["role"] == "Brief"
        assert price in round_one["agent_turns"][0]["text"]
        seen_prices.add(price)
        seen_labels.add(briefing["audience_label"].lower())
    assert seen_prices == {"from £49/mo", "from €199/mo", "from £12/mo"}
    assert len(seen_labels) >= 2
