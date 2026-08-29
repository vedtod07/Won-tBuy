import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed; env vars still work
    pass


class CacheFallback(RuntimeError):
    pass


def use_cache_requested(use_cache: bool = False) -> bool:
    if use_cache:
        return True
    return os.getenv("USE_CACHE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _live_api_key() -> str | None:
    """Return the first configured key, preferring Gemini when it looks like one."""
    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if gemini_key:
        return gemini_key
    return (os.getenv("LLM_API_KEY") or "").strip()


def live_key_present() -> bool:
    return bool(_live_api_key()) and not use_cache_requested()


def chat_json(system: str, user: str, use_cache: bool = False) -> dict:
    """One chat helper for every agent (personas, critic, optimizer).

    Calls Gemini generateContent when the key starts with 'AIza', otherwise
    falls back to a generic OpenAI-compatible endpoint. Raises CacheFallback
    when the key is missing or cache mode is requested, so callers use their
    fixture/cached_verdict path instead of crashing.
    """
    api_key = _live_api_key()
    if use_cache_requested(use_cache) or not api_key:
        raise CacheFallback("Cached fixtures requested or no API key")

    is_gemini = api_key.startswith("AIza")
    try:
        if is_gemini:
            return _gemini_chat_json(api_key, system, user)
        return _openai_chat_json(api_key, system, user)
    except CacheFallback:
        raise
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CacheFallback("LLM response unavailable") from error


def _gemini_chat_json(api_key: str, system: str, user: str) -> dict:
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    prompt = f"{system}\n\n{user}"
    request = Request(
        url,
        data=json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json_object(text)


def _openai_chat_json(api_key: str, system: str, user: str) -> dict:
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
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    return _parse_json_object(payload["choices"][0]["message"]["content"])


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("LLM response was not an object")
    return result
