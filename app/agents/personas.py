import json

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
    return {
        **grounded,
        "quote": str(live.get("quote") or grounded.get("quote") or ""),
        "reason": str(live.get("reason") or grounded.get("reason") or ""),
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
    }


def _llm_verdict(persona: dict, campaign: dict, use_cache: bool) -> dict:
    persona_id = persona["id"]
    profile = _profile(persona)
    extra = ""
    if not profile.get("is_icp"):
        extra = (
            " You are not the intended buyer and will never pay. "
            "If the ad sounds broadly appealing, set would_click true."
        )
    result = chat_json(
        "You simulate one buyer reaction." + extra + " Return JSON only. Do not alter the campaign.",
        json.dumps(
            {
                "persona": profile,
                "campaign": campaign,
                "required_schema": {
                    "id": persona_id,
                    "reached": True,
                    "verdict": "buy|ignore|object",
                    "would_click": "boolean",
                    "quote": "short first-person quote",
                    "reason": "one short sentence",
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
        name = persona.get("name") or "This person"
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "buy",
            "would_click": True,
            "quote": "It sounds like a hot new operating system.",
            "reason": f"{name} is curious about the branding but is not the buyer.",
        }

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
