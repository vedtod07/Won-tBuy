"""Turn a free-text brief into a lab: brand, price, audience, shoppers.

Never invent a Northline price. If the human wrote 49 pounds, the lab
uses from £49/mo — including typos like 'moth' for 'month'.
When a live model is present it names the audience; there is no industry lookup table.
"""

from __future__ import annotations

import random
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
CURRENCY_TOKEN = r"[€$£₹]"


def _price_is_monthly(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 16) : min(len(text), end + 32)]
    return bool(re.search(rf"(?:/\s*{MONTH}\b|\bper\s+{MONTH}\b|\b{MONTH}\b)", window, re.I))


def _price_label(symbol: str, amount: str, monthly: bool) -> str:
    return f"from {symbol}{amount}/mo" if monthly else f"from {symbol}{amount}"


def parse_price(brief: str) -> str | None:
    """Normalize a price from messy human text. Returns None if none is present."""
    text = brief.replace(",", " ")
    words = "|".join(pattern for pattern, _symbol in CURRENCY_WORDS)

    match = re.search(
        rf"({CURRENCY_TOKEN})\s*(\d+(?:\.\d+)?)\s*(?:/\s*|\s+per\s+){MONTH}\b",
        text,
        re.I,
    )
    if match:
        return f"from {match.group(1)}{match.group(2)}/mo"

    match = re.search(
        rf"({CURRENCY_TOKEN})\s*(\d+(?:\.\d+)?)\s*/\s*{MONTH}\b",
        text,
        re.I,
    )
    if match:
        return f"from {match.group(1)}{match.group(2)}/mo"

    match = re.search(
        rf"(?:ranges?\s+from\s+|from\s+)?"
        rf"(?:{CURRENCY_TOKEN}\s*)?(\d+(?:\.\d+)?)\s*(?:{words})?"
        rf"\s*(?:to|–|—|-|up\s*to|upto)\s*"
        rf"(?:up\s*to|upto)?\s*"
        rf"(?:{CURRENCY_TOKEN}\s*)?(\d+(?:\.\d+)?)\s*({words}|{CURRENCY_TOKEN})?",
        text,
        re.I,
    )
    if match:
        blob = match.group(0)
        unit = match.group(3) or ""
        if not unit and not re.search(rf"{CURRENCY_TOKEN}|{words}", blob, re.I):
            match = None
    if match:
        unit = match.group(3) or ""
        if unit in {"€", "$", "£", "₹"}:
            symbol = unit
        elif unit:
            symbol = _symbol_for_word(unit)
        elif "$" in match.group(0):
            symbol = "$"
        elif "£" in match.group(0):
            symbol = "£"
        elif "€" in match.group(0):
            symbol = "€"
        else:
            symbol = "$"
        return _price_label(symbol, match.group(1), _price_is_monthly(text, *match.span()))

    match = re.search(
        rf"(\d+(?:\.\d+)?)\s*({words})\s*(?:/\s*|\s+per\s+)?(?:{MONTH})?\b",
        text,
        re.I,
    )
    if match:
        return _price_label(
            _symbol_for_word(match.group(2)),
            match.group(1),
            _price_is_monthly(text, *match.span()),
        )

    match = re.search(rf"(?:from\s+)?({CURRENCY_TOKEN})\s*(\d+(?:\.\d+)?)", text, re.I)
    if match:
        return _price_label(match.group(1), match.group(2), _price_is_monthly(text, *match.span()))

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
            "There is NO default industry and NO default shopper. Infer who should buy from this text only "
            "(age, gifts, job, store type — whatever is written). "
            "Never return plant_manager, factory, operating system, Klaus, Jules, or Northline "
            "unless those words are in the brief. "
            "The leak is someone who would click THIS ad but is not the buyer you named "
            "(a window-shopper, a teen, a competitor — infer from THIS product, not from a previous lab). "
            "Never invent a price that is not in the brief. Never use 199 unless the brief says 199. "
            "If they give a range (100 to 5000 dollars), price is from $100 — do not add /mo unless they said month. "
            "Company is the name before a colon (Reachify:Marketing → Reachify). "
            "If they wrote 'audience includes', that is who should buy — not the words after 'for' if those are a purpose. "
            "Normalize price: pounds→£, dollars→$, euros→€, per month/moth/mo→/mo, prefix 'from '. "
            "Invent three intended-buyer names with titles that match THIS audience, and one leak who is not a buyer.\n"
            "Return {\n"
            '  "reasoning": "two first-person sentences: brand, price you read, who should see it, who is the leak",\n'
            '  "company": "brand",\n'
            '  "product": "one sentence",\n'
            '  "price": "from £49/mo or null",\n'
            '  "audience_label": "who should buy, in their words",\n'
            '  "tight_targeting": {"industries": ["slug"], "roles": ["slug"], "regions": ["slug"]},\n'
            '  "leak_role": "slug",\n'
            '  "buyers": [{"name": "str", "title": "who they are · why they buy this", "objection": "proof|price|ranking"}],\n'
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
            "No live model this run — I parsed brand, price, and who should buy it from your brief, "
            "not from a fixed industry list. "
            + briefing["reasoning"]
        )
    return briefing


def assemble_briefing(brief: str, parsed_price: str | None, llm: dict | None) -> dict:
    company = _company(brief, llm)
    product = ""
    if llm:
        product = str(llm.get("product") or "").strip()
        if len(product) > 90 or "..." in product or "pricing" in product.lower():
            product = ""
    if not product:
        product = _product_line(brief, company)

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
    audience = _apply_who_clauses(brief, audience)
    leak_role, llm = _scrub_factory_bleed(brief, llm, audience)
    leak_role = str(leak_role or audience["leak_role"])
    leak_role = re.sub(r"[^a-z0-9_]+", "_", leak_role.lower()).strip("_") or "window_shopper"

    tight = Targeting.model_validate(
        {
            "industries": audience["industries"],
            "roles": audience["roles"],
            "company_sizes": SIZES,
            "regions": audience["regions"],
        }
    )
    if leak_role in tight.roles:
        leak_role = "window_shopper"
    leaky_roles = list(dict.fromkeys([*tight.roles, leak_role]))
    leaky = Targeting(
        industries=list(tight.industries),
        roles=leaky_roles,
        company_sizes=SIZES,
        regions=list(tight.regions),
    )

    audience_short = _headline_audience(audience["label"])
    headline_core = f"The #1 {company} for {audience_short}"
    if len(headline_core) > 72:
        headline_core = f"The #1 {company}"
    ad_body = (
        f"{product.rstrip('.')}. For {audience['label']}. "
        f"{company} — the one everyone is switching to."
    )
    if len(ad_body) > 220:
        ad_body = f"{company} for {audience['label']}. The one everyone is switching to."
    campaign = Campaign(
        company=company,
        targeting=leaky,
        ad=Creative(headline=headline_core[:140], body=ad_body, cta="Learn more"),
        page=LandingPage(
            headline=headline_core[:140],
            body=ad_body,
            bullets=[],
            proof=None,
            cta="Learn more",
            price=None,
        ),
    )

    personas = _shoppers(brief, llm, audience, leak_role, product, company)
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
        "cta": infer_cta(brief, product),
        "interpreted_by": "llm" if llm else "offline",
    }


def _company(brief: str, llm: dict | None) -> str:
    name = ""
    if llm:
        name = str(llm.get("company") or "").strip().strip(".,;:")
    if not name:
        text = brief.replace("\n", " ").strip()
        if ":" in text[:56]:
            name = text.split(":", 1)[0].strip()
        else:
            name = text.split(" ")[0].strip(",.!?:;")
    if ":" in name:
        name = name.split(":", 1)[0].strip()
    return (name or "Your product")[:40]


def _product_line(brief: str, company: str) -> str:
    rest = brief.replace("\n", " ").strip()
    if rest.lower().startswith(company.lower()):
        rest = rest[len(company) :].lstrip(" :")
    rest = re.split(r"\baudience\b|\bpricing\b|\bprices?\b", rest, maxsplit=1, flags=re.I)[0]
    rest = re.split(r"\.{2,}|\u2026", rest, maxsplit=1)[0]
    rest = rest.split(".")[0]
    rest = re.split(
        r"\bto (?:increase|grow|boost|expand|help|get|reach)\b",
        rest,
        maxsplit=1,
        flags=re.I,
    )[0]
    rest = re.sub(r"\s+", " ", rest).strip(" :.-")
    if len(rest) > 72:
        rest = rest[:70].rsplit(" ", 1)[0]
    return rest or company


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")[:40]


def _industry_from_label(label: str) -> str:
    low = label.lower()
    if "store" in low or "shop" in low:
        return "local_retail"
    slug = _slug(label)
    return slug.split("_")[0] or "local"


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
    if not _factory_brief(brief):
        roles = [
            role
            for role in roles
            if not re.search(r"plant_manager|operations_manager|^factory$", role)
        ]
        industries = [
            item
            for item in industries
            if not re.search(r"plant_manager|^factory$|^manufacturing$", item)
        ]
    if not roles and not industries and not llm.get("audience_label"):
        return None
    label = str(llm.get("audience_label") or "").strip() or ", ".join(roles).replace("_", " ")
    if not _factory_brief(brief) and _NORTHLINE_VOICE.search(label):
        label = _who_from_brief(brief)
    leak = llm.get("leak") if isinstance(llm.get("leak"), dict) else {}
    leak_role = str(llm.get("leak_role") or "window_shopper")
    leak_title = str(leak.get("title") or "Not the buyer")
    if not _factory_brief(brief) and (_NORTHLINE_VOICE.search(leak_role) or _NORTHLINE_VOICE.search(leak_title)):
        leak_role = "window_shopper"
        leak_title = f"Not {label[:50]} — will click and never buy"
    return {
        "industries": (industries or ["consumer"])[:3],
        "roles": (roles or ["buyer"])[:4],
        "regions": regions[:3],
        "label": label or "intended buyers",
        "titles": [str(row.get("title") or "") for row in buyers] or _buyer_titles(label),
        "leak_role": leak_role,
        "leak_title": leak_title,
    }


_NORTHLINE_VOICE = re.compile(
    r"plant[_\s-]?manager|operations_manager|operating system|\bnorthline\b|industrial plant",
    re.I,
)


def _factory_brief(brief: str) -> bool:
    return bool(
        re.search(
            r"\bfactor(?:y|ies)\b|\bplant managers?\b|\bdowntime\b|\bmanufactur|\boee\b|\bshift board\b",
            brief,
            re.I,
        )
    )


def _scrub_factory_bleed(brief: str, llm: dict | None, audience: dict) -> tuple[str, dict | None]:
    leak_role = str((llm or {}).get("leak_role") or audience.get("leak_role") or "window_shopper")
    if _factory_brief(brief) or llm is None:
        return leak_role, llm
    patched = dict(llm)
    leak = dict(patched.get("leak") or {}) if isinstance(patched.get("leak"), dict) else {}
    leak_title = str(leak.get("title") or audience.get("leak_title") or "")
    if _NORTHLINE_VOICE.search(leak_role) or _NORTHLINE_VOICE.search(leak_title):
        leak_role = "window_shopper"
        leak["title"] = f"Not {audience['label'][:50]} — will click and never buy"
        patched["leak"] = leak
        patched["leak_role"] = leak_role
    buyers = []
    for row in list(patched.get("buyers") or []):
        title = str((row or {}).get("title") or "")
        if _NORTHLINE_VOICE.search(title):
            fallback = audience.get("titles") or ["Intended buyer"]
            row = {**row, "title": fallback[0] if isinstance(fallback, list) else fallback}
        buyers.append(row)
    if buyers:
        patched["buyers"] = buyers
    reasoning = str(patched.get("reasoning") or "")
    if _NORTHLINE_VOICE.search(reasoning):
        patched["reasoning"] = (
            f"I read this as {audience['label']}. Leak is a window-shopper who would click and never buy — "
            "not a factory role."
        )
    return leak_role, patched


def _clause_end(who: str) -> str:
    who = re.split(r"\.{2,}|\u2026", who, maxsplit=1)[0]
    who = who.split(".")[0]
    who = re.split(r"\bfrom\b|\bstarting\b|\bpricing\b|\bprices?\b", who, maxsplit=1, flags=re.I)[0]
    who = re.split(
        r"\bto (?:increase|grow|boost|expand|help|get)\b",
        who,
        maxsplit=1,
        flags=re.I,
    )[0]
    who = re.split(r"\d+\s*(?:dollars?|pounds?|euros?|usd|gbp)", who, maxsplit=1)[0]
    return who.strip(" .,;:—-")


_CUSTOM_NAMES = (
    "Samira",
    "Kenji",
    "Elena",
    "Tomas",
    "Nia",
    "Haruto",
    "Lila",
    "Omar",
    "Ines",
    "Diego",
    "Asha",
    "Ravi",
    "Sofi",
    "Marek",
    "Yara",
    "Luca",
    "Noor",
    "Pavel",
    "Chioma",
    "Hugo",
)

_DEMO_TELL_NAMES = {
    "priya",
    "owen",
    "mina",
    "klaus",
    "anika",
    "mateo",
    "jules",
    "alex",
    "lena",
}


def _parse_who_clauses(brief: str) -> dict:
    buyer = None
    leak = None
    match = re.search(r"\bbuyers?:\s*([^.;\n]+)", brief, re.I)
    if match:
        buyer = match.group(1).strip()[:80]
    match = re.search(r"\bleak:\s*([^.;\n]+)", brief, re.I)
    if match:
        leak = match.group(1).strip()[:80]
    if not leak:
        match = re.search(r"\bwrong[- ]eyes:\s*([^.;\n]+)", brief, re.I)
        if match:
            leak = match.group(1).strip()[:80]
    return {"buyer_phrase": buyer, "leak_phrase": leak}


def _apply_who_clauses(brief: str, audience: dict) -> dict:
    clauses = _parse_who_clauses(brief)
    patched = dict(audience)
    if clauses.get("buyer_phrase"):
        patched["label"] = clauses["buyer_phrase"]
        patched["titles"] = _buyer_titles(patched["label"])
        roles = _roles_from_who(clauses["buyer_phrase"])
        if roles:
            patched["roles"] = roles
    if clauses.get("leak_phrase"):
        patched["leak_role"] = _slug(clauses["leak_phrase"]) or "window_shopper"
        patched["leak_title"] = clauses["leak_phrase"]
    return patched


def _shopper_names(company: str, audience: str) -> list[str]:
    rng = random.Random(f"{company.lower()}|{audience.lower()}")
    pool = list(_CUSTOM_NAMES)
    rng.shuffle(pool)
    return pool[:4]


def _clean_person_name(name: str, fallback: str, brief: str) -> str:
    cleaned = str(name or "").strip()
    if not cleaned:
        return fallback
    if cleaned.lower() in _DEMO_TELL_NAMES and not _factory_brief(brief):
        return fallback
    return cleaned[:40]


def _who_from_brief(brief: str) -> str:
    clauses = _parse_who_clauses(brief)
    if clauses.get("buyer_phrase") and len(clauses["buyer_phrase"]) >= 4:
        return clauses["buyer_phrase"][:80]
    match = re.search(r"\baudience(?:\s+includes|\s+is|:)?\s+(.+)", brief, re.I)
    if match:
        who = _clause_end(match.group(1))
        if len(who) >= 6:
            return who[:80]
    for pattern in (
        r"\baimed at\s+(.+)",
        r"\bfor\s+(.+)",
        r"\btarget(?:ing|s|ed)?\s+(.+)",
    ):
        match = re.search(pattern, brief, re.I)
        if not match:
            continue
        who = _clause_end(match.group(1))
        if len(who) >= 4:
            return who[:80]
    parts = brief.split(":", 1)
    if len(parts) > 1:
        rest = _clause_end(parts[1])
        if len(rest) >= 8:
            return rest[:80]
    return _clause_end(brief.split(".")[0])[:80] or "the buyers named in the brief"


def _headline_audience(label: str) -> str:
    short = re.split(
        r"\b(?:offering|selling|providing|who|aged|at)\b",
        label,
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    if len(short) > 32:
        short = short[:32].rsplit(" ", 1)[0] or short[:32]
    return short or label[:32]


def _voice_job(label: str) -> str:
    job = _headline_audience(label).lower()
    for plural, singular in (
        ("owners", "owner"),
        ("managers", "manager"),
        ("professionals", "professional"),
        ("parents", "parent"),
        ("cooks", "cook"),
        ("students", "student"),
        ("stores", "store"),
        ("shops", "shop"),
        ("brides and grooms", "bride or groom"),
        ("brides", "bride"),
        ("grooms", "groom"),
    ):
        job = re.sub(rf"\b{plural}\b", singular, job)
    job = re.sub(r"\s+", " ", job).strip()
    if len(job.split()) <= 4 and re.search(r"\b(store|shop|cafe)\b", job) and "owner" not in job:
        job = f"{job} owner"
    return job or "buyer"


def _buyer_titles(label: str) -> list[str]:
    job = _voice_job(label)
    display = job[:1].upper() + job[1:] if job else "Intended buyer"
    if display.lower().startswith("hr "):
        display = "HR " + display[3:]
    if display.lower().startswith("gcse "):
        display = "GCSE " + display[5:]
    return [display, display, display]


def _roles_from_who(who: str) -> list[str]:
    """Role slugs taken from words that actually appear in the audience phrase."""
    tokens = re.findall(r"[a-z0-9]+", who.lower())
    blob = " ".join(tokens)
    roles: list[str] = []
    if "cafe" in blob or "coffee" in blob:
        roles.append("cafe_owner")
    if "parent" in blob:
        roles.append("parent")
    if "cook" in blob:
        roles.append("home_cook")
    if "professional" in blob:
        roles.append("professional")
    if "bride" in blob or "groom" in blob or "wedding" in blob:
        roles.append("couple")
    if "hr" in tokens:
        roles.append("hr_manager")
    if "student" in blob or "gcse" in tokens:
        roles.append("student")
    for marker in (
        "owner",
        "manager",
        "buyer",
        "partner",
        "dentist",
        "founder",
        "headteacher",
        "teacher",
        "chef",
        "principal",
    ):
        if marker in tokens or marker in blob:
            roles.append(marker)
    if any(token.startswith("store") or token.startswith("shop") for token in tokens):
        roles.extend(["store_owner", "store_manager"])
    if "plant" in tokens and "manager" in tokens:
        roles.append("plant_manager")
    if "gift" in tokens or "gifts" in tokens:
        roles.append("gift_buyer")
    if "adult" in tokens or "adults" in tokens:
        roles.append("young_adult")
    if not roles:
        roles = ["buyer"]
    return list(dict.fromkeys(roles))[:4]


def _audience_from_for_clause(brief: str, region: list[str]) -> dict:
    label = _who_from_brief(brief)
    roles = _roles_from_who(label)
    industry = _industry_from_label(label)
    return {
        "industries": [industry],
        "roles": roles,
        "regions": region,
        "label": label,
        "titles": _buyer_titles(label),
        "leak_role": "window_shopper",
        "leak_title": f"Not {label[:50]} — will click and never buy",
    }


def _shoppers(
    brief: str,
    llm: dict | None,
    audience: dict,
    leak_role: str,
    product: str,
    company: str = "",
) -> list[dict]:
    names = _shopper_names(company or "campaign", audience.get("label") or "buyers")
    job_titles = audience.get("titles") or _buyer_titles(audience["label"])
    while len(job_titles) < 3:
        job_titles.append(job_titles[-1] if job_titles else "Intended buyer")
    angles = (
        (f"{job_titles[0]} · wants a real number, not a slogan", "proof", "hates slogans without numbers"),
        (f"{job_titles[1]} · will not click without a price", "price", "will not click when the price is missing"),
        (f"{job_titles[2]} · rejects unsourced ranking", "ranking", "rejects unsourced ranking claims"),
    )
    buyers = []
    llm_buyers = list((llm or {}).get("buyers") or [])
    for index, (fallback_title, objection, trait) in enumerate(angles):
        row = llm_buyers[index] if index < len(llm_buyers) else {}
        title = str(row.get("title") or "").strip() or fallback_title
        if not _factory_brief(brief) and _NORTHLINE_VOICE.search(title):
            title = fallback_title
        buyers.append(
            {
                "id": f"buyer_{objection}",
                "name": _clean_person_name(row.get("name"), names[index], brief),
                "segment": audience["roles"][0] if audience["roles"] else "buyer",
                "title": title,
                "audience_label": audience["label"],
                "product": product,
                "is_icp": True,
                "objection": objection,
                "trait": trait,
            }
        )
    leak_row = (llm or {}).get("leak") or {}
    leak_title = str(
        leak_row.get("title")
        or audience.get("leak_title")
        or f"Not {audience['label'][:40]} — would click and never buy"
    )
    if not _factory_brief(brief) and _NORTHLINE_VOICE.search(leak_title):
        leak_title = f"Not {audience['label'][:40]} — would click and never buy"
    buyers.append(
        {
            "id": "leak",
            "name": _clean_person_name(leak_row.get("name"), names[3], brief),
            "segment": leak_role,
            "title": leak_title,
            "audience_label": audience["label"],
            "product": product,
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


def infer_cta(brief: str, product: str = "") -> str:
    """CTA that fits the offer. Northline-style B2B stays Book a demo."""
    blob = f"{brief} {product}".lower()
    if re.search(r"\bwhitening\b|\bdentists?\b|\bdental\b|\bclinic\b|\bappointment\b", blob):
        return "Book an appointment"
    if re.search(r"\bmugs?\b|\bhandmade\b|\bfloral\b|\bflowers?\b|\bgifts?\b", blob):
        return "Shop now"
    if re.search(r"\btutor|\bcourse\b|\benroll\b|\bgcse\b", blob):
        return "Enroll"
    if re.search(r"\bgym\b|\bmembership\b", blob):
        return "Book a class"
    if re.search(r"\bcafe\b|\bcoffee\b|\bwholesale\b", blob):
        return "Request a sample"
    return "Book a demo"
