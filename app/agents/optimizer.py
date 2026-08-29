import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.models import Campaign, Creative, Industry, LandingPage, Region, Role, Targeting


FIXED_PRICE = "from €199/mo"
FIXED_CTA = "Book a demo"
FIXED_PROOF = "Trusted by 40 plants across Europe"


def tighten_targeting(campaign: Campaign) -> Campaign:
    targeting = Targeting(
        industries=[Industry.MANUFACTURING],
        roles=[Role.PLANT_MANAGER, Role.OPERATIONS_MANAGER],
        company_sizes=campaign.targeting.company_sizes,
        regions=[Region.EUROPE],
    )
    return campaign.model_copy(update={"targeting": targeting}, deep=True)


def optimize_copy(campaign: Campaign, cached_campaign: Campaign) -> Campaign:
    if _use_cache() or not os.getenv("LLM_API_KEY"):
        return _cached_copy(campaign, cached_campaign)

    try:
        result = _chat_copy(campaign)
        ad = Creative.model_validate(result["ad"])
        page = LandingPage.model_validate(result["page"])
        _validate_copy(ad, page)
        return campaign.model_copy(update={"ad": ad, "page": page}, deep=True)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _cached_copy(campaign, cached_campaign)


def _use_cache() -> bool:
    return os.getenv("USE_CACHE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _cached_copy(campaign: Campaign, cached_campaign: Campaign) -> Campaign:
    _validate_copy(cached_campaign.ad, cached_campaign.page)
    return campaign.model_copy(
        update={"ad": cached_campaign.ad, "page": cached_campaign.page, "email": cached_campaign.email},
        deep=True,
    )


def _chat_copy(campaign: Campaign) -> dict:
    prompt = {
        "company": campaign.company,
        "product": "factory dashboard for plant managers to see machine downtime before the shift",
        "requirements": {
            "page_price": FIXED_PRICE,
            "ad_cta": FIXED_CTA,
            "page_cta": FIXED_CTA,
            "forbidden_claims": ["#1", "best in the world"],
            "proof": FIXED_PROOF,
        },
        "schema": {
            "ad": {"headline": "string", "body": "string", "cta": FIXED_CTA},
            "page": {
                "headline": "string",
                "body": "string",
                "bullets": ["string", "string", "string"],
                "proof": FIXED_PROOF,
                "cta": FIXED_CTA,
                "price": FIXED_PRICE,
            },
        },
    }
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "Improve copy only. Return JSON only. Never change targeting or company.",
                    },
                    {"role": "user", "content": json.dumps(prompt)},
                ],
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
    result = json.loads(payload["choices"][0]["message"]["content"])
    if not isinstance(result, dict):
        raise ValueError("LLM copy response was not an object")
    return result


def _validate_copy(ad: Creative, page: LandingPage) -> None:
    copy = " ".join(
        (ad.headline, ad.body, page.headline, page.body)
        + tuple(page.bullets)
    ).lower()
    if "#1" in copy or "best in the world" in copy:
        raise ValueError("Copy contains an unsourced ranking claim")
    if page.price != FIXED_PRICE:
        raise ValueError("Page price is invalid")
    if ad.cta != FIXED_CTA or page.cta != FIXED_CTA:
        raise ValueError("Campaign CTA is invalid")
