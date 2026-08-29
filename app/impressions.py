import random

from app.models import Targeting


SEED = 42
IMPRESSION_COUNT = 80
DEFAULT_LEAK_ROLES = {"student"}


def _val(item) -> str:
    return item.value if hasattr(item, "value") else str(item)


def icp_probability(targeting: Targeting, leak_roles: set[str] | None = None) -> float:
    roles = {_val(role) for role in targeting.roles}
    leaks = leak_roles or DEFAULT_LEAK_ROLES
    return 0.40 if roles & leaks else 0.85


def sample_impressions(
    targeting: Targeting,
    n: int = IMPRESSION_COUNT,
    seed: int = SEED,
    leak_roles: set[str] | None = None,
) -> list[dict]:
    rng = random.Random(seed)
    leaks = leak_roles or DEFAULT_LEAK_ROLES
    target_icp_count = round(n * icp_probability(targeting, leaks))
    in_icp_flags = [True] * target_icp_count + [False] * (n - target_icp_count)
    rng.shuffle(in_icp_flags)

    industries = [_val(industry) for industry in targeting.industries]
    roles = [_val(role) for role in targeting.roles]
    company_sizes = [_val(size) for size in targeting.company_sizes]
    regions = [_val(region) for region in targeting.regions]
    icp_roles = [role for role in roles if role not in leaks] or roles

    impressions = []
    for index, in_icp in enumerate(in_icp_flags, start=1):
        if in_icp:
            industry = industries[0]
            role = rng.choice(icp_roles)
            region = regions[0]
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
