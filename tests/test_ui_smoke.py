"""Dashboard HTML contains the demo-visible controls. No Selenium."""

import os

os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)

from pathlib import Path

from app.main import load_round, reset_lab


HTML = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_dashboard_has_waste_compare_and_play():
    assert 'id="metric-waste"' in HTML
    assert 'id="compare-panel"' in HTML
    assert 'id="play-all-btn"' in HTML
    assert "/api/round/${roundNumber}/stream" in HTML
    assert "X-Lab-Id" in HTML
    assert "Rate-limited → cached" in HTML
    assert 'id="integrations-panel"' in HTML
    assert 'id="integ-meta"' in HTML
    assert 'id="integ-google"' in HTML
    assert 'id="integ-linkedin"' in HTML
    assert 'id="integ-login"' in HTML
    assert 'id="details-numbers"' in HTML
    assert "Last campaign numbers" in HTML
    assert 'id="num-csv-file"' in HTML
    assert 'id="csv-preview"' in HTML
    assert 'id="csv-demo-btn"' in HTML
    assert "/api/lab/numbers/preview" in HTML
    assert "Live model is reading this export" in HTML
    assert 'id="details-audience"' in HTML
    assert 'id="audience-form"' in HTML
    assert 'id="open-audience-btn"' in HTML
    assert 'id="open-numbers-btn"' in HTML
    assert "/api/lab/audience" in HTML
    assert 'id="login-view"' in HTML
    assert 'id="login-form"' in HTML
    assert 'id="lab-view"' in HTML
    assert 'id="marketing-dashboard"' in HTML
    assert 'id="funnel-reach"' in HTML
    assert 'id="details-custom"' in HTML
    assert 'id="brief-form"' in HTML
    assert 'id="open-brief-btn"' in HTML
    assert 'id="war-pipeline"' in HTML
    assert 'id="agent-room"' in HTML
    assert 'id="agent-timeline"' not in HTML  # created dynamically by streamed turns
    assert "function renderAgentTimeline" in HTML
    assert "renderAgentTimeline(chunk.turns || [], false)" in HTML
    assert "render(finalPayload);" in HTML
    assert "/assets/lab.css" in HTML


def test_round_one_payload_has_waste_line():
    reset_lab()
    data = load_round(1)
    assert data["waste"]["wasted_spend"] == 4.8
    assert data["chapter"]["eyes"] == "Wrong eyes"
    assert data["chapter"]["words"] == "Wrong words"


def test_integrations_catalog_does_not_claim_live_ads():
    from app.main import integrations

    data = integrations()
    assert data["live_ads"] is False
    ids = {row["id"]: row for row in data["integrations"]}
    assert ids["meta"]["wired"] is False
    assert ids["google"]["wired"] is False
    assert ids["share"]["wired"] is True
    assert ids["dashboard"]["wired"] is True
