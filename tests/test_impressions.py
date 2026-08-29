"""Tests for the code-only impression sampler.

Verifies: seed determinism, row count, p_icp ranges for broad vs tight
targeting, and that in-ICP rows only carry roles/industries/regions
that the ICP sampler is allowed to pick.
"""

from app.impressions import sample_impressions, targeting_accuracy
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


def test_every_row_has_required_fields():
    impressions = sample_impressions(_broad_campaign().targeting)
    for row in impressions:
        assert {"id", "industry", "role", "company_size", "region", "in_icp"} <= set(row)
