import json

from app.llm import CacheFallback, chat_json


PERSONAS = {
    "klaus": {
        "name": "Klaus",
        "age": 48,
        "role": "plant manager",
        "location": "Germany",
        "trait": "hates slogans without numbers",
    },
    "anika": {
        "name": "Anika",
        "role": "plant manager",
        "trait": "will not click when the price is missing",
    },
    "mateo": {
        "name": "Mateo",
        "role": "plant manager",
        "trait": "rejects unsourced ranking claims",
    },
    "jules": {
        "name": "Jules",
        "age": 22,
        "role": "student with a side hustle",
        "trait": "likes products that sound like a hot operating system",
    },
}


def evaluate_persona(persona: dict, campaign: dict, round_number: int, use_cache: bool = False) -> dict:
    persona_id = persona["id"]
    if not persona["reached"]:
        return {
            "id": persona_id,
            "reached": False,
            "status": "Not reached this round",
        }

    if persona_id == "jules":
        if round_number != 1:
            return {
                "id": persona_id,
                "reached": False,
                "status": "Not reached this round",
            }
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "buy",
            "would_click": True,
            "quote": "It sounds like a hot new operating system.",
            "reason": "Jules is curious about the branding but is not a B2B factory-software buyer.",
        }

    profile = PERSONAS[persona_id]
    result = chat_json(
        "You simulate one buyer reaction. Return JSON only. Do not alter the campaign.",
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
    """Deterministic verdict used when the LLM is unavailable (USE_CACHE or no key).

    Derives each ICP persona's reaction from the campaign copy actually present,
    so cards stay coherent for custom briefs as well as the Northline fixture.
    """
    persona_id = persona["id"]
    if not persona.get("reached", True):
        return {"id": persona_id, "reached": False, "status": "Not reached this round"}

    if persona_id == "jules":
        return {
            "id": persona_id,
            "reached": True,
            "verdict": "buy",
            "would_click": True,
            "quote": "It sounds like a hot new operating system.",
            "reason": "Jules is curious about the branding but is not the B2B buyer.",
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

    if persona_id == "klaus":
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

    if persona_id == "anika":
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

    if persona_id == "mateo":
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

    return {
        "id": persona_id,
        "reached": True,
        "verdict": "ignore",
        "would_click": False,
        "quote": "Not sure this is for me.",
        "reason": "No strong objection, but nothing compelling either.",
    }
