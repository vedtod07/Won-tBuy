from app.llm import CacheFallback, chat_json


def critic_summary(targeting_accuracy: float, use_cache: bool = False) -> str:
    result = chat_json(
        "You are a concise funnel critic. Return JSON only and never change the supplied metric.",
        (
            f"The code-computed targeting_accuracy is {targeting_accuracy}%. "
            "Return {\"summary\": \"one sentence interpreting targeting quality\"}."
        ),
        use_cache=use_cache,
    )
    summary = str(result.get("summary", "")).strip()
    if not summary:
        raise CacheFallback("Critic returned no summary")
    return " ".join(summary.splitlines())


def cached_critic_summary(targeting_accuracy: float) -> str:
    if targeting_accuracy < 60:
        return f"Only {targeting_accuracy}% of simulated impressions reached the ICP, showing a costly targeting leak."
    return f"{targeting_accuracy}% of simulated impressions reached the ICP after targeting was tightened."
