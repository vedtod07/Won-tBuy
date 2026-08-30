"""HTTP end-to-end: every judge-facing route on a cached lab."""

import json
import os
from pathlib import Path

os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient

from app.main import app, reset_lab

ROOT = Path(__file__).resolve().parent.parent
DEMO_CSV = (ROOT / "app" / "static" / "demo" / "last-campaign.csv").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")

client = TestClient(app)


def _lab(name: str) -> dict:
    return {"X-Lab-Id": name}


def test_pages_and_static_assets():
    home = client.get("/")
    login = client.get("/login")
    css = client.get("/assets/lab.css")
    demo = client.get("/assets/demo/last-campaign.csv")
    assert home.status_code == 200
    assert "Won'tBuy" in home.text
    assert 'id="login-view"' in home.text
    assert 'id="lab-view"' in home.text
    assert login.status_code == 200
    assert css.status_code == 200
    assert demo.status_code == 200
    assert "spend" in demo.text
    lab_at = home.text.index('id="lab-view"')
    dash_at = home.text.index('id="marketing-dashboard"')
    login_at = home.text.index('id="login-view"')
    assert login_at < lab_at < dash_at
    assert "function renderAgentTimeline" in home.text
    assert "Live model is reading this export" in home.text
    assert 'id="login-judge"' in home.text
    assert HTML.index('id="funnel-reach"') and "reach:" in HTML


def test_health_status_integrations():
    health = client.get("/health").json()
    status = client.get("/api/status").json()
    integ = client.get("/api/integrations").json()
    assert health["status"] == "ok"
    assert status["mode"] in {"live", "cached", "rate_limited"}
    assert integ["live_ads"] is False
    ids = {row["id"] for row in integ["integrations"]}
    assert {"meta", "google", "linkedin", "share", "dashboard"} <= ids


def test_northline_three_rounds_and_compare():
    headers = _lab("e2e-northline")
    reset_lab("e2e-northline")
    assert client.post("/api/lab/reset", headers=headers).json()["lab"] == "northline"

    r1 = client.get("/api/round/1?use_cache=true", headers=headers).json()
    r2 = client.get("/api/round/2?use_cache=true", headers=headers).json()
    r3 = client.get("/api/round/3?use_cache=true", headers=headers).json()
    assert r1["lab"] == "northline"
    assert r1["targeting_accuracy"] == 40.0
    assert r1["chapter"]["eyes"] == "Wrong eyes"
    assert r1["waste"]["wasted_spend"] == 4.8
    assert r1["waste"]["impressions"] == 80
    names = [p["name"] for p in r1["personas"]]
    assert names == ["Klaus", "Anika", "Mateo", "Jules"]
    jules = next(p for p in r1["personas"] if p["id"] == "jules")
    assert jules["reached"] is True
    assert jules["would_click"] is True

    assert r2["targeting_accuracy"] == 85.0
    j2 = next(p for p in r2["personas"] if p["id"] == "jules")
    assert j2["reached"] is False
    assert r1["campaign"]["ad"] == r2["campaign"]["ad"]

    assert r3["targeting_accuracy"] == 85.0
    assert r3["campaign"]["ad"]["cta"] == "Book a demo"
    assert r3["campaign"]["page"]["price"] == "from €199/mo"
    assert r2["campaign"]["targeting"] == r3["campaign"]["targeting"]
    icp_clicks = [
        p for p in r3["personas"] if p.get("is_icp") and p.get("reached") and p.get("would_click")
    ]
    assert len(icp_clicks) == 3

    played = client.get("/api/lab/play?use_cache=true", headers=headers).json()
    assert len(played["rounds"]) == 3
    assert "compare" in played

    export = client.get("/api/export/campaign.md", headers=headers)
    assert export.status_code == 200
    assert "Northline" in export.text or "campaign" in export.text.lower()


def test_round_one_stream_finishes():
    headers = _lab("e2e-stream")
    reset_lab("e2e-stream")
    with client.stream("GET", "/api/round/1/stream?use_cache=true", headers=headers) as res:
        assert res.status_code == 200
        chunks = [json.loads(line) for line in res.iter_lines() if line]
    assert chunks
    assert chunks[-1]["type"] == "final"
    nodes = [c.get("node") for c in chunks if c.get("type") == "node"]
    assert "optimizer" in nodes
    assert "sampler" in nodes
    final = chunks[-1]
    assert final["targeting_accuracy"] == 40.0
    assert len(final["impressions"]) == 80


def test_csv_preview_apply_rescales_waste_not_mix():
    headers = _lab("e2e-csv")
    reset_lab("e2e-csv")
    preview = client.post(
        "/api/lab/numbers/preview?use_cache=true",
        headers=headers,
        json={"csv": DEMO_CSV},
    ).json()
    assert preview["ok"] is True
    assert preview["totals"]["spend"] == 1200
    assert preview["totals"]["impressions"] == 8000
    assert "campaign_name" in preview["ignored"]
    assert preview["interpreted_by"] in {"offline", "llm"}
    assert preview["reasoning"]

    applied = client.post(
        "/api/lab/numbers?use_cache=true",
        headers=headers,
        json={"csv": DEMO_CSV},
    ).json()
    assert applied["ok"] is True
    assert applied["economics"]["spend"] == 1200

    r1 = client.get("/api/round/1?use_cache=true", headers=headers).json()
    assert r1["waste"]["impressions"] == 80
    assert r1["waste"]["wasted_spend"] == 720.0
    assert r1["waste"]["source"] == "user_spend"
    assert [p["name"] for p in r1["personas"]] == ["Klaus", "Anika", "Mateo", "Jules"]

    bad = client.post(
        "/api/lab/numbers/preview?use_cache=true",
        headers=headers,
        json={"csv": "foo,bar\n1,2"},
    ).json()
    assert bad["ok"] is False


def test_audience_builder_then_custom_brief_then_reset():
    headers = _lab("e2e-audience")
    reset_lab("e2e-audience")
    missing = client.post(
        "/api/lab/audience",
        headers=headers,
        json={"company": "Clayfolk", "audience": "home cooks", "leak": "teens", "price": ""},
    ).json()
    assert "error" in missing

    aud = client.post(
        "/api/lab/audience",
        headers=headers,
        json={
            "company": "Clayfolk",
            "product": "handmade mugs",
            "price": "18 pounds each",
            "audience": "home cooks",
            "leak": "teen gift browsers",
            "buyers": [
                {"name": "Marta", "title": "Home cook · wants a price"},
                {"name": "Kenji", "title": "Home cook · hates slogans"},
                {"name": "Elena", "title": "Home cook · rejects ranking"},
            ],
            "leak_name": "Tess",
            "leak_title": "Teen browsing gifts",
        },
    ).json()
    assert aud["ok"] is True
    assert aud["interpreted_by"] == "audience_builder"
    assert aud["cta"] == "Shop now"
    names = [p["name"] for p in aud["personas"]]
    assert names == ["Marta", "Kenji", "Elena", "Tess"]

    r1 = client.get("/api/round/1?use_cache=true", headers=headers).json()
    assert r1["lab"] == "custom"
    assert [p["name"] for p in r1["personas"]] == ["Marta", "Kenji", "Elena", "Tess"]
    leak = next(p for p in r1["personas"] if p.get("is_icp") is False)
    assert leak["name"] == "Tess"
    assert leak["reached"] is True

    empty = client.post("/api/custom?use_cache=true", headers=headers, json={"brief": ""}).json()
    assert "error" in empty
    noprize = client.post(
        "/api/custom?use_cache=true",
        headers=headers,
        json={"brief": "Helix is a floor ops board for plant managers."},
    ).json()
    assert "error" in noprize

    custom = client.post(
        "/api/custom?use_cache=true",
        headers=headers,
        json={"brief": "Nimbus: log search for cloud ops. From $80/mo. Buyer: cloud ops managers. Leak: solo indie hackers."},
    ).json()
    assert custom["ok"] is True
    assert custom["company"].lower().startswith("nimbus")
    assert "199" not in str(custom.get("price") or "")
    r_custom = client.get("/api/round/1?use_cache=true", headers=headers).json()
    assert r_custom["lab"] == "custom"
    custom_names = {p["name"] for p in r_custom["personas"]}
    assert "Klaus" not in custom_names
    assert "Jules" not in custom_names

    reset = client.post("/api/lab/reset", headers=headers).json()
    assert reset["lab"] == "northline"
    back = client.get("/api/round/1?use_cache=true", headers=headers).json()
    assert [p["name"] for p in back["personas"]] == ["Klaus", "Anika", "Mateo", "Jules"]
