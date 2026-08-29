import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CacheFallback(RuntimeError):
    pass


def chat_json(system: str, user: str) -> dict:
    api_key = os.getenv("LLM_API_KEY")
    use_cache = os.getenv("USE_CACHE", "0").strip().lower() in {"1", "true", "yes", "on"}
    if use_cache or not api_key:
        raise CacheFallback("Cached fixtures requested or LLM_API_KEY is missing")

    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
        result = json.loads(payload["choices"][0]["message"]["content"])
        if not isinstance(result, dict):
            raise ValueError("LLM response was not an object")
        return result
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CacheFallback("LLM response unavailable") from error
