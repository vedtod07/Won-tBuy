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


CPC_PER_IMPRESSION = 0.10  # demo constant: EUR per impression


def wasted_spend(impressions: list[dict], cost_per_impression: float = CPC_PER_IMPRESSION) -> dict:
    total = len(impressions)
    on_icp = sum(1 for row in impressions if row.get("in_icp"))
    off_icp = total - on_icp
    return {
        "impressions": total,
        "on_icp": on_icp,
        "off_icp": off_icp,
        "cost_per_impression": cost_per_impression,
        "currency": "EUR",
        "wasted_spend": round(off_icp * cost_per_impression, 2),
        "total_spend": round(total * cost_per_impression, 2),
        "waste_share": round(off_icp / total * 100, 1) if total else 0.0,
    }


def apply_economics(waste: dict, economics: dict | None) -> dict:
    """Rescale simulator waste using the user's last-campaign spend or CPC."""
    if not waste:
        return waste or {}
    out = dict(waste)
    if not economics:
        return out
    total = float(out.get("impressions") or 0)
    off = float(out.get("off_icp") or 0)
    share = (off / total) if total else 0.0
    spend = economics.get("spend")
    cpi = economics.get("cost_per_impression") or economics.get("cpc")
    if spend is not None:
        out["total_spend"] = round(float(spend), 2)
        out["wasted_spend"] = round(float(spend) * share, 2)
        out["source"] = "user_spend"
    elif cpi is not None:
        cpi = float(cpi)
        out["cost_per_impression"] = cpi
        out["wasted_spend"] = round(off * cpi, 2)
        out["total_spend"] = round(total * cpi, 2)
        out["source"] = "user_cpc"
    return out


def parse_campaign_economics(
    spend: float | None = None,
    impressions: float | None = None,
    cpc: float | None = None,
    csv_text: str | None = None,
) -> dict:
    data: dict = {}
    if csv_text and str(csv_text).strip():
        data.update(_economics_from_csv(csv_text))
    if spend is not None:
        data["spend"] = float(spend)
    if impressions is not None:
        data["impressions"] = float(impressions)
    if cpc is not None:
        data["cpc"] = float(cpc)
        data["cost_per_impression"] = float(cpc)
    if data.get("spend") is not None and data.get("impressions"):
        data["cost_per_impression"] = float(data["spend"]) / float(data["impressions"])
    return data


def _economics_from_csv(text: str) -> dict:
    import csv
    import io

    sample = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        return {}
    keys = {name.lower().strip(): name for name in reader.fieldnames}
    spend_key = next((keys[k] for k in keys if k in {"spend", "cost", "amount", "total_spend"}), None)
    impr_key = next((keys[k] for k in keys if k in {"impressions", "imps", "impression"}), None)
    cpc_key = next((keys[k] for k in keys if k in {"cpc", "cpi", "cost_per_impression", "cost_per_click"}), None)
    spend_total = 0.0
    impr_total = 0.0
    cpc_val = None
    rows = 0
    for row in reader:
        rows += 1
        if spend_key:
            spend_total += _num(row.get(spend_key))
        if impr_key:
            impr_total += _num(row.get(impr_key))
        if cpc_key and cpc_val is None:
            cpc_val = _num(row.get(cpc_key))
    out: dict = {}
    if spend_key:
        out["spend"] = round(spend_total, 2)
    if impr_key:
        out["impressions"] = impr_total
    if cpc_val is not None:
        out["cpc"] = cpc_val
        out["cost_per_impression"] = cpc_val
    return out


def _num(value) -> float:
    text = str(value or "").replace(",", "").replace("€", "").replace("$", "").replace("£", "").strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0
