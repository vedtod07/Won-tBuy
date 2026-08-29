import random

from app.models import Targeting


SEED = 42
IMPRESSION_COUNT = 80
ICP_ROLES = {"plant_manager", "operations_manager"}


def icp_probability(targeting: Targeting) -> float:
    industries = {industry.value for industry in targeting.industries}
    roles = {role.value for role in targeting.roles}
    regions = {region.value for region in targeting.regions}

    is_tight = (
        industries == {"manufacturing"}
        and roles <= ICP_ROLES
        and bool(roles)
        and regions == {"europe"}
    )
    return 0.85 if is_tight else 0.40


def sample_impressions(
    targeting: Targeting,
    n: int = IMPRESSION_COUNT,
    seed: int = SEED,
) -> list[dict]:
    rng = random.Random(seed)
    target_icp_count = round(n * icp_probability(targeting))
    in_icp_flags = [True] * target_icp_count + [False] * (n - target_icp_count)
    rng.shuffle(in_icp_flags)

    industries = [industry.value for industry in targeting.industries]
    roles = [role.value for role in targeting.roles]
    company_sizes = [size.value for size in targeting.company_sizes]
    regions = [region.value for region in targeting.regions]

    impressions = []
    for index, in_icp in enumerate(in_icp_flags, start=1):
        if in_icp:
            industry = "manufacturing" if "manufacturing" in industries else rng.choice(industries)
            eligible_roles = [role for role in roles if role in ICP_ROLES]
            role = rng.choice(eligible_roles or roles)
            region = "europe" if "europe" in regions else rng.choice(regions)
        else:
            industry = rng.choice(industries)
            role = rng.choice(roles)
            region = rng.choice(regions)

        impressions.append(
            {
                "id": index,
                "industry": industry,
                "role": role,
                "company_size": rng.choice(company_sizes),
                "region": region,
                "in_icp": in_icp,
            }
        )

    return impressions


def targeting_accuracy(impressions: list[dict]) -> float:
    if not impressions:
        return 0.0
    in_icp_count = sum(impression["in_icp"] for impression in impressions)
    return round(in_icp_count / len(impressions) * 100, 1)
