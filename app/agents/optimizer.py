from app.llm import CacheFallback, chat_json, use_cache_requested
from app.models import Campaign, Creative, LandingPage, Industry, Region, Role, Targeting


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


def optimize_copy(campaign: Campaign, cached_campaign: Campaign, use_cache: bool = False) -> Campaign:
    if use_cache or use_cache_requested():
        return _cached_copy(campaign, cached_campaign)

    try:
        result = chat_json(
            "Improve copy only. Return JSON only. Never change targeting or company.",
            _copy_prompt(campaign),
            use_cache=use_cache,
        )
        ad = Creative.model_validate(result["ad"])
        page = LandingPage.model_validate(result["page"])
        _validate_copy(ad, page)
        return campaign.model_copy(update={"ad": ad, "page": page}, deep=True)
    except CacheFallback:
        return _cached_copy(campaign, cached_campaign)
    except (KeyError, TypeError, ValueError):
        return _cached_copy(campaign, cached_campaign)


def _cached_copy(campaign: Campaign, cached_campaign: Campaign) -> Campaign:
    _validate_copy(cached_campaign.ad, cached_campaign.page)
    return campaign.model_copy(
        update={"ad": cached_campaign.ad, "page": cached_campaign.page, "email": cached_campaign.email},
        deep=True,
    )


def _copy_prompt(campaign: Campaign) -> str:
    return (
        "{\n"
        f'  "company": {campaign.company!r},\n'
        '  "product": "factory dashboard for plant managers to see machine downtime before the shift",\n'
        "  \"requirements\": {\n"
        f'    "page_price": {FIXED_PRICE!r},\n'
        f'    "ad_cta": {FIXED_CTA!r},\n'
        f'    "page_cta": {FIXED_CTA!r},\n'
        '    "forbidden_claims": ["#1", "best in the world"],\n'
        f'    "proof": {FIXED_PROOF!r}\n'
        "  },\n"
        "  \"schema\": {\n"
        '    "ad": {"headline": "string", "body": "string", "cta": "Book a demo"},\n'
        "    \"page\": {\n"
        '      "headline": "string", "body": "string",\n'
        '      "bullets": ["string", "string", "string"],\n'
        f'      "proof": {FIXED_PROOF!r}, "cta": "Book a demo", "price": {FIXED_PRICE!r}\n'
        "    }\n"
        "  }\n"
        "}"
    )


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
