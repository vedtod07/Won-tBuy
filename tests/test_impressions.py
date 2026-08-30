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
