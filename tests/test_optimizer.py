"""Tests for the optimizer agent.

Round 2 (tighten_targeting): targeting becomes manufacturing +
plant_manager/operations_manager + europe. Copy is frozen — ad and
page must be byte-for-byte identical to the input campaign.

Round 3 (optimize_copy via cached fallback): price must be
"from €199/mo", CTAs must be "Book a demo", and no unsourced "#1" or
"best in the world" claims may appear anywhere in the copy.
"""

import json
from pathlib import Path

from app.agents.optimizer import tighten_targeting, optimize_copy
from app.models import Campaign


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load_campaign(round_number: int) -> Campaign:
    with (FIXTURES / f"round_{round_number}.json").open(encoding="utf-8") as f:
        return Campaign.model_validate(json.load(f)["campaign"])


def test_tighten_targeting_narrows_enums():
    campaign = _load_campaign(1)
    result = tighten_targeting(campaign)

    industries = [i.value for i in result.targeting.industries]
    roles = [r.value for r in result.targeting.roles]
    regions = [r.value for r in result.targeting.regions]

    assert industries == ["manufacturing"]
    assert set(roles) == {"plant_manager", "operations_manager"}
    assert regions == ["europe"]


def test_tighten_targeting_freezes_copy():
    campaign = _load_campaign(1)
    result = tighten_targeting(campaign)

    assert result.ad == campaign.ad
    assert result.page == campaign.page


def test_optimize_copy_cache_fallback_fixes_price():
    import os
    os.environ["USE_CACHE"] = "1"
    os.environ.pop("LLM_API_KEY", None)

    round_two = _load_campaign(2)
    round_three = _load_campaign(3)
    result = optimize_copy(round_two, round_three)

    assert result.page.price == "from €199/mo"


def test_optimize_copy_cache_fallback_fixes_cta():
    import os
    os.environ["USE_CACHE"] = "1"
    os.environ.pop("LLM_API_KEY", None)

    round_two = _load_campaign(2)
    round_three = _load_campaign(3)
    result = optimize_copy(round_two, round_three)

    assert result.ad.cta == "Book a demo"
    assert result.page.cta == "Book a demo"


def test_optimize_copy_cache_fallback_removes_unsourced_claims():
    import os
    os.environ["USE_CACHE"] = "1"
    os.environ.pop("LLM_API_KEY", None)

    round_two = _load_campaign(2)
    round_three = _load_campaign(3)
    result = optimize_copy(round_two, round_three)

    copy = " ".join(
        [result.ad.headline, result.ad.body, result.page.headline, result.page.body]
        + list(result.page.bullets or [])
    ).lower()
    assert "#1" not in copy
    assert "best in the world" not in copy


def test_optimize_copy_cache_fallback_adds_proof():
    import os
    os.environ["USE_CACHE"] = "1"
    os.environ.pop("LLM_API_KEY", None)

    round_two = _load_campaign(2)
    round_three = _load_campaign(3)
    result = optimize_copy(round_two, round_three)

    assert result.page.proof is not None
    assert len(result.page.proof) > 0


def test_optimize_copy_cache_fallback_adds_bullets():
    import os
    os.environ["USE_CACHE"] = "1"
    os.environ.pop("LLM_API_KEY", None)

    round_two = _load_campaign(2)
    round_three = _load_campaign(3)
    result = optimize_copy(round_two, round_three)

    assert len(result.page.bullets) == 3


def test_optimize_copy_freezes_targeting():
    import os
    os.environ["USE_CACHE"] = "1"
    os.environ.pop("LLM_API_KEY", None)

    round_two = _load_campaign(2)
    round_three = _load_campaign(3)
    result = optimize_copy(round_two, round_three)

    assert result.targeting == round_two.targeting
