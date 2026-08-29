import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel as PydBaseModel

from app.agents.critic import cached_critic_summary, critic_summary
from app.agents.optimizer import optimize_copy, tighten_targeting
from app.agents.personas import cached_verdict, evaluate_persona
from app.impressions import sample_impressions, targeting_accuracy
from app.llm import CacheFallback, live_key_present
from app.models import Campaign, CompanySize, Creative, Industry, LandingPage, Region, Role, Targeting


BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="Won'tBuy", version="0.2.0")

load_dotenv()


def read_fixture(round_number: int) -> dict:
    with (FIXTURES_DIR / f"round_{round_number}.json").open(encoding="utf-8") as fixture:
        return json.load(fixture)


def load_round(round_number: int, use_cache: bool = False) -> dict:
    payload = read_fixture(round_number)
    campaign = Campaign.model_validate(payload["campaign"])

    if round_number == 2:
        round_one = Campaign.model_validate(read_fixture(1)["campaign"])
        campaign = tighten_targeting(round_one)
    elif round_number == 3:
        round_two = Campaign.model_validate(read_fixture(2)["campaign"])
        campaign = optimize_copy(round_two, campaign, use_cache=use_cache)

    campaign_data = campaign.model_dump(mode="json")
    impressions = sample_impressions(campaign.targeting)
    accuracy = targeting_accuracy(impressions)

    feed = []
    feed.append(f"Sampler: generated {len(impressions)} simulated impressions (seed 42)")
    feed.append(f"Sampler: {accuracy}% targeting accuracy")
    if round_number == 2:
        feed.append("Optimizer: tightened targeting — manufacturing, plant_manager + operations_manager, europe")
    elif round_number == 3:
        feed.append("Optimizer: fixed copy — price added, #1 removed, CTA changed to Book a demo")

    evaluated_personas = []
    for fixture_persona in payload["personas"]:
        try:
            evaluation = evaluate_persona(fixture_persona, campaign_data, round_number, use_cache=use_cache)
            evaluated_personas.append({**fixture_persona, **evaluation})
            if not evaluation.get("reached"):
                feed.append(f"Persona: {fixture_persona['name']} not reached — skipped")
            elif evaluation.get("would_click"):
                feed.append(f"Persona: {fixture_persona['name']} evaluated — Would click")
            else:
                feed.append(f"Persona: {fixture_persona['name']} evaluated — Would not click")
        except CacheFallback:
            evaluated_personas.append(fixture_persona)
            if not fixture_persona.get("reached"):
                feed.append(f"Persona: {fixture_persona['name']} not reached — skipped (cached)")
            elif fixture_persona.get("would_click"):
                feed.append(f"Persona: {fixture_persona['name']} (cached) — Would click")
            else:
                feed.append(f"Persona: {fixture_persona['name']} (cached) — Would not click")

    try:
        summary = critic_summary(accuracy, use_cache=use_cache)
        feed.append(f"Critic: {summary}")
    except CacheFallback:
        summary = cached_critic_summary(accuracy)
        feed.append(f"Critic (cached): {summary}")

    payload["campaign"] = campaign_data
    payload["personas"] = evaluated_personas
    payload["impressions"] = impressions
    payload["targeting_accuracy"] = accuracy
    payload["critic_summary"] = summary
    payload["agent_feed"] = feed
    payload["icp_purchase_rate"] = f"{sum(1 for p in evaluated_personas if p.get('is_icp') and p.get('reached') and p.get('would_click'))}/{sum(1 for p in evaluated_personas if p.get('is_icp') and p.get('reached'))}"
    return payload


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


def build_custom_campaign(brief: str) -> Campaign:
    words = [w for w in brief.replace("\n", " ").split(" ") if w]
    company = words[0].strip(",.!?:;") if words else "Your product"
    first_sentence = brief.split(".")[0].strip().strip(",.!?:;")
    headline = first_sentence if first_sentence else f"{company} — see it before it costs you"

    targeting = Targeting(
        industries=[Industry.MANUFACTURING, Industry.TECHNOLOGY],
        roles=[Role.PLANT_MANAGER, Role.OPERATIONS_MANAGER, Role.ENGINEER],
        company_sizes=[CompanySize.SMALL, CompanySize.MEDIUM, CompanySize.LARGE],
        regions=[Region.EUROPE, Region.NORTH_AMERICA],
    )
    return Campaign(
        company=company,
        targeting=targeting,
        ad=Creative(headline=headline, body=brief.strip(), cta="Learn more"),
        page=LandingPage(
            headline=headline,
            body=brief.strip(),
            bullets=[],
            proof=None,
            cta="Learn more",
            price=None,
        ),
    )


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
            "error": "Brief is too short — add at least a product name and target buyer.",
            "sample": SAMPLE_BRIEF,
        }

    campaign = build_custom_campaign(brief)
    campaign_data = campaign.model_dump(mode="json")
    impressions = sample_impressions(campaign.targeting)
    accuracy = targeting_accuracy(impressions)

    # Reuse the persona profiles to judge the custom campaign, deriving
    # verdicts from the custom copy rather than the Northline fixture.
    base = read_fixture(1)
    personas = []
    for fixture_persona in base["personas"]:
        try:
            evaluation = evaluate_persona(fixture_persona, campaign_data, 1, use_cache=use_cache)
            personas.append({**fixture_persona, **evaluation})
        except CacheFallback:
            personas.append({**fixture_persona, **cached_verdict(fixture_persona, campaign_data)})

    try:
        summary = critic_summary(accuracy, use_cache=use_cache)
    except CacheFallback:
        summary = cached_critic_summary(accuracy)

    purchase = f"{sum(1 for p in personas if p.get('is_icp') and p.get('reached') and p.get('would_click'))}/{sum(1 for p in personas if p.get('is_icp') and p.get('reached'))}"
    return {
        "round": 0,
        "mode": "simulated",
        "campaign": campaign_data,
        "personas": personas,
        "impressions": impressions,
        "targeting_accuracy": accuracy,
        "icp_purchase_rate": purchase,
        "critic_summary": summary,
        "agent_feed": [
            f"Sampler: generated {len(impressions)} simulated impressions (seed 42)",
            f"Sampler: {accuracy}% targeting accuracy",
            f"Brief: built a custom campaign for '{campaign.company}'",
        ],
    }
