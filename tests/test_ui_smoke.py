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


def test_round_one_payload_has_waste_line():
    reset_lab()
    data = load_round(1)
    assert data["waste"]["wasted_spend"] == 4.8
    assert data["chapter"]["eyes"] == "Wrong eyes"
    assert data["chapter"]["words"] == "Wrong words"
