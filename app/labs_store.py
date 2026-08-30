"""Stdlib sqlite persistence for custom lab briefings. No new dependency."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / ".data" / "labs.sqlite"


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS labs (
            lab_id TEXT PRIMARY KEY,
            company TEXT,
            briefing_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_round INTEGER,
            last_payload_json TEXT
        )
        """
    )
    return conn


def save_lab(lab_id: str, briefing: dict, payload: dict | None = None) -> None:
    company = ""
    if briefing:
        campaign = briefing.get("campaign")
        campaign_company = ""
        if hasattr(campaign, "company"):
            campaign_company = getattr(campaign, "company", "") or ""
        elif isinstance(campaign, dict):
            campaign_company = campaign.get("company") or ""
        company = str(briefing.get("company") or campaign_company or "")
    last_round = None
    last_payload = None
    if payload:
        last_round = payload.get("round")
        last_payload = json.dumps(_jsonable(payload))
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO labs (lab_id, company, briefing_json, updated_at, last_round, last_payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(lab_id) DO UPDATE SET
                company = excluded.company,
                briefing_json = excluded.briefing_json,
                updated_at = excluded.updated_at,
                last_round = COALESCE(excluded.last_round, labs.last_round),
                last_payload_json = COALESCE(excluded.last_payload_json, labs.last_payload_json)
            """,
            (lab_id, company, json.dumps(_jsonable(briefing)), now, last_round, last_payload),
        )


def list_labs() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT lab_id, company, updated_at, last_round FROM labs ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "lab_id": row[0],
            "company": row[1],
            "updated_at": row[2],
            "last_round": row[3],
        }
        for row in rows
    ]


def load_lab(lab_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT lab_id, company, briefing_json, updated_at, last_round, last_payload_json FROM labs WHERE lab_id = ?",
            (lab_id,),
        ).fetchone()
    if not row:
        return None
    briefing = json.loads(row[2])
    payload = json.loads(row[5]) if row[5] else None
    campaign = briefing.get("campaign")
    if isinstance(campaign, dict):
        from app.models import Campaign

        briefing["campaign"] = Campaign.model_validate(campaign)
    return {
        "lab_id": row[0],
        "company": row[1],
        "briefing": briefing,
        "updated_at": row[3],
        "last_round": row[4],
        "payload": payload,
    }
