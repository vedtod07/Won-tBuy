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


def evaluate_persona(persona: dict, campaign: dict, round_number: int) -> dict:
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
