"""Tests for the code-only impression sampler.

Verifies: seed determinism, row count, p_icp ranges for broad vs tight
targeting, and that in-ICP rows only carry roles/industries/regions
that the ICP sampler is allowed to pick.
"""

from app.impressions import sample_impressions, targeting_accuracy, wasted_spend
from app.models import (
    Campaign,
    Creative,
    Industry,
    LandingPage,
    Region,
    Role,
    Targeting,
    CompanySize,
)


def _broad_campaign() -> Campaign:
    return Campaign(
        company="Northline",
        targeting=Targeting(
            industries=[Industry.MANUFACTURING, Industry.TECHNOLOGY, Industry.EDUCATION],
            roles=[Role.PLANT_MANAGER, Role.OPERATIONS_MANAGER, Role.ENGINEER, Role.STUDENT],
            company_sizes=[CompanySize.SMALL, CompanySize.MEDIUM, CompanySize.LARGE],
            regions=[Region.EUROPE, Region.NORTH_AMERICA, Region.LATIN_AMERICA],
        ),
        ad=Creative(headline="#1 OS", body="Best in the world", cta="Learn more"),
        page=LandingPage(headline="Northline", cta="Learn more", price=None),
    )


def _tight_campaign() -> Campaign:
    return Campaign(
        company="Northline",
        targeting=Targeting(
            industries=[Industry.MANUFACTURING],
            roles=[Role.PLANT_MANAGER, Role.OPERATIONS_MANAGER],
            company_sizes=[CompanySize.SMALL, CompanySize.MEDIUM, CompanySize.LARGE],
            regions=[Region.EUROPE],
        ),
        ad=Creative(headline="#1 OS", body="Best in the world", cta="Learn more"),
        page=LandingPage(headline="Northline", cta="Learn more", price=None),
    )


def test_sampler_produces_80_rows():
    impressions = sample_impressions(_broad_campaign().targeting)
    assert len(impressions) == 80


def test_sampler_is_deterministic():
    targeting = _broad_campaign().targeting
    first = sample_impressions(targeting)
    second = sample_impressions(targeting)
    assert first == second


def test_broad_accuracy_is_about_40_percent():
    impressions = sample_impressions(_broad_campaign().targeting)
    accuracy = targeting_accuracy(impressions)
    assert accuracy == 40.0


def test_tight_accuracy_is_about_85_percent():
    impressions = sample_impressions(_tight_campaign().targeting)
    accuracy = targeting_accuracy(impressions)
    assert accuracy == 85.0


def test_in_icp_rows_have_valid_roles():
    impressions = sample_impressions(_tight_campaign().targeting)
    for row in impressions:
        if row["in_icp"]:
            assert row["role"] in {"plant_manager", "operations_manager"}
            assert row["industry"] == "manufacturing"
            assert row["region"] == "europe"


def test_empty_impressions_returns_zero():
    assert targeting_accuracy([]) == 0.0


def test_wasted_spend_broad_is_4_80():
    impressions = sample_impressions(_broad_campaign().targeting)
    waste = wasted_spend(impressions)
    assert waste["impressions"] == 80
    assert waste["on_icp"] == 32
    assert waste["off_icp"] == 48
    assert waste["wasted_spend"] == 4.8
    assert waste["total_spend"] == 8.0
    assert waste["waste_share"] == 60.0


def test_wasted_spend_tight_is_1_20():
    impressions = sample_impressions(_tight_campaign().targeting)
    waste = wasted_spend(impressions)
    assert waste["on_icp"] == 68
    assert waste["off_icp"] == 12
    assert waste["wasted_spend"] == 1.2
    assert waste["waste_share"] == 15.0


def test_every_row_has_required_fields():
    impressions = sample_impressions(_broad_campaign().targeting)
    for row in impressions:
        assert {"id", "industry", "role", "company_size", "region", "in_icp"} <= set(row)


def test_apply_economics_uses_user_spend():
    from app.impressions import apply_economics, wasted_spend

    waste = wasted_spend(sample_impressions(_broad_campaign().targeting))
    scaled = apply_economics(waste, {"spend": 1000})
    assert scaled["total_spend"] == 1000
    assert scaled["wasted_spend"] == 600.0
    assert scaled["source"] == "user_spend"


def test_parse_campaign_economics_from_csv():
    from app.impressions import parse_campaign_economics

    data = parse_campaign_economics(csv_text="spend,impressions\n400,2000\n600,2000")
    assert data["spend"] == 1000
    assert data["impressions"] == 4000
    assert data["cost_per_impression"] == 0.25


def test_inspect_campaign_csv_maps_and_ignores_extra_columns():
    from app.impressions import inspect_campaign_csv

    report = inspect_campaign_csv(
        "campaign,spend,impressions,clicks\nQ2,1200,8000,40\n"
    )
    assert report["ok"] is True
    assert report["can_apply"] is True
    assert report["mapped"]["spend"] == "spend"
    assert report["mapped"]["impressions"] == "impressions"
    assert "clicks" in report["ignored"]
    assert report["totals"]["spend"] == 1200
    assert report["totals"]["impressions"] == 8000
    assert report["preview"][0]["campaign"] == "Q2"


def test_inspect_campaign_csv_rejects_empty_and_wrong_headers():
    from app.impressions import inspect_campaign_csv

    empty = inspect_campaign_csv("  ")
    assert empty["ok"] is False
    assert "empty" in empty["error"].lower()
    bad = inspect_campaign_csv("foo,bar\n1,2")
    assert bad["ok"] is False
    assert "spend" in bad["error"].lower() or "cpc" in bad["error"].lower()


def test_demo_csv_rescales_waste_like_pasted_numbers():
    from pathlib import Path

    from app.impressions import inspect_campaign_csv, parse_campaign_economics
    from app.main import get_lab, load_round, reset_lab

    csv_path = Path(__file__).resolve().parent.parent / "app" / "static" / "demo" / "last-campaign.csv"
    text = csv_path.read_text(encoding="utf-8")
    report = inspect_campaign_csv(text)
    assert report["ok"] is True
    assert report["totals"]["spend"] == 1200
    assert report["totals"]["impressions"] == 8000
    reset_lab()
    try:
        get_lab()["economics"] = parse_campaign_economics(csv_text=text)
        data = load_round(1)
        assert data["waste"]["off_icp"] == 48
        assert data["waste"]["impressions"] == 80
        assert data["waste"]["wasted_spend"] == 720.0
        assert data["waste"]["source"] == "user_spend"
    finally:
        reset_lab()


def test_pasted_spend_rescales_round_one_waste_not_the_mix():
    from app.impressions import parse_campaign_economics
    from app.main import get_lab, load_round, reset_lab

    reset_lab()
    try:
        get_lab()["economics"] = parse_campaign_economics(spend=1200, impressions=8000)
        data = load_round(1)
        assert data["waste"]["off_icp"] == 48
        assert data["waste"]["impressions"] == 80
        assert data["waste"]["wasted_spend"] == 720.0
        assert data["waste"]["total_spend"] == 1200
        assert data["waste"]["source"] == "user_spend"
    finally:
        reset_lab()


def test_interpret_campaign_csv_offline_keeps_code_totals():
    from app.agents.csv_read import interpret_campaign_csv

    report = interpret_campaign_csv("spend,impressions,clicks\n400,2000,9\n600,2000,11", use_cache=True)
    assert report["ok"] is True
    assert report["interpreted_by"] == "offline"
    assert report["totals"]["spend"] == 1000
    assert report["totals"]["impressions"] == 4000
    assert "clicks" in report["ignored"]
    assert report["live_or_cache"] == "cache"


def test_interpret_campaign_csv_calls_llm_when_live(monkeypatch):
    from app.agents import csv_read

    called = {}

    def fake_chat(system, user, use_cache=False):
        called["system"] = system
        called["user"] = user
        called["use_cache"] = use_cache
        return {
            "reasoning": "I read a LinkedIn export for Northline Shiftboard. Spend is already summed in the file.",
            "mapped": {"spend": "spend", "impressions": "impressions", "cpc": "cpc"},
            "campaign": "Northline Shiftboard",
            "platform": "linkedin",
            "audience_guess": "plant managers",
            "leak_guess": "students",
        }

    monkeypatch.setattr(csv_read, "live_key_present", lambda: True)
    monkeypatch.setattr(csv_read, "use_cache_requested", lambda _use_cache=False: False)
    monkeypatch.setattr(csv_read, "chat_json", fake_chat)
    monkeypatch.setattr(
        csv_read,
        "last_call_meta",
        lambda: {"model": "gemini-3.6-flash", "live_or_cache": "live", "latency_ms": 18},
    )
    csv_text = "campaign_name,spend,impressions,cpc\nNorthline Shiftboard | LinkedIn,1200,8000,0.15\n"
    report = csv_read.interpret_campaign_csv(csv_text, use_cache=False)
    assert called["use_cache"] is False
    assert "Northline Shiftboard" in called["user"]
    assert "Never invent" in called["system"]
    assert report["interpreted_by"] == "llm"
    assert report["live_or_cache"] == "live"
    assert report["totals"]["spend"] == 1200
    assert report["totals"]["impressions"] == 8000
    assert "Shiftboard" in report["reasoning"]
    assert report["read"]["platform"] == "linkedin"


def test_llm_cannot_replace_csv_totals(monkeypatch):
    from app.agents import csv_read

    def fake_chat(system, user, use_cache=False):
        return {
            "reasoning": "I invent spend 9.",
            "mapped": {"spend": "spend", "impressions": "impressions", "cpc": None},
            "campaign": None,
            "platform": "unknown",
            "audience_guess": None,
            "leak_guess": None,
            "spend": 9,
            "impressions": 9,
        }

    monkeypatch.setattr(csv_read, "live_key_present", lambda: True)
    monkeypatch.setattr(csv_read, "use_cache_requested", lambda _use_cache=False: False)
    monkeypatch.setattr(csv_read, "chat_json", fake_chat)
    monkeypatch.setattr(
        csv_read,
        "last_call_meta",
        lambda: {"model": "gemini-3.6-flash", "live_or_cache": "live", "latency_ms": 1},
    )
    report = csv_read.interpret_campaign_csv("spend,impressions\n1200,8000", use_cache=False)
    assert report["totals"]["spend"] == 1200
    assert report["totals"]["impressions"] == 8000


def test_llm_maps_messy_headers_then_code_sums(monkeypatch):
    from app.agents import csv_read

    def fake_chat(system, user, use_cache=False):
        return {
            "reasoning": "I mapped Amount spent and Impr.",
            "mapped": {"spend": "Amount spent (EUR)", "impressions": "Impr.", "cpc": None},
            "campaign": None,
            "platform": "unknown",
            "audience_guess": None,
            "leak_guess": None,
        }

    monkeypatch.setattr(csv_read, "live_key_present", lambda: True)
    monkeypatch.setattr(csv_read, "use_cache_requested", lambda _use_cache=False: False)
    monkeypatch.setattr(csv_read, "chat_json", fake_chat)
    monkeypatch.setattr(
        csv_read,
        "last_call_meta",
        lambda: {"model": "gemini-3.6-flash", "live_or_cache": "live", "latency_ms": 4},
    )
    report = csv_read.interpret_campaign_csv(
        "Amount spent (EUR),Impr.\n100,500\n200,500\n",
        use_cache=False,
    )
    assert report["ok"] is True
    assert report["interpreted_by"] == "llm"
    assert report["totals"]["spend"] == 300
    assert report["totals"]["impressions"] == 1000
