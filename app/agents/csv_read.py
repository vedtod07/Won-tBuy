"""Live model reads a campaign CSV. Totals stay summed in code."""

from __future__ import annotations

import csv
import io

from app.impressions import inspect_campaign_csv
from app.llm import CacheFallback, chat_json, last_call_meta, live_key_present, use_cache_requested

_SYSTEM = (
    "You read one paid-ads CSV export for a simulated marketing lab. Return JSON only. "
    "Never invent spend, impressions, or CPC totals — code already summed those. "
    "You may map messy headers onto spend, impressions, and cpc. "
    "Read campaign names for who this was aimed at and who might be wasted reach. "
    "Do not claim live ads were pulled. Do not reuse Northline or plant managers "
    "unless those words appear in the CSV."
)


def interpret_campaign_csv(text: str, use_cache: bool = False) -> dict:
    """Inspect the file in code, then ask the live model to read it."""
    report = inspect_campaign_csv(text)
    payload = None
    live = live_key_present() and not use_cache_requested(use_cache)
    if live:
        try:
            result = chat_json(_SYSTEM, _csv_prompt(text, report), use_cache=False)
            if isinstance(result, dict):
                payload = result
        except CacheFallback:
            payload = None
        except (KeyError, TypeError, ValueError):
            payload = None
    if payload and not report.get("ok"):
        remapped = _inspect_using_llm_map(text, payload.get("mapped") or {})
        if remapped.get("ok"):
            warnings = list(remapped.get("warnings") or [])
            warnings.append("Column map came from the live model. Totals were still summed in code.")
            remapped["warnings"] = warnings
            report = remapped
    report["interpreted_by"] = "llm" if payload else "offline"
    report["read"] = _read_from_payload(payload) if payload else {}
    if payload:
        reasoning = str(payload.get("reasoning") or "").strip()
        report["reasoning"] = reasoning or _offline_reasoning(report)
        meta = last_call_meta()
        report["model"] = meta.get("model")
        report["live_or_cache"] = meta.get("live_or_cache")
        report["latency_ms"] = meta.get("latency_ms")
    else:
        report["reasoning"] = _offline_reasoning(report)
        report["model"] = "cache"
        report["live_or_cache"] = "cache"
        report["latency_ms"] = 0
    return report


def _csv_prompt(text: str, report: dict) -> str:
    snippet = str(text or "").lstrip("\ufeff").strip()
    if len(snippet) > 3500:
        snippet = snippet[:3500] + "\n…(truncated)"
    return (
        f"CSV:\n{snippet}\n\n"
        f"Code mapped columns: {report.get('mapped')}\n"
        f"Code totals (do not replace these numbers): {report.get('totals')}\n"
        f"Code ok: {report.get('ok')} error: {report.get('error')}\n\n"
        "If mapping is wrong or missing, return better mapped column names from the header. "
        "Do not invent numeric totals.\n"
        "Return {\n"
        '  "reasoning": "two first-person sentences: I read this export as …, spend/impressions I see in the file, who it looks aimed at, who might be wasted reach",\n'
        '  "mapped": {"spend": "header or null", "impressions": "header or null", "cpc": "header or null"},\n'
        '  "campaign": "campaign name if present or null",\n'
        '  "platform": "linkedin|meta|google|unknown",\n'
        '  "audience_guess": "who this export looks aimed at",\n'
        '  "leak_guess": "who might click and never buy"\n'
        "}"
    )


def _read_from_payload(payload: dict) -> dict:
    return {
        "campaign": str(payload.get("campaign") or "").strip() or None,
        "platform": str(payload.get("platform") or "").strip() or None,
        "audience_guess": str(payload.get("audience_guess") or "").strip() or None,
        "leak_guess": str(payload.get("leak_guess") or "").strip() or None,
    }


def _offline_reasoning(report: dict) -> str:
    totals = report.get("totals") or {}
    if report.get("ok") and totals.get("spend") is not None:
        extra = f" Spend {totals.get('spend')}"
        if totals.get("impressions") is not None:
            extra += f", impressions {totals.get('impressions')}"
        extra += "."
    elif report.get("ok"):
        extra = " CPC was enough to rescale waste."
    else:
        extra = ""
    return (
        "No live model this run — I mapped columns in code. Totals are from the file, "
        "not invented. The 80-impression mix does not change."
        + extra
    )


def _inspect_using_llm_map(text: str, mapped: dict) -> dict:
    if not isinstance(mapped, dict):
        return {"ok": False}
    spend = str(mapped.get("spend") or "").strip()
    impressions = str(mapped.get("impressions") or "").strip()
    cpc = str(mapped.get("cpc") or "").strip()
    if not any((spend, impressions, cpc)):
        return {"ok": False}
    raw = str(text or "").lstrip("\ufeff").strip()
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return {"ok": False}
    lookup = {str(name).strip().lower(): str(name) for name in reader.fieldnames if str(name).strip()}

    def resolve(name: str) -> str | None:
        if not name:
            return None
        if name in reader.fieldnames:
            return name
        return lookup.get(name.lower().strip())

    spend_h = resolve(spend)
    impr_h = resolve(impressions)
    cpc_h = resolve(cpc)
    rows = list(reader)
    extra: list[str] = []
    existing = {str(name).strip().lower() for name in reader.fieldnames}
    if spend_h and "spend" not in existing:
        extra.append("spend")
    if impr_h and "impressions" not in existing:
        extra.append("impressions")
    if cpc_h and "cpc" not in existing and "cpi" not in existing:
        extra.append("cpc")
    if not extra:
        return inspect_campaign_csv(text)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(reader.fieldnames) + extra)
    writer.writeheader()
    for row in rows:
        new = dict(row)
        if spend_h and "spend" in extra:
            new["spend"] = row.get(spend_h)
        if impr_h and "impressions" in extra:
            new["impressions"] = row.get(impr_h)
        if cpc_h and "cpc" in extra:
            new["cpc"] = row.get(cpc_h)
        writer.writerow(new)
    return inspect_campaign_csv(out.getvalue())
