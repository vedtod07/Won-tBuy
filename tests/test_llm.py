"""LLM retry helpers and status shape."""

from types import SimpleNamespace

from app.llm import _retry_after_seconds, llm_status, rate_limited


def test_retry_after_reads_header():
    error = SimpleNamespace(headers={"Retry-After": "3"})
    assert _retry_after_seconds(error) == 3.0


def test_retry_after_defaults_when_missing():
    error = SimpleNamespace(headers={})
    assert _retry_after_seconds(error) == 30.0


def test_quota_reason_credits_vs_generic_429():
    from app.llm import _quota_reason

    assert "prepaid credits" in _quota_reason(
        429,
        '{"error":{"message":"Your prepayment credits are depleted."}}',
    )
    assert _quota_reason(429, '{"error":{"status":"RESOURCE_EXHAUSTED"}}') == "LLM HTTP 429"


def test_llm_status_has_rate_limited_and_model():
    status = llm_status()
    assert "live" in status
    assert "rate_limited" in status
    assert "model" in status
    assert "mode" in status
    assert status["mode"] in {"live", "cached", "rate_limited"}
    assert isinstance(rate_limited(), bool)
