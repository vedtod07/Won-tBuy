"""Turn a free-text brief into a lab: brand, price, audience, shoppers.

Never invent a Northline price. If the human wrote 49 pounds, the lab
uses from £49/mo — including typos like 'moth' for 'month'.
When a live model is present it names the audience; there is no industry lookup table.
"""

from __future__ import annotations

import re

from app.llm import CacheFallback, chat_json, live_key_present, use_cache_requested
from app.models import Campaign, CompanySize, Creative, LandingPage, Targeting


SIZES = [CompanySize.SMALL.value, CompanySize.MEDIUM.value, CompanySize.LARGE.value]

CURRENCY_WORDS = (
    (r"pounds?|gbp|sterling", "£"),
    (r"dollars?|usd", "$"),
    (r"euros?|eur", "€"),
    (r"rupees?|inr|rs", "₹"),
)

MONTH = r"(?:months?|moths?|mo)"


def parse_price(brief: str) -> str | None:
    """Normalize a price from messy human text. Returns None if none is present."""
    text = brief.replace(",", " ")
    match = re.search(
        rf"([€$£₹])\s*(\d+(?:\.\d+)?)\s*(?:/\s*|\s+per\s+){MONTH}\b",
        text,
        re.I,
    )
    if match:
        return f"from {match.group(1)}{match.group(2)}/mo"

    match = re.search(
        rf"([€$£₹])\s*(\d+(?:\.\d+)?)\s*/\s*{MONTH}\b",
        text,
        re.I,
    )
    if match:
        return f"from {match.group(1)}{match.group(2)}/mo"

    words = "|".join(pattern for pattern, _symbol in CURRENCY_WORDS)
    match = re.search(
        rf"(\d+(?:\.\d+)?)\s*({words})\s*(?:/\s*|\s+per\s+)?(?:{MONTH})?\b",
        text,
        re.I,
    )
    if match:
        return f"from {_symbol_for_word(match.group(2))}{match.group(1)}/mo"

    match = re.search(r"(?:from\s+)?([€$£₹])\s*(\d+(?:\.\d+)?)", text, re.I)
    if match:
        return f"from {match.group(1)}{match.group(2)}/mo"

    match = re.search(
        rf"(\d+(?:\.\d+)?)\s*(?:/\s*|\s+per\s+){MONTH}\b",
        text,
        re.I,
    )
    if match:
        return f"from ${match.group(1)}/mo"
    return None


class BriefError(ValueError):
    pass


def _symbol_for_word(word: str) -> str:
    lowered = word.lower()
    for pattern, symbol in CURRENCY_WORDS:
        if re.fullmatch(pattern, lowered):
            return symbol
    return "$"


def interpret_brief(brief: str, use_cache: bool = False) -> dict:
    """Live: the model names brand, audience, and shoppers. Price is still checked against the brief.

    Offline: no industry keyword table — audience is taken from the words after 'for'.
    """
    text = brief.strip()
    parsed_price = parse_price(text)
    live = live_key_present() and not use_cache_requested(use_cache)
    payload = None
    if live:
        prompt = (
            f"Brief:\n{text}\n\n"
            "There is NO default industry. Infer who should buy from this text only "
            "(shoe store → store managers; dentist → clinicians; cafe → owners; whatever the brief says). "
            "Never return plant_manager unless the brief is about factories or plants. "
            "Never invent a price that is not in the brief. Never use 199 unless the brief says 199. "
            "Normalize price: pounds→£, dollars→$, euros→€, per month/moth/mo→/mo, prefix 'from '. "
            "Invent three intended-buyer names with job titles that match THIS audience, and one leak who is not a buyer.\n"
            "Return {\n"
            '  "reasoning": "two first-person sentences: brand, price you read, who should see it, who is the leak",\n'
            '  "company": "brand",\n'
            '  "product": "one sentence",\n'
            '  "price": "from £49/mo or null",\n'
            '  "audience_label": "who should buy, in their words",\n'
            '  "tight_targeting": {"industries": ["slug"], "roles": ["slug"], "regions": ["slug"]},\n'
            '  "leak_role": "slug",\n'
            '  "buyers": [{"name": "str", "title": "job · place", "objection": "proof|price|ranking"}],\n'
            '  "leak": {"name": "str", "title": "why they are not the buyer"}\n'
            "}"
        )
        for _attempt in range(2):
            try:
                result = chat_json(
                    "You interpret one campaign brief. Return JSON only. Reason from the brief; do not reuse a previous product.",
                    prompt,
                    use_cache=False,
                )
                if result.get("company") or result.get("audience_label") or result.get("tight_targeting"):
                    payload = result
                    break
            except CacheFallback:
                payload = None
                break
            except (KeyError, TypeError, ValueError):
                payload = None
    briefing = assemble_briefing(text, parsed_price, payload)
    briefing["interpreted_by"] = "llm" if payload else "offline"
    if payload:
        model_text = str(payload.get("reasoning") or "").strip()
        if model_text:
            briefing["reasoning"] = model_text
    else:
        briefing["reasoning"] = (
            "No live model this run — I parsed brand, price, and the audience from the words after 'for' "
            "in your brief, not from a fixed industry list. "
            + briefing["reasoning"]
        )
    return briefing


def assemble_briefing(brief: str, parsed_price: str | None, llm: dict | None) -> dict:
    company = _company(brief, llm)
    product = ""
    if llm:
        product = str(llm.get("product") or "").strip()
    if not product:
        product = brief.split(".")[0].strip()[:180] or company

    price = parsed_price
    if not price and llm:
        llm_price = str(llm.get("price") or "").strip()
        if llm_price and llm_price.lower() not in {"null", "none", ""}:
            if "199" in llm_price and "199" not in brief:
                llm_price = ""
            price = llm_price or None

    if not price:
        raise BriefError(
            "No price in the brief — I will not invent €199 or any other number. "
            "Add one, e.g. 49 pounds per month."
        )

    audience = _audience(brief, llm)
    leak_role = str((llm or {}).get("leak_role") or audience["leak_role"])
    leak_role = re.sub(r"[^a-z0-9_]+", "_", leak_role.lower()).strip("_") or "student"

    tight = Targeting.model_validate(
        {
            "industries": audience["industries"],
            "roles": audience["roles"],
            "company_sizes": SIZES,
            "regions": audience["regions"],
        }
    )
    leaky_roles = list(dict.fromkeys([*tight.roles, leak_role]))
    leaky_industries = list(dict.fromkeys([*tight.industries, "education", "technology"]))
    leaky_regions = list(dict.fromkeys([*tight.regions, "north_america", "europe"]))
    leaky = Targeting(
        industries=leaky_industries,
        roles=leaky_roles,
        company_sizes=SIZES,
        regions=leaky_regions,
    )

    headline_core = product if product else company
    if "#1" not in headline_core:
        headline_core = f"The #1 {headline_core}"
    campaign = Campaign(
        company=company,
        targeting=leaky,
        ad=Creative(headline=headline_core[:140], body=brief.strip(), cta="Learn more"),
        page=LandingPage(
            headline=headline_core[:140],
            body=brief.strip(),
            bullets=[],
            proof=None,
            cta="Learn more",
            price=None,
        ),
    )

    personas = _shoppers(brief, llm, audience, leak_role)
    reasoning = ""
    if llm:
        reasoning = str(llm.get("reasoning") or "").strip()
    if not reasoning:
        reasoning = (
            f"I read this as {company}. Price is {price} — taken from the brief, not a demo default. "
            f"Intended audience: {audience['label']}. Leak I will cut in step 2: {personas[-1]['name']} ({leak_role})."
        )

    return {
        "company": company,
        "product": product,
        "price": price,
        "audience_label": audience["label"],
        "tight_targeting": tight.model_dump(mode="json"),
        "leak_role": leak_role,
        "leak_id": "leak",
        "personas": personas,
        "campaign": campaign,
        "reasoning": reasoning,
        "proof": _proof_line(brief, company),
        "interpreted_by": "llm" if llm else "offline",
    }


def _company(brief: str, llm: dict | None) -> str:
    if llm:
        name = str(llm.get("company") or "").strip().strip(".,;:")
        if name:
            return name[:40]
    token = brief.replace("\n", " ").split(" ")[0].strip(",.!?:;")
    return token or "Your product"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")[:40]


def _slugs(values) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    return [slug for slug in (_slug(item) for item in values) if slug]


def _regions_from_brief(brief: str) -> list[str]:
    text = brief.lower()
    if any(word in text for word in ("uk", "britain", "british", "pound", "london")):
        return ["united_kingdom"]
    if any(word in text for word in ("us ", "usa", "united states", "dollar")):
        return ["north_america"]
    return ["europe"]


def _audience(brief: str, llm: dict | None) -> dict:
    from_model = _audience_from_llm(brief, llm)
    if from_model:
        return from_model
    return _audience_from_for_clause(brief, _regions_from_brief(brief))


def _audience_from_llm(brief: str, llm: dict | None) -> dict | None:
    if not llm:
        return None
    raw = llm.get("tight_targeting") if isinstance(llm.get("tight_targeting"), dict) else {}
    industries = _slugs(raw.get("industries"))
    roles = [role for role in _slugs(raw.get("roles")) if role not in {"student", "intern", "hobbyist"}]
    regions = _slugs(raw.get("regions")) or _regions_from_brief(brief)
    buyers = list(llm.get("buyers") or [])
    if not roles:
        roles = [role for role in (_slug(row.get("title") or "") for row in buyers) if role]
    if not industries:
        label_slug = _slug(str(llm.get("audience_label") or ""))
        if label_slug:
            industries = [label_slug]
    if not roles and not industries and not llm.get("audience_label"):
        return None
    label = str(llm.get("audience_label") or "").strip() or ", ".join(roles).replace("_", " ")
    leak = llm.get("leak") if isinstance(llm.get("leak"), dict) else {}
    return {
        "industries": (industries or ["local_business"])[:3],
        "roles": (roles or ["buyer"])[:4],
        "regions": regions[:3],
        "label": label or "intended buyers",
        "titles": [str(row.get("title") or "") for row in buyers],
        "leak_role": str(llm.get("leak_role") or "student"),
        "leak_title": str(leak.get("title") or "Not the buyer"),
    }


def _audience_from_for_clause(brief: str, region: list[str]) -> dict:
    match = re.search(r"\bfor\s+(.+)", brief, re.I)
    who = match.group(1).strip() if match else ""
    who = re.split(r"\bfrom\b|\bstarting\b|\d", who, maxsplit=1)[0]
    who = who.strip(" .,;:—-")
    if len(who) < 6:
        who = "the buyers named in the brief"
    label = who[:80]
    return {
        "industries": ["local_business"],
        "roles": ["owner", "manager"],
        "regions": region,
        "label": label,
        "titles": [
            f"Owner · {label[:42]}",
            f"Manager · {label[:42]}",
            f"Buyer · {label[:42]}",
        ],
        "leak_role": "student",
        "leak_title": f"Not a buyer for {label[:40]} — no budget",
    }


def _shoppers(brief: str, llm: dict | None, audience: dict, leak_role: str) -> list[dict]:
    objections = ("proof", "price", "ranking")
    buyers = []
    llm_buyers = list((llm or {}).get("buyers") or [])
    fallback_names = ("Priya", "Owen", "Mina")
    for index, objection in enumerate(objections):
        row = llm_buyers[index] if index < len(llm_buyers) else {}
        name = str(row.get("name") or fallback_names[index])
        title = str(row.get("title") or (audience.get("titles") or ["Intended buyer"] * 3)[index])
        buyers.append(
            {
                "id": f"buyer_{objection}",
                "name": name,
                "segment": audience["roles"][0] if audience["roles"] else "buyer",
                "title": title,
                "is_icp": True,
                "objection": objection,
                "trait": {
                    "proof": "hates slogans without numbers",
                    "price": "will not click when the price is missing",
                    "ranking": "rejects unsourced ranking claims",
                }[objection],
            }
        )
    leak_row = (llm or {}).get("leak") or {}
    leak_name = str(leak_row.get("name") or "Jules")
    buyers.append(
        {
            "id": "leak",
            "name": leak_name,
            "segment": leak_role,
            "title": str(leak_row.get("title") or audience.get("leak_title") or "Not a buyer"),
            "is_icp": False,
            "objection": "leak",
            "trait": "likes ads that sound broadly cool and would click without buying",
        }
    )
    return buyers


def _proof_line(brief: str, company: str) -> str:
    match = re.search(r"(?:proof|trusted by|used by)[:\s]+([^\.]{8,80})", brief, re.I)
    if match:
        return match.group(0).strip().rstrip(".")
    return f"A concrete number for {company} — not a ranking claim."
