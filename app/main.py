import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response

from app.agents.critic import cached_critic_summary, critic_summary
from app.agents.optimizer import optimize_copy, tighten_targeting
from app.agents.personas import evaluate_persona
from app.impressions import sample_impressions, targeting_accuracy
from app.llm import CacheFallback
from app.models import Campaign


BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="Won'tBuy", version="0.2.0")


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
        campaign = optimize_copy(round_two, campaign)

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
            evaluation = evaluate_persona(fixture_persona, campaign_data, round_number)
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
        summary = critic_summary(accuracy)
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
        if campaign["page"].get("proof"):
            lines.append(f"\n*{campaign['page']['proof']}*")
        lines.append(f"Price: {campaign['page'].get('price') or 'no price'}")
        lines.append(f"CTA: {campaign['page']['cta']}")
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


@app.get("/api/round/1")
def round_one(use_cache: bool = False) -> dict:
    return load_round(1, use_cache=use_cache)


@app.get("/api/round/2")
def round_two(use_cache: bool = False) -> dict:
    return load_round(2, use_cache=use_cache)


@app.get("/api/round/3")
def round_three(use_cache: bool = False) -> dict:
    return load_round(3, use_cache=use_cache)


@app.get("/api/export/campaign.md")
def export_campaign() -> Response:
    markdown = build_campaign_markdown()
    return Response(content=markdown, media_type="text/markdown", headers={
        "Content-Disposition": 'attachment; filename="campaign.md"'
    })
