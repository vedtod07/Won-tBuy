import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed; env vars still work
    pass


class CacheFallback(RuntimeError):
    pass


# Tracks the most recent HTTP 429 so /api/status can surface "rate-limited".
_RATE_LIMIT = {"at": 0.0, "retry_after": 0.0}

MAX_RETRIES = 2
MAX_BACKOFF_SECONDS = 5.0


def rate_limited() -> bool:
    """True while the last 429's cooldown has not elapsed."""
    if _RATE_LIMIT["retry_after"] <= 0:
        return False
    return time.monotonic() - _RATE_LIMIT["at"] < _RATE_LIMIT["retry_after"]


def current_model() -> str:
    key = _live_api_key() or ""
    if key.startswith("AIza"):
        return os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    return os.getenv("LLM_MODEL", "gpt-4o-mini")


_last_call: dict = {
    "model": None,
    "live_or_cache": "cache",
    "latency_ms": 0,
}


def _mark_rate_limited(retry_after: float | None) -> None:
    _RATE_LIMIT["at"] = time.monotonic()
    _RATE_LIMIT["retry_after"] = max(0.0, float(retry_after or 30.0))


def last_call_meta() -> dict:
    live_or_cache = _last_call.get("live_or_cache") or "cache"
    return {
        "model": current_model() if live_or_cache == "live" else "cache",
        "live_or_cache": live_or_cache,
        "latency_ms": int(_last_call.get("latency_ms") or 0),
    }


def llm_status() -> dict:
    live = live_key_present()
    limited = rate_limited()
    if live and limited:
        mode = "rate_limited"
    elif live:
        mode = "live"
    else:
        mode = "cached"
    return {
        "live": live,
        "rate_limited": limited,
        "model": current_model(),
        "mode": mode,
    }


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
    started = time.perf_counter()
    if use_cache_requested(use_cache) or not api_key:
        _last_call.update({"live_or_cache": "cache", "latency_ms": 0, "model": "cache"})
        raise CacheFallback("Cached fixtures requested or no API key")

    is_gemini = api_key.startswith("AIza")
    was_limited = rate_limited()
    attempt = 0
    while True:
        try:
            if is_gemini:
                result = _gemini_chat_json(api_key, system, user)
            else:
                result = _openai_chat_json(api_key, system, user)
            _last_call.update({
                "live_or_cache": "live",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "model": current_model(),
            })
            return result
        except CacheFallback:
            _last_call.update({
                "live_or_cache": "cache",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "model": "cache",
            })
            raise
        except HTTPError as error:
            body = ""
            try:
                body = error.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if error.code == 429:
                retry_after = _retry_after_seconds(error)
                _mark_rate_limited(retry_after)
                # Retry only when the server promises a short cooldown. The
                # free tier returns tens of seconds, so a retry would always
                # fail again — fall back instantly instead of freezing a demo
                # on multi-second sleeps. Billing/credit 429s also skip retry.
                if (
                    retry_after <= MAX_BACKOFF_SECONDS
                    and not was_limited
                    and attempt < MAX_RETRIES
                    and "credit" not in body.lower()
                ):
                    attempt += 1
                    time.sleep(retry_after)
                    continue
            _last_call.update({
                "live_or_cache": "cache",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "model": "cache",
            })
            raise CacheFallback(_quota_reason(error.code, body)) from error
        except (URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            _last_call.update({
                "live_or_cache": "cache",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "model": "cache",
            })
            raise CacheFallback("LLM response unavailable") from error


def _retry_after_seconds(error: HTTPError) -> float:
    header = error.headers.get("Retry-After", "") if error.headers else ""
    try:
        if header:
            return float(header)
    except ValueError:
        pass
    return 30.0


def _quota_reason(code: int, body: str) -> str:
    lowered = (body or "").lower()
    if "prepayment credits are depleted" in lowered or "credits are depleted" in lowered:
        return "LLM HTTP 429: prepaid credits depleted — add credit in AI Studio"
    if "free_tier" in lowered or "free tier" in lowered:
        return "LLM HTTP 429: free-tier quota exhausted"
    return f"LLM HTTP {code}"


def _gemini_chat_json(api_key: str, system: str, user: str) -> dict:
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
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
