import json

from app.llm import CacheFallback, chat_json


def critic_summary(
    targeting_accuracy: float,
    use_cache: bool = False,
    personas: list | None = None,
    round_number: int = 1,
) -> str:
    compact = [
        {
            "name": row.get("name"),
            "reached": row.get("reached"),
            "would_click": row.get("would_click"),
            "is_icp": row.get("is_icp"),
        }
        for row in (personas or [])
    ]
    result = chat_json(
        (
            "You are the funnel critic. Return JSON only. Never change targeting_accuracy. "
            "Separate wrong eyes (who saw it) from wrong words (who would click)."
        ),
        (
            f"targeting_accuracy is {targeting_accuracy}%. Round {round_number}. "
            f"Personas: {json.dumps(compact)}. "
            'Return {"summary": "two sentences: first the %, then eyes vs words"}.'
        ),
        use_cache=use_cache,
    )
    summary = str(result.get("summary", "")).strip()
    if not summary:
        raise CacheFallback("Critic returned no summary")
    if f"{targeting_accuracy}" not in summary and f"{targeting_accuracy:.0f}" not in summary:
        summary = f"{targeting_accuracy}%. {summary}"
    return " ".join(summary.splitlines())


def cached_critic_summary(
    targeting_accuracy: float,
    round_number: int = 1,
    personas: list | None = None,
) -> str:
    rows = personas or []
    leak = next((row for row in rows if row.get("is_icp") is False), None)
    leak_name = (leak or {}).get("name") or "the leak"
    buyers = [row for row in rows if row.get("is_icp")]
    buyer_names = ", ".join(row.get("name") or "buyer" for row in buyers) or "the intended buyers"
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
