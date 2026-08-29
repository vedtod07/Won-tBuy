import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel as PydBaseModel

from app.agents.brief import BriefError, interpret_brief, parse_price
from app.agents.graph import run_lab_round
from app.agents.optimizer import FIXED_PRICE
from app.llm import live_key_present


BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="Won'tBuy", version="0.2.0")

load_dotenv()


def read_fixture(round_number: int) -> dict:
    with (FIXTURES_DIR / f"round_{round_number}.json").open(encoding="utf-8") as fixture:
        return json.load(fixture)


_lab: dict = {
    "client": None,
    "price": FIXED_PRICE,
    "northline": True,
    "briefing": None,
}


def reset_lab() -> None:
    _lab["client"] = None
    _lab["price"] = FIXED_PRICE
    _lab["northline"] = True
    _lab["briefing"] = None


def activate_custom_lab(briefing: dict) -> None:
    _lab["client"] = briefing["campaign"]
    _lab["price"] = briefing["price"]
    _lab["northline"] = False
    _lab["briefing"] = briefing


def load_round(round_number: int, use_cache: bool = False) -> dict:
    return run_lab_round(
        round_number,
        use_cache=use_cache,
        client=_lab["client"],
        required_price=_lab["price"],
        northline=_lab["northline"],
        briefing=_lab.get("briefing"),
    )


def build_campaign_markdown() -> str:
    lines = ["# Won'tBuy — Campaign Export", ""]

    for round_number in (1, 2, 3):
        data = load_round(round_number)
        campaign = data["campaign"]
        personas = data["personas"]
        accuracy = data["targeting_accuracy"]
        purchase = f"{sum(1 for p in personas if p.get('is_icp') and p.get('reached') and p.get('would_click'))}/{sum(1 for p in personas if p.get('is_icp') and p.get('reached'))}"

        lines.append(f"## Round {round_number} — {campaign['company']}")
        lines.append("")
        lines.append("### Targeting")
        for group, values in campaign["targeting"].items():
            lines.append(f"- **{group.replace('_', ' ')}**: {', '.join(v.replace('_', ' ') for v in values)}")
        lines.append("")

        lines.append("### Ad")
        lines.append(f"**{campaign['ad']['headline']}**")
        lines.append(f"{campaign['ad']['body']}")
        lines.append(f"CTA: {campaign['ad']['cta']}")
        lines.append("")

        lines.append("### Landing page")
        lines.append(f"**{campaign['page']['headline']}**")
        if campaign["page"].get("body"):
            lines.append(campaign["page"]["body"])
        if campaign["page"].get("bullets"):
            for bullet in campaign["page"]["bullets"]:
                lines.append(f"- {bullet}")
        if campaign["page"].get("highlight"):
            lines.append(f"\n> **{campaign['page']['highlight']}**")
        if campaign["page"].get("proof"):
            lines.append(f"\n*{campaign['page']['proof']}*")
        lines.append(f"Price: {campaign['page'].get('price') or 'no price'}")
        lines.append(f"CTA: {campaign['page']['cta']}")
        lines.append("")

        if campaign.get("email"):
            lines.append("### Email follow-up")
            lines.append(f"**Subject:** {campaign['email']['subject']}")
            lines.append(f"\n{campaign['email']['body']}")
            lines.append("")

        lines.append("### Metrics")
        lines.append(f"- Targeting accuracy: {accuracy}%")
        lines.append(f"- ICP purchase rate: {purchase}")
        if data.get("critic_summary"):
            lines.append(f"- Critic: {data['critic_summary']}")
        lines.append("")

        lines.append("### Personas")
        for persona in personas:
            if not persona.get("reached"):
                lines.append(f"- **{persona['name']}** — {persona.get('status', 'Not reached this round')}")
            else:
                click = "Would click" if persona.get("would_click") else "Would not click"
                reason = f": {persona['reason']}" if persona.get("reason") else ""
                lines.append(f"- **{persona['name']}** — {click}{reason}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    return {
        "live": live_key_present(),
        "mode": "live" if live_key_present() else "cached",
    }


@app.get("/api/round/1")
def round_one(use_cache: bool = False) -> dict:
    return load_round(1, use_cache=use_cache)


@app.get("/api/round/2")
def round_two(use_cache: bool = False) -> dict:
    return load_round(2, use_cache=use_cache)


@app.get("/api/round/3")
def round_three(use_cache: bool = False) -> dict:
    return load_round(3, use_cache=use_cache)


class BriefRequest(PydBaseModel):
    brief: str = ""


@app.get("/api/export/campaign.md")
def export_campaign() -> Response:
    markdown = build_campaign_markdown()
    return Response(content=markdown, media_type="text/markdown", headers={
        "Content-Disposition": 'attachment; filename="campaign.md"'
    })


SAMPLE_BRIEF = (
    "Northline: dashboard for plant managers to see machine downtime "
    "before the shift. From €199/mo. Proof: 40 plants."
)


def extract_price(brief: str) -> str | None:
    return parse_price(brief)


def build_custom_campaign(brief: str, use_cache: bool = True):
    """Kept for tests: interpret the brief into a leaky round-1 campaign."""
    return interpret_brief(brief, use_cache=use_cache)["campaign"]


@app.post("/api/lab/reset")
def lab_reset() -> dict:
    reset_lab()
    return {"ok": True, "lab": "northline"}


@app.post("/api/custom")
def custom_campaign(req: BriefRequest, use_cache: bool = False) -> dict:
    brief = req.brief.strip()
    if not brief:
        return {
            "error": "Brief cannot be empty.",
            "sample": SAMPLE_BRIEF,
        }
    if len(brief) < 10:
        return {
            "error": "Brief is too short — add at least a product name, who should buy it, and a price.",
            "sample": SAMPLE_BRIEF,
        }

    try:
        briefing = interpret_brief(brief, use_cache=use_cache)
    except BriefError as error:
        return {
            "error": str(error),
            "sample": "Brightside Dental: recall SMS for UK dentists. 49 pounds per month.",
        }

    activate_custom_lab(briefing)
    payload = load_round(1, use_cache=use_cache)
    payload["agent_feed"] = payload.get("agent_feed") or []
    return payload
