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
    quotes = " ".join(row.get("quote") or "" for row in round_one["personas"]).lower()
    assert "operating system" not in quotes
    assert "kicksly" in quotes or "shoe" in quotes or "store" in quotes
    assert "two failures, same campaign" not in round_one["critic_summary"].lower()


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


def test_flowerio_audience_and_quotes_are_not_factory():
    briefing = interpret_brief(
        "Flowerio: floral gifts aimed at young adults aged 20-35 buying gifts. Starting from $25/mo.",
        use_cache=True,
    )
    roles = briefing["tight_targeting"]["roles"]
    assert "plant_manager" not in roles
    assert briefing["leak_role"] not in {"plant_manager", "operations_manager"}
    label = briefing["audience_label"].lower()
    assert "gift" in label or "young" in label or "adult" in label
    titles = " ".join(row["title"] for row in briefing["personas"]).lower()
    assert "plant manager" not in titles
    assert "gift" in titles or "adult" in titles or "young" in titles

    activate_custom_lab(briefing)
    round_one = load_round(1)
    quotes = " ".join(row.get("quote") or "" for row in round_one["personas"]).lower()
    assert "operating system" not in quotes
    assert "slogan with no numbers" not in quotes
    assert "flowerio" in quotes or "gift" in quotes or "floral" in quotes
    critic = round_one["critic_summary"].lower()
    assert "two failures, same campaign" not in critic
    leak = next(row for row in round_one["personas"] if row.get("is_icp") is False)
    assert leak["name"].lower() != "jules"
    assert "flowerio" in critic or leak["name"].lower() in critic or "gift" in critic


def test_llm_factory_leak_is_scrubbed_for_gifts():
    llm = {
        "reasoning": "I targeted young professionals and identified an industrial plant manager as a leak.",
        "company": "Flowerio",
        "product": "floral gifts for young adults",
        "price": "from $25/mo",
        "audience_label": "young adults aged 20-35 buying gifts",
        "tight_targeting": {
            "industries": ["gifting"],
            "roles": ["gift_buyer", "young_adult"],
            "regions": ["north_america"],
        },
        "leak_role": "plant_manager",
        "buyers": [
            {"name": "Maya Lin", "title": "Gift buyer · 28", "objection": "proof"},
            {"name": "Liam Vance", "title": "Young adult · gifting", "objection": "price"},
            {"name": "Chloe Bennett", "title": "Occasion shopper", "objection": "ranking"},
        ],
        "leak": {"name": "Harold Finch", "title": "industrial plant manager"},
    }
    briefing = assemble_briefing(
        "Flowerio: floral gifts aimed at young adults aged 20-35 buying gifts. Starting from $25/mo.",
        "from $25/mo",
        llm,
    )
    assert briefing["leak_role"] != "plant_manager"
    assert "plant" not in briefing["personas"][-1]["title"].lower()
    assert "plant manager" not in briefing["reasoning"].lower()
    activate_custom_lab(briefing)
    round_one = load_round(1)
    quotes = " ".join(row.get("quote") or "" for row in round_one["personas"]).lower()
    assert "operating system" not in quotes
    assert "flowerio" in quotes
    assert round_one["personas"][-1]["name"] == "Harold Finch"


def test_reachify_messy_brief_is_a_store_lab_not_a_dump():
    brief = (
        "Reachify:Marketing agency for stores to increase their reach and position customers"
        "...audience includes local stores offering various products"
        "...pricing ranges from 100 dollars to upto 5000 dollars depending on the reach and scale they want"
    )
    assert parse_price(brief) == "from $100"
    assert parse_price("aged 20-35 buying gifts. Starting from $25/mo.") == "from $25/mo"

    briefing = interpret_brief(brief, use_cache=True)
    assert briefing["company"] == "Reachify"
    assert ":" not in briefing["company"]
    assert briefing["price"] == "from $100"
    assert "/mo" not in briefing["price"]
    label = briefing["audience_label"].lower()
    assert "local store" in label
    assert "increase their reach" not in label
    roles = briefing["tight_targeting"]["roles"]
    assert "store_owner" in roles or "store_manager" in roles
    assert "plant_manager" not in roles
    headline = briefing["campaign"].ad.headline
    assert headline.startswith("The #1 Reachify")
    assert "Reachify:Marketing" not in headline
    assert "pricing ranges" not in briefing["campaign"].ad.body.lower()
    assert "..." not in briefing["campaign"].ad.body

    activate_custom_lab(briefing)
    round_one = load_round(1)
    quotes = " ".join(row.get("quote") or "" for row in round_one["personas"]).lower()
    assert "operating system" not in quotes
    assert "reachify" in quotes
    assert "reachify:marketing" not in round_one["campaign"]["company"].lower()
    critic = round_one["critic_summary"].lower()
    assert "two failures, same campaign" not in critic
    assert "local store" in critic or "reachify" in critic


def test_diverse_briefs_keep_their_own_voice():
    cases = [
        (
            "MokaLane: specialty coffee wholesale for neighbourhood cafe owners. 39 euros a month.",
            "from €39/mo",
            "mokalane",
            "cafe",
            "cafe owner",
        ),
        (
            "SkillNest: Excel crash course aimed at working professionals aged 28-45. 199 dollars one time.",
            "from $199",
            "skillnest",
            "professional",
            "professional",
        ),
        (
            "Ironroom: gym membership for busy parents in Austin. From $49/mo.",
            "from $49/mo",
            "ironroom",
            "parent",
            "parent",
        ),
        (
            "Clayfolk: handmade mugs for home cooks. 18 pounds each.",
            "from £18",
            "clayfolk",
            "cook",
            "cook",
        ),
        (
            "SmileArc teeth whitening for brides and grooms. Starting at 250 dollars.",
            "from $250",
            "smilearc",
            "bride",
            "bride",
        ),
        (
            "PTOBoard: leave tracker for HR managers at eighty-person companies. 12 pounds per moth.",
            "from £12/mo",
            "ptoboard",
            "hr",
            "hr manager",
        ),
        (
            "NightOwl: 1:1 maths tutoring for GCSE students. 25 pounds per hour.",
            "from £25",
            "nightowl",
            "student",
            "student",
        ),
    ]
    for brief, price, brand, marker, voice in cases:
        reset_lab()
        briefing = interpret_brief(brief, use_cache=True)
        activate_custom_lab(briefing)
        round_one = load_round(1)
        quotes = " ".join(row.get("quote") or "" for row in round_one["personas"]).lower()
        headline = briefing["campaign"].ad.headline.lower()
        body = briefing["campaign"].ad.body.lower()
        assert briefing["price"] == price, brief
        assert brand in briefing["company"].lower(), brief
        assert marker in briefing["audience_label"].lower(), briefing["audience_label"]
        assert voice in quotes, quotes
        assert "i'm a buyer" not in quotes
        assert "i'm a owner" not in quotes
        assert "operating system" not in quotes
        assert "more customers" not in body
        assert not headline.endswith("aged")
        assert not headline.endswith(" at")
        assert "two failures, same campaign" not in round_one["critic_summary"].lower()
        leak = next(row for row in round_one["personas"] if row.get("is_icp") is False)
        if marker == "student":
            assert leak.get("segment") != "student"


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


_TELL_NAMES = {"priya", "owen", "mina", "klaus", "anika", "mateo", "jules", "alex", "lena"}


def test_custom_shoppers_are_not_demo_tells():
    briefing = interpret_brief(
        "MokaLane: specialty coffee wholesale for neighbourhood cafe owners. 39 euros a month.",
        use_cache=True,
    )
    names = [row["name"].lower() for row in briefing["personas"]]
    assert not _TELL_NAMES.intersection(names)
    assert briefing["personas"][0]["id"] == "buyer_proof"
    assert briefing["personas"][-1]["id"] == "leak"
    assert briefing["personas"][-1]["is_icp"] is False
    assert "cafe" in briefing["personas"][0]["title"].lower()


def test_two_brands_mint_different_people():
    cafe = interpret_brief(
        "MokaLane: specialty coffee wholesale for neighbourhood cafe owners. 39 euros a month.",
        use_cache=True,
    )
    mugs = interpret_brief("Clayfolk: handmade mugs for home cooks. 18 pounds each.", use_cache=True)
    cafe_names = [row["name"] for row in cafe["personas"]]
    mug_names = [row["name"] for row in mugs["personas"]]
    assert cafe_names != mug_names
    assert len(set(cafe_names)) == 4
    assert "cafe" in cafe["personas"][0]["title"].lower()
    assert "cook" in mugs["personas"][0]["title"].lower()


def test_explicit_buyer_and_leak_clauses_mint_that_audience():
    briefing = interpret_brief(
        "Nimbus: log search. From $80/mo. Buyer: cloud ops managers at banks. Leak: solo indie hackers.",
        use_cache=True,
    )
    label = briefing["audience_label"].lower()
    assert "ops" in label or "cloud" in label or "bank" in label
    leak = briefing["personas"][-1]
    assert leak["is_icp"] is False
    blob = (leak["title"] + " " + str(leak.get("segment") or "")).lower()
    assert "indie" in blob or "hacker" in blob
    names = [row["name"].lower() for row in briefing["personas"]]
    assert not _TELL_NAMES.intersection(names)


def test_infer_cta_matches_the_offer():
    from app.agents.brief import infer_cta

    assert infer_cta("Clayfolk: handmade mugs for home cooks. 18 pounds each.") == "Shop now"
    assert infer_cta("Ironroom: gym membership for busy parents. From $49/mo.") == "Book a class"
    assert infer_cta("SkillNest: Excel crash course. 199 dollars one time.") == "Enroll"
    assert infer_cta("Brightside Dental: recall SMS for UK dentists. 49 pounds per month.") == "Book an appointment"
    assert infer_cta("Northline: downtime dashboard for plant managers. From €199/mo.") == "Book a demo"
    assert infer_cta("Reachify: marketing for local stores. From $100.") == "Book a demo"


def test_clayfolk_round_three_uses_shop_now():
    briefing = interpret_brief("Clayfolk: handmade mugs for home cooks. 18 pounds each.", use_cache=True)
    assert briefing["cta"] == "Shop now"
    activate_custom_lab(briefing)
    round_three = load_round(3)
    assert round_three["campaign"]["ad"]["cta"] == "Shop now"
    assert round_three["campaign"]["page"]["cta"] == "Shop now"
    proof = (round_three["campaign"]["page"].get("proof") or "").lower()
    assert "plants across europe" not in proof
    assert "Shop now" in round_three["chapter"]["people_sub"]
