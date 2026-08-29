import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.models import Campaign


BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="Won'tBuy", version="0.1.0")


def load_round_one() -> dict:
    with (FIXTURES_DIR / "round_1.json").open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    payload["campaign"] = Campaign.model_validate(payload["campaign"]).model_dump(mode="json")
    return payload


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/round/1")
def round_one() -> dict:
    return load_round_one()
