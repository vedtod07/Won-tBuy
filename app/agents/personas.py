import json
import re

from app.llm import CacheFallback, chat_json, live_key_present, use_cache_requested


PERSONAS = {
    "klaus": {
        "name": "Klaus",
        "age": 48,
        "role": "plant manager",
        "location": "Germany",
        "trait": "hates slogans without numbers",
        "objection": "proof",
        "is_icp": True,
    },
    "anika": {
        "name": "Anika",
        "role": "plant manager",
        "trait": "will not click when the price is missing",
        "objection": "price",
        "is_icp": True,
    },
    "mateo": {
        "name": "Mateo",
        "role": "plant manager",
        "trait": "rejects unsourced ranking claims",
        "objection": "ranking",
        "is_icp": True,
    },
    "jules": {
        "name": "Jules",
        "age": 22,
        "role": "student with a side hustle",
        "trait": "likes products that sound like a hot operating system",
        "is_icp": False,
    },
}

_ID_OBJECTION = {"klaus": "proof", "anika": "price", "mateo": "ranking"}
NORTHLINE_IDS = {"klaus", "anika", "mateo", "jules"}
_FACTORY_VOICE = re.compile(
    r"operating system|plant manager|factory floor|downtime dashboard",
    re.I,
)


def evaluate_persona(persona: dict, campaign: dict, round_number: int, use_cache: bool = False) -> dict:
    persona_id = persona["id"]
    if not persona.get("reached"):
        return {
            "id": persona_id,
            "reached": False,
            "status": "Not reached this round",
        }

    grounded = cached_verdict(persona, campaign)
    if use_cache_requested(use_cache) or not live_key_present():
        return grounded

    try:
        live = _llm_verdict(persona, campaign, use_cache)
    except CacheFallback:
        return grounded
    quote = str(live.get("quote") or grounded.get("quote") or "")
    reason = str(live.get("reason") or grounded.get("reason") or "")
    if _quote_bleeds_northline(quote, persona, campaign):
        quote = str(grounded.get("quote") or quote)
        reason = str(grounded.get("reason") or reason)
    return {
        **grounded,
        "quote": quote,
        "reason": reason,
    }


def evaluate_shopper(persona: dict, campaign: dict, use_cache: bool = False) -> dict:
    """Graph entry: reach is already set from targeting, not from round number."""
    return evaluate_persona(persona, campaign, 0, use_cache=use_cache)


def _profile(persona: dict) -> dict:
    stored = PERSONAS.get(persona["id"], {})
    return {
        "name": persona.get("name") or stored.get("name"),
        "title": persona.get("title") or persona.get("segment") or stored.get("role"),
        "trait": persona.get("trait") or stored.get("trait"),
        "is_icp": persona.get("is_icp", stored.get("is_icp", True)),
        "objection": persona.get("objection") or stored.get("objection"),
        "audience_label": persona.get("audience_label"),
        "product": persona.get("product"),
    }


def _northline_shopper(persona: dict) -> bool:
    return persona.get("id") in NORTHLINE_IDS


def _factory_campaign(campaign: dict, persona: dict) -> bool:
    blob = " ".join(
        [
            str(campaign.get("company") or ""),
            str((campaign.get("ad") or {}).get("body") or ""),
            str(persona.get("title") or ""),
            str(persona.get("product") or ""),
            str(persona.get("audience_label") or ""),
        ]
    ).lower()
    return any(word in blob for word in ("factory", "plant manager", "downtime", "manufactur", "oee"))


def _quote_bleeds_northline(quote: str, persona: dict, campaign: dict) -> bool:
    if _northline_shopper(persona) or _factory_campaign(campaign, persona):
        return False
    return bool(_FACTORY_VOICE.search(quote or ""))


def _job(persona: dict) -> str:
    title = str(persona.get("title") or persona.get("segment") or "").replace("_", " ").strip()
    if not title:
        title = str(PERSONAS.get(persona.get("id"), {}).get("role") or "buyer")
    return title.split("·")[0].strip() or "buyer"


def _product_hook(persona: dict, campaign: dict) -> tuple[str, str]:
    company = str(campaign.get("company") or "this brand")
    product = str(persona.get("product") or "").strip()
    if not product:
        product = str((campaign.get("ad") or {}).get("body") or company)
    hook = product.split(".")[0].strip()[:70] or company
    if company.lower() not in hook.lower():
        hook = company
    return company, hook


def _llm_verdict(persona: dict, campaign: dict, use_cache: bool) -> dict:
    persona_id = persona["id"]
    profile = _profile(persona)
    extra = ""
    if not profile.get("is_icp"):
        extra = (
            " You are not the intended buyer and will never pay. "
            "If the ad sounds broadly appealing, set would_click true."
        )
    voice = (
        " Speak in first person as the job in persona.title about this company and product. "
        "The quote must sound like that job reacting to this product — never like a factory "
        "plant manager, and never mention an operating system, unless that is this job or this product."
    )
    result = chat_json(
        "You simulate one buyer reaction." + extra + voice + " Return JSON only. Do not alter the campaign.",
        json.dumps(
            {
                "persona": profile,
                "company": campaign.get("company"),
                "ad": campaign.get("ad"),
                "page": campaign.get("page"),
                "required_schema": {
                    "id": persona_id,
                    "reached": True,
                    "verdict": "buy|ignore|object",
                    "would_click": "boolean",
                    "quote": "short first-person quote in this shopper's voice about this product",
                    "reason": "one short sentence naming this product and this job",
                },
            }
        ),
        use_cache=use_cache,
    )

    if result.get("verdict") not in {"buy", "ignore", "object"}:
        raise CacheFallback("Invalid persona verdict")
    if not isinstance(result.get("would_click"), bool):
        raise CacheFallback("Invalid persona click decision")

    return {
        "id": persona_id,
        "reached": True,
        "verdict": result["verdict"],
        "would_click": result["would_click"],
        "quote": str(result.get("quote", "")),
        "reason": str(result.get("reason", "")),
    }


def cached_verdict(persona: dict, campaign: dict) -> dict:
    """Deterministic verdict from the copy actually on the page."""
    persona_id = persona["id"]
    if not persona.get("reached", True):
        return {"id": persona_id, "reached": False, "status": "Not reached this round"}

    is_icp = persona.get("is_icp")
    if is_icp is None:
        is_icp = persona_id not in {"jules", "leak"}
    if not is_icp:
        if _northline_shopper(persona):
            name = persona.get("name") or "This person"
            return {
                "id": persona_id,
                "reached": True,
                "verdict": "buy",
                "would_click": True,
                "quote": "It sounds like a hot new operating system.",
                "reason": f"{name} is curious about the branding but is not the buyer.",
            }
        return _custom_leak_verdict(persona, campaign)

    copy = " ".join(
        [
            campaign.get("ad", {}).get("headline", ""),
            campaign.get("ad", {}).get("body", ""),
            campaign.get("page", {}).get("headline", ""),
            campaign.get("page", {}).get("body", ""),
            " ".join(campaign.get("page", {}).get("bullets", [])),
        ]
    ).lower()
    has_price = bool(campaign.get("page", {}).get("price"))
    has_ranking = "#1" in copy or "best in the world" in copy
    objection = persona.get("objection") or _ID_OBJECTION.get(persona_id, "price")

    if _northline_shopper(persona):
        return _northline_buyer_verdict(persona_id, objection, has_price, has_ranking)
    return _custom_buyer_verdict(persona, campaign, objection, has_price, has_ranking)


def _northline_buyer_verdict(persona_id: str, objection: str, has_price: bool, has_ranking: bool) -> dict:
    if objection == "proof":
        if has_ranking or not has_price:
            return {
                "id": persona_id,
                "reached": True,
                "verdict": "object",
                "would_click": False,
                "quote": "A slogan with no numbers behind it tells me nothing.",
                "reason": "Objects to claims without proof and to a missing price.",
            }
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "buy",
            "would_click": True,
            "quote": "A number I can act on. I'd book a demo.",
            "reason": "Proof and price are present, so the objection clears.",
        }

    if objection == "price":
        if not has_price:
            return {
                "id": persona_id,
                "reached": True,
                "verdict": "ignore",
                "would_click": False,
                "quote": "No price anywhere — I'm not clicking just to find out.",
                "reason": "Will not click when the price is missing.",
            }
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "buy",
            "would_click": True,
            "quote": "The price is right there. Fine, show me.",
            "reason": "The price is present, so the blocker is gone.",
        }

    if has_ranking:
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "object",
            "would_click": False,
            "quote": "Who says that? There's no source.",
            "reason": "Rejects an unsourced ranking claim.",
        }
    return {
        "id": persona_id,
        "reached": True,
        "verdict": "buy",
        "would_click": True,
        "quote": "No fake claims, just what it does. Yes.",
        "reason": "No unsourced ranking claim in the copy.",
    }


def _custom_leak_verdict(persona: dict, campaign: dict) -> dict:
    name = persona.get("name") or "This person"
    company, hook = _product_hook(persona, campaign)
    job = _job(persona)
    return {
        "id": persona["id"],
        "reached": True,
        "verdict": "buy",
        "would_click": True,
        "quote": f"{company} looks catchy — I'd tap it, even though I'm not who they sell to.",
        "reason": f"{name} ({job}) would click {company} out of curiosity and never buy {hook}.",
    }


def _im_a(job: str) -> str:
    voice = re.sub(r"\s+", " ", job or "buyer").strip().lower()
    if voice.startswith("hr "):
        voice = "HR " + voice[3:]
    elif voice.startswith("gcse "):
        voice = "GCSE " + voice[5:]
    article = "an" if (voice[:1].lower() in "aeiou" or voice.lower().startswith("hr ")) else "a"
    return f"I'm {article} {voice}"


def _custom_buyer_verdict(
    persona: dict,
    campaign: dict,
    objection: str,
    has_price: bool,
    has_ranking: bool,
) -> dict:
    persona_id = persona["id"]
    job = _job(persona)
    company, hook = _product_hook(persona, campaign)
    audience = str(persona.get("audience_label") or job)

    if objection == "proof":
        if has_ranking or not has_price:
            return {
                "id": persona_id,
                "reached": True,
                "verdict": "object",
                "would_click": False,
                "quote": (
                    f"{_im_a(job)}. Calling {company} '#1' with nothing behind it "
                    f"doesn't help me buy {hook}."
                ),
                "reason": f"{job} wants proof for {company}, not a ranking slogan.",
            }
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "buy",
            "would_click": True,
            "quote": f"As {_im_a(job)[4:]}, a real number and a price — I'd go further with {company}.",
            "reason": f"Proof and price are present for {audience}.",
        }

    if objection == "price":
        if not has_price:
            return {
                "id": persona_id,
                "reached": True,
                "verdict": "ignore",
                "would_click": False,
                "quote": (
                    f"{_im_a(job)}. No price on {company} — I'm not clicking just to find out "
                    f"what {hook} costs."
                ),
                "reason": f"{job} will not click {company} when the price is missing.",
            }
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "buy",
            "would_click": True,
            "quote": f"The price for {company} is right there. Fine, show me.",
            "reason": f"The price is present, so the {job} blocker is gone.",
        }

    if has_ranking:
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "object",
            "would_click": False,
            "quote": f"Who ranked {company} #1? That means nothing when I'm buying as {_im_a(job)[4:]}.",
            "reason": f"{job} rejects an unsourced ranking claim for {company}.",
        }
    return {
        "id": persona_id,
        "reached": True,
        "verdict": "buy",
        "would_click": True,
        "quote": f"No fake ranking — just what {company} does. Yes.",
        "reason": f"No unsourced ranking claim in the {company} copy.",
    }
