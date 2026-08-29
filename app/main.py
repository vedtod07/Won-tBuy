import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.agents.optimizer import optimize_copy, tighten_targeting
from app.impressions import sample_impressions, targeting_accuracy
from app.models import Campaign


BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="Won'tBuy", version="0.1.0")


def read_fixture(round_number: int) -> dict:
    with (FIXTURES_DIR / f"round_{round_number}.json").open(encoding="utf-8") as fixture:
        return json.load(fixture)


def load_round(round_number: int) -> dict:
    payload = read_fixture(round_number)
    campaign = Campaign.model_validate(payload["campaign"])

    if round_number == 2:
        round_one = Campaign.model_validate(read_fixture(1)["campaign"])
        campaign = tighten_targeting(round_one)
    elif round_number == 3:
        round_two = Campaign.model_validate(read_fixture(2)["campaign"])
        campaign = optimize_copy(round_two, campaign)

    impressions = sample_impressions(campaign.targeting)
    payload["campaign"] = campaign.model_dump(mode="json")
    payload["impressions"] = impressions
    payload["targeting_accuracy"] = targeting_accuracy(impressions)
    return payload


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/round/1")
def round_one() -> dict:
    return load_round(1)


@app.get("/api/round/2")
def round_two() -> dict:
    return load_round(2)


@app.get("/api/round/3")
def round_three() -> dict:
    return load_round(3)
