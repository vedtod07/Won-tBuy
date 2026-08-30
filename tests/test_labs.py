"""Lab isolation and sqlite restore."""

import os

os.environ["USE_CACHE"] = "1"
os.environ.pop("LLM_API_KEY", None)

from app.agents.brief import interpret_brief
from app.labs_store import list_labs, load_lab
from app.main import activate_custom_lab, get_lab, reset_lab


def test_two_labs_do_not_clobber():
    reset_lab()
    reset_lab("judge-a")
    reset_lab("judge-b")
    briefing = interpret_brief("MokaLane: espresso for cafe owners. From €39/mo.", use_cache=True)
    activate_custom_lab(briefing, lab_id="judge-a")
    assert get_lab("judge-a")["northline"] is False
    assert get_lab("judge-a")["price"] == briefing["price"]
    assert get_lab("judge-b")["northline"] is True
    assert get_lab("default")["northline"] is True
    reset_lab("judge-a")
    reset_lab("judge-b")


def test_custom_lab_is_persisted():
    reset_lab("persist-demo")
    briefing = interpret_brief("Clayfolk: mugs for home cooks. £18.", use_cache=True)
    activate_custom_lab(briefing, lab_id="persist-demo")
    stored = load_lab("persist-demo")
    assert stored is not None
    assert stored["briefing"]["price"] == briefing["price"]
    ids = [row["lab_id"] for row in list_labs()]
    assert "persist-demo" in ids
    reset_lab("persist-demo")
