from app.llm import CacheFallback, chat_json, live_key_present, use_cache_requested
from app.models import Campaign, Creative, Email, LandingPage, Targeting


FIXED_PRICE = "from €199/mo"
FIXED_CTA = "Book a demo"
FIXED_PROOF = "Trusted by 40 plants across Europe"


def tighten_targeting(campaign: Campaign, tight: dict | Targeting | None = None) -> Campaign:
    if tight is not None:
        targeting = tight if isinstance(tight, Targeting) else Targeting.model_validate(tight)
        return campaign.model_copy(update={"targeting": targeting}, deep=True)
    industries = [str(item) for item in campaign.targeting.industries]
    if "manufacturing" in industries:
        industries = ["manufacturing"]
    else:
        industries = industries[:1] or ["manufacturing"]
    roles = [str(role) for role in campaign.targeting.roles if str(role) not in {"student", "engineer"}]
    if not roles:
        roles = ["plant_manager", "operations_manager"]
    regions = [str(region) for region in campaign.targeting.regions]
    if "europe" in regions:
        regions = ["europe"]
    else:
        regions = regions[:1] or ["europe"]
    targeting = Targeting(
        industries=industries,
        roles=roles,
        company_sizes=[str(size) for size in campaign.targeting.company_sizes],
        regions=regions,
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


def _copy_prompt(campaign: Campaign, required_price: str = FIXED_PRICE, proof: str = FIXED_PROOF) -> str:
    product = (campaign.page.body or campaign.ad.body or campaign.company).strip()[:240]
    return (
        "{\n"
        f'  "company": {campaign.company!r},\n'
        f'  "product": {product!r},\n'
        "  \"requirements\": {\n"
        f'    "page_price": {required_price!r},\n'
        f'    "ad_cta": {FIXED_CTA!r},\n'
        f'    "page_cta": {FIXED_CTA!r},\n'
        '    "forbidden_claims": ["#1", "best in the world"],\n'
        f'    "proof": {proof!r}\n'
        "  },\n"
        "  \"schema\": {\n"
        '    "ad": {"headline": "string", "body": "string", "cta": "Book a demo"},\n'
        "    \"page\": {\n"
        '      "headline": "string", "body": "string",\n'
        '      "bullets": ["string", "string", "string"],\n'
        f'      "proof": {proof!r}, "cta": "Book a demo", "price": {required_price!r}\n'
        "    },\n"
        '    "email": {"subject": "string", "body": "string"}\n'
        "  }\n"
        "}"
    )


def rewrite_copy(
    campaign: Campaign,
    use_cache: bool = False,
    cached_campaign: Campaign | None = None,
    allow_fixture: bool = True,
    required_price: str = FIXED_PRICE,
    proof_line: str | None = None,
) -> tuple[Campaign, str | None]:
    """Optimizer tool: rewrite ad + page. Live path never silently pastes a fixture."""
    proof = proof_line or FIXED_PROOF
    offline = use_cache or use_cache_requested() or not live_key_present()
    if offline and allow_fixture and cached_campaign is not None:
        return _cached_copy(campaign, cached_campaign), None
    if offline and not allow_fixture:
        repaired = _deterministic_repair(campaign, required_price, proof)
        return repaired, None

    last_error = "Optimizer: rewrite_copy returned nothing."
    for _attempt in range(2):
        try:
            result = chat_json(
                "Improve copy only. Return JSON only. Never change targeting or company. Use the required price exactly.",
                _copy_prompt(campaign, required_price, proof),
                use_cache=False,
            )
            ad = Creative.model_validate(result["ad"])
            page = LandingPage.model_validate(result["page"])
            _validate_copy(ad, page, required_price)
            updates: dict = {"ad": ad, "page": page}
            if result.get("email"):
                updates["email"] = Email.model_validate(result["email"])
            return campaign.model_copy(update=updates, deep=True), None
        except CacheFallback as error:
            last_error = f"Optimizer: rewrite_copy had no live model ({error})."
            break
        except (KeyError, TypeError, ValueError) as error:
            last_error = f"Optimizer: rewrite failed validation ({error}). Retrying."

    if allow_fixture and cached_campaign is not None:
        return _cached_copy(campaign, cached_campaign), None
    repaired = _deterministic_repair(campaign, required_price, proof)
    return repaired, last_error.replace(" Retrying.", "") + " Applied a validated repair so the lab can show right words."


def _deterministic_repair(campaign: Campaign, required_price: str, proof: str = FIXED_PROOF) -> Campaign:
    name = campaign.company
    ad = Creative(
        headline=f"See the outcome before the next review — {name}",
        body=f"{name} for the buyer who should actually pay. {required_price}. No unsourced ranking.",
        cta=FIXED_CTA,
    )
    page = LandingPage(
        headline=f"{name}: what it does, what it costs",
        body=f"{name} stated plainly for the intended buyer — not a slogan for everyone.",
        bullets=[
            "Who it is for, in one line",
            "What you see in the first session",
            "A number on the page before you book",
        ],
        proof=proof,
        highlight="Price and proof, not a ranking claim.",
        cta=FIXED_CTA,
        price=required_price,
    )
    email = Email(
        subject=f"15 min on {name}",
        body=f"Hi,\n\n{required_price}. I can walk the offer without the ranking language.\n",
    )
    _validate_copy(ad, page, required_price)
    return campaign.model_copy(update={"ad": ad, "page": page, "email": email}, deep=True)


def _validate_copy(ad: Creative, page: LandingPage, required_price: str = FIXED_PRICE) -> None:
    copy = " ".join(
        (ad.headline, ad.body, page.headline, page.body)
        + tuple(page.bullets)
    ).lower()
    if "#1" in copy or "best in the world" in copy:
        raise ValueError("Copy contains an unsourced ranking claim")
    if page.price != required_price:
        raise ValueError("Page price is invalid")
    if ad.cta != FIXED_CTA or page.cta != FIXED_CTA:
        raise ValueError("Campaign CTA is invalid")
