import json
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel as PydBaseModel

from app.agents.brief import BriefError, briefing_from_audience, interpret_brief, parse_price
from app.agents.csv_read import interpret_campaign_csv
from app.agents.graph import run_lab_round, stream_lab_round
from app.agents.optimizer import FIXED_PRICE
from app.impressions import parse_campaign_economics
from app.labs_store import list_labs as stored_labs
from app.labs_store import load_lab as stored_load
from app.labs_store import save_lab
from app.llm import llm_status


BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="Won'tBuy", version="0.2.0")

load_dotenv()

DEFAULT_LAB = "default"
_lock = threading.Lock()
_labs: dict[str, dict] = {}


def read_fixture(round_number: int) -> dict:
    with (FIXTURES_DIR / f"round_{round_number}.json").open(encoding="utf-8") as fixture:
        return json.load(fixture)


def _empty_slot() -> dict:
    return {
        "client": None,
        "price": FIXED_PRICE,
        "northline": True,
        "briefing": None,
        "economics": None,
    }


def get_lab(lab_id: str = DEFAULT_LAB) -> dict:
    with _lock:
        slot = _labs.get(lab_id)
        if slot is None:
            slot = _empty_slot()
            _labs[lab_id] = slot
        return slot


# Tests and older callers still import `_lab` as the default slot.
_lab = get_lab(DEFAULT_LAB)


def reset_lab(lab_id: str = DEFAULT_LAB) -> None:
    slot = get_lab(lab_id)
    slot.update(_empty_slot())


def activate_custom_lab(briefing: dict, lab_id: str = DEFAULT_LAB) -> None:
    slot = get_lab(lab_id)
    slot["client"] = briefing["campaign"]
    slot["price"] = briefing["price"]
    slot["northline"] = False
    slot["briefing"] = briefing
    save_lab(lab_id, briefing)


def load_round(round_number: int, use_cache: bool = False, lab_id: str = DEFAULT_LAB) -> dict:
    slot = get_lab(lab_id)
    payload = run_lab_round(
        round_number,
        use_cache=use_cache,
        client=slot["client"],
        required_price=slot["price"],
        northline=slot["northline"],
        briefing=slot.get("briefing"),
        economics=slot.get("economics"),
    )
    if slot.get("briefing"):
        save_lab(lab_id, slot["briefing"], payload)
    return payload


def _lab_id(request: Request) -> str:
    return (
        request.headers.get("x-lab-id")
        or request.query_params.get("lab_id")
        or DEFAULT_LAB
    )


def build_compare(rounds: list[dict]) -> dict:
    by_round = {row.get("round"): row for row in rounds}

    def targeting(row: dict | None) -> dict:
        return ((row or {}).get("campaign") or {}).get("targeting") or {}

    def copy_bits(row: dict | None) -> dict:
        campaign = (row or {}).get("campaign") or {}
        ad = campaign.get("ad") or {}
        page = campaign.get("page") or {}
        return {
            "headline": ad.get("headline"),
            "price": page.get("price"),
            "cta": ad.get("cta"),
        }

    r1, r2, r3 = by_round.get(1), by_round.get(2), by_round.get(3)
    return {
        "targeting": {"round_1": targeting(r1), "round_2": targeting(r2)},
        "copy": {"round_2": copy_bits(r2), "round_3": copy_bits(r3)},
        "score": {
            "accuracy": [(row or {}).get("targeting_accuracy") for row in (r1, r2, r3)],
            "purchase": [(row or {}).get("icp_purchase_rate") for row in (r1, r2, r3)],
            "waste": [(row or {}).get("waste") for row in (r1, r2, r3)],
        },
    }


def build_campaign_markdown() -> str:
    lines = ["# Won'tBuy — Campaign Export", ""]

    for round_number in (1, 2, 3):
        data = load_round(round_number)
        campaign = data["campaign"]
        personas = data["personas"]
        accuracy = data["targeting_accuracy"]
        purchase = f"{sum(1 for p in personas if p.get('is_icp') and p.get('reached') and p.get('would_click'))}/{sum(1 for p in personas if p.get('is_icp') and p.get('reached'))}"
        waste = data.get("waste") or {}

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
        if waste:
            lines.append(
                f"- Wasted spend: €{waste.get('wasted_spend', 0):.2f} "
                f"({waste.get('off_icp', 0)} off-ICP of {waste.get('impressions', 0)})"
            )
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


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    return llm_status()


@app.get("/api/round/1")
def round_one(request: Request, use_cache: bool = False) -> dict:
    return load_round(1, use_cache=use_cache, lab_id=_lab_id(request))


@app.get("/api/round/2")
def round_two(request: Request, use_cache: bool = False) -> dict:
    return load_round(2, use_cache=use_cache, lab_id=_lab_id(request))


@app.get("/api/round/3")
def round_three(request: Request, use_cache: bool = False) -> dict:
    return load_round(3, use_cache=use_cache, lab_id=_lab_id(request))


def _stream_round(round_number: int, request: Request, use_cache: bool):
    slot = get_lab(_lab_id(request))

    def generate():
        for chunk in stream_lab_round(
            round_number,
            use_cache=use_cache,
            client=slot["client"],
            required_price=slot["price"],
            northline=slot["northline"],
            briefing=slot.get("briefing"),
            economics=slot.get("economics"),
        ):
            yield json.dumps(chunk) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/round/1/stream")
def round_one_stream(request: Request, use_cache: bool = False):
    return _stream_round(1, request, use_cache)


@app.get("/api/round/2/stream")
def round_two_stream(request: Request, use_cache: bool = False):
    return _stream_round(2, request, use_cache)


@app.get("/api/round/3/stream")
def round_three_stream(request: Request, use_cache: bool = False):
    return _stream_round(3, request, use_cache)


class BriefRequest(PydBaseModel):
    brief: str = ""


class NumbersRequest(PydBaseModel):
    spend: float | None = None
    impressions: float | None = None
    cpc: float | None = None
    csv: str = ""


class BuyerRow(PydBaseModel):
    name: str = ""
    title: str = ""


class AudienceRequest(PydBaseModel):
    company: str = ""
    product: str = ""
    price: str = ""
    audience: str = ""
    leak: str = ""
    proof: str = ""
    buyers: list[BuyerRow] = []
    leak_name: str = ""
    leak_title: str = ""


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


@app.post("/api/lab/numbers")
def lab_numbers(req: NumbersRequest, request: Request, use_cache: bool = False) -> dict:
    csv_read = None
    try:
        if req.csv and str(req.csv).strip():
            csv_read = interpret_campaign_csv(req.csv, use_cache=use_cache)
            if not csv_read.get("ok"):
                return {
                    "error": csv_read.get("error") or "Could not read those numbers.",
                    "csv": csv_read,
                }
            totals = csv_read.get("totals") or {}
            economics = parse_campaign_economics(
                spend=req.spend if req.spend is not None else totals.get("spend"),
                impressions=req.impressions if req.impressions is not None else totals.get("impressions"),
                cpc=req.cpc if req.cpc is not None else totals.get("cpc"),
            )
        else:
            economics = parse_campaign_economics(
                spend=req.spend,
                impressions=req.impressions,
                cpc=req.cpc,
            )
    except (TypeError, ValueError):
        return {"error": "Could not read those numbers."}
    if not economics:
        return {"error": "Enter spend + impressions, a CPC, or a CSV with those columns."}
    if csv_read:
        economics["interpreted_by"] = csv_read.get("interpreted_by")
        economics["reasoning"] = csv_read.get("reasoning")
        economics["read"] = csv_read.get("read") or {}
    slot = get_lab(_lab_id(request))
    slot["economics"] = economics
    return {"ok": True, "economics": economics, "csv": csv_read}


@app.post("/api/lab/numbers/preview")
def lab_numbers_preview(req: NumbersRequest, use_cache: bool = False) -> dict:
    """Live model reads the export; code still sums spend. Does not attach economics."""
    return interpret_campaign_csv(req.csv or "", use_cache=use_cache)


@app.post("/api/lab/audience")
def lab_audience(req: AudienceRequest, request: Request) -> dict:
    """Activate a custom lab from explicit buyer / leak fields."""
    try:
        briefing = briefing_from_audience(
            company=req.company,
            audience=req.audience,
            leak=req.leak,
            price=req.price,
            product=req.product,
            proof=req.proof,
            buyers=[{"name": row.name, "title": row.title} for row in req.buyers],
            leak_person={"name": req.leak_name, "title": req.leak_title},
        )
    except BriefError as error:
        return {
            "error": str(error),
            "sample": "Clayfolk / home cooks / teen gift browsers / 18 pounds each",
        }
    lab_id = _lab_id(request)
    try:
        activate_custom_lab(briefing, lab_id=lab_id)
    except Exception:
        return {
            "error": "That audience loaded, but the lab could not run it. Check brand, buyers, leak, and price.",
            "sample": "Clayfolk / home cooks / teen gift browsers / 18 pounds each",
        }
    return {
        "ok": True,
        "lab": "custom",
        "company": briefing.get("company"),
        "price": briefing.get("price"),
        "audience": briefing.get("audience_label"),
        "cta": briefing.get("cta"),
        "reasoning": briefing.get("reasoning"),
        "interpreted_by": briefing.get("interpreted_by"),
        "personas": [
            {"id": row.get("id"), "name": row.get("name"), "title": row.get("title"), "is_icp": row.get("is_icp")}
            for row in briefing.get("personas") or []
        ],
    }


@app.post("/api/lab/reset")
def lab_reset(request: Request) -> dict:
    reset_lab(_lab_id(request))
    return {"ok": True, "lab": "northline"}


@app.get("/api/labs")
def labs() -> dict:
    return {"labs": stored_labs()}


@app.post("/api/labs/{lab_id}/restore")
def restore_lab(lab_id: str) -> dict:
    stored = stored_load(lab_id)
    if not stored:
        return {"error": "Lab not found."}
    activate_custom_lab(stored["briefing"], lab_id=lab_id)
    return {"ok": True, "lab_id": lab_id, "company": stored.get("company")}


@app.get("/api/integrations")
def integrations() -> dict:
    """Catalog of optional product hooks. None of these pull live ads."""
    return {
        "mode": "simulator",
        "live_ads": False,
        "integrations": [
            {"id": "meta", "name": "Meta Ads", "wired": False, "now": "Paste spend/impressions to rescale waste."},
            {"id": "google", "name": "Google Ads", "wired": False, "now": "Paste spend/impressions to rescale waste."},
            {"id": "linkedin", "name": "LinkedIn Ads", "wired": False, "now": "Paste spend/impressions to rescale waste."},
            {"id": "share", "name": "Team login / share", "wired": True, "now": "Copy a ?lab= link for this session."},
            {"id": "dashboard", "name": "Dashboard", "wired": True, "now": "Campaign health panel on this page."},
            {"id": "agents", "name": "Extra agents", "wired": False, "now": "Sampler, Optimizer, shoppers, Critic only."},
            {"id": "chat", "name": "Chatbot", "wired": False, "now": "Edit the brief and re-run."},
            {"id": "round4", "name": "Round 4", "wired": False, "now": "Three steps stay the product."},
        ],
    }


@app.get("/api/lab/play")
def play_lab(request: Request, use_cache: bool = False) -> dict:
    lab_id = _lab_id(request)
    rounds = [load_round(n, use_cache=use_cache, lab_id=lab_id) for n in (1, 2, 3)]
    return {"rounds": rounds, "compare": build_compare(rounds)}


@app.post("/api/custom")
def custom_campaign(req: BriefRequest, request: Request, use_cache: bool = False) -> dict:
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

    lab_id = _lab_id(request)
    try:
        activate_custom_lab(briefing, lab_id=lab_id)
    except Exception:
        return {
            "error": "That brief loaded, but the lab could not run it. Try a shorter line: brand, who should buy it, and a price.",
            "sample": "Reachify: marketing for local stores. From $100.",
        }
    return {
        "ok": True,
        "lab": "custom",
        "company": briefing.get("company"),
        "price": briefing.get("price"),
        "audience": briefing.get("audience_label"),
        "cta": briefing.get("cta"),
        "reasoning": briefing.get("reasoning"),
        "interpreted_by": briefing.get("interpreted_by"),
    }


app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")
