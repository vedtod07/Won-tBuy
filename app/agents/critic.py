import json

from app.llm import CacheFallback, chat_json


NORTHLINE_IDS = {"klaus", "anika", "mateo", "jules"}


def _northline_cast(personas: list | None) -> bool:
    return any((row or {}).get("id") in NORTHLINE_IDS for row in (personas or []))


def critic_summary(
    targeting_accuracy: float,
    use_cache: bool = False,
    personas: list | None = None,
    round_number: int = 1,
    company: str | None = None,
    audience_label: str | None = None,
) -> str:
    compact = [
        {
            "name": row.get("name"),
            "title": row.get("title"),
            "reached": row.get("reached"),
            "would_click": row.get("would_click"),
            "is_icp": row.get("is_icp"),
            "quote": row.get("quote"),
            "objection": row.get("objection"),
        }
        for row in (personas or [])
    ]
    brand = company or "this product"
    audience = audience_label or "the intended buyers"
    result = chat_json(
        (
            "You are the funnel critic. Return JSON only. Never change targeting_accuracy. "
            "Separate wrong eyes (who saw it) from wrong words (who would click). "
            "Talk about THIS company and THESE shoppers. Never mention factories, plant managers, "
            "or operating systems unless those strings appear in the personas. "
            "Never write the phrase 'two failures, same campaign'."
        ),
        (
            f"Company: {brand}. Intended audience: {audience}. "
            f"targeting_accuracy is {targeting_accuracy}%. Round {round_number}. "
            f"Personas: {json.dumps(compact)}. "
            'Return {"summary": "two sentences: first the %, then leak vs buyers in this product\'s voice"}.'
        ),
        use_cache=use_cache,
    )
    summary = str(result.get("summary", "")).strip()
    if not summary:
        raise CacheFallback("Critic returned no summary")
    if not _northline_cast(personas) and "two failures" in summary.lower():
        raise CacheFallback("Critic reused the factory template")
    if f"{targeting_accuracy}" not in summary and f"{targeting_accuracy:.0f}" not in summary:
        summary = f"{targeting_accuracy}%. {summary}"
    return " ".join(summary.splitlines())


def cached_critic_summary(
    targeting_accuracy: float,
    round_number: int = 1,
    personas: list | None = None,
    company: str | None = None,
    audience_label: str | None = None,
) -> str:
    rows = personas or []
    leak = next((row for row in rows if row.get("is_icp") is False), None)
    leak_name = (leak or {}).get("name") or "the leak"
    buyers = [row for row in rows if row.get("is_icp")]
    buyer_names = ", ".join(row.get("name") or "buyer" for row in buyers) or "the intended buyers"
    if _northline_cast(rows):
        if round_number <= 1:
            return (
                f"Only {targeting_accuracy}% of simulated impressions reached the ICP, showing a costly targeting leak. "
                f"{leak_name} would click while {buyer_names} would not — two failures, same campaign."
            )
        if round_number == 2:
            return (
                f"{targeting_accuracy}% of simulated impressions reached the ICP after targeting was tightened. "
                f"The words are still why {buyer_names} refuse."
            )
        return (
            f"{targeting_accuracy}% of simulated impressions reached the ICP after targeting was tightened. "
            f"Copy is why the buyers would click; {leak_name} was not reached."
        )

    brand = company or "this product"
    audience = audience_label or "the intended buyers"
    leak_title = str((leak or {}).get("title") or "not a buyer").split("·")[0].strip()
    if round_number <= 1:
        return (
            f"Only {targeting_accuracy}% of simulated impressions reached {audience}. "
            f"{leak_name} ({leak_title}) would click {brand} and never buy, while {buyer_names} — "
            f"the actual {audience} — would not: missing price and an unsourced #1."
        )
    if round_number == 2:
        return (
            f"{targeting_accuracy}% of simulated impressions now reach {audience}. "
            f"{leak_name} is out. Copy is still why {buyer_names} refuse {brand}."
        )
    return (
        f"{targeting_accuracy}% of simulated impressions still reach {audience}. "
        f"Copy is why {buyer_names} would click {brand}; {leak_name} was not reached."
    )
