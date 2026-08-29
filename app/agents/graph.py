"""LangGraph lab: Sampler → Optimizer → shoppers → Critic."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.critic import cached_critic_summary, critic_summary
from app.agents.optimizer import rewrite_copy, tighten_targeting
from app.agents.personas import cached_verdict, evaluate_shopper
from app.agents.tools import campaign_as_dict, run_sampler, shopper_is_reached
from app.llm import CacheFallback, chat_json, live_key_present, use_cache_requested
from app.models import Campaign


BASE_DIR = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"

SHOPPER_ORDER = ("klaus", "anika", "mateo", "jules")


class LabState(TypedDict, total=False):
    round_number: int
    use_cache: bool
    live: bool
    northline: bool
    required_price: str
    proof_line: str
    tight_targeting: dict
    leak_roles: list[str]
    leak_ids: list[str]
    audience_label: str
    briefing_text: str
    campaign: dict
    personas_meta: list
    impressions: list
    targeting_accuracy: float
    personas: list
    critic_summary: str
    agent_feed: list[str]
    agent_turns: list[dict[str, str]]
    optimizer_error: str | None


def _offline(use_cache: bool) -> bool:
    return use_cache_requested(use_cache) or not live_key_present()


def _turn(feed: list[str], turns: list[dict[str, str]], role: str, name: str, text: str) -> None:
    feed.append(f"{role}: {text}" if role != "Persona" else f"Persona: {name} — {text}")
    turns.append({"role": role, "name": name, "text": text})


def _speak(system: str, user: str, fallback: str, use_cache: bool) -> str:
    if _offline(use_cache):
        return fallback
    try:
        result = chat_json(
            system + " Return JSON only.",
            user + '\nReturn {"text": "one or two first-person sentences"}',
            use_cache=use_cache,
        )
        text = str(result.get("text") or "").strip()
        return text or fallback
    except (CacheFallback, KeyError, TypeError, ValueError):
        return fallback


def _load_client_campaign() -> Campaign:
    with (FIXTURES_DIR / "round_1.json").open(encoding="utf-8") as handle:
        return Campaign.model_validate(json.load(handle)["campaign"])


def _load_round_three_campaign() -> Campaign:
    with (FIXTURES_DIR / "round_3.json").open(encoding="utf-8") as handle:
        return Campaign.model_validate(json.load(handle)["campaign"])


def _persona_meta() -> list[dict]:
    with (FIXTURES_DIR / "round_1.json").open(encoding="utf-8") as handle:
        return json.load(handle)["personas"]


def sampler_node(state: LabState) -> dict[str, Any]:
    tool = run_sampler.invoke(
        {
            "targeting": state["campaign"]["targeting"],
            "leak_roles": state.get("leak_roles") or ["student"],
        }
    )
    accuracy = tool["targeting_accuracy"]
    fallback = (
        f"I bought {tool['n']} simulated impressions (seed {tool['seed']}). "
        f"{accuracy}% were in-target. I do not judge the words."
    )
    text = _speak(
        "You are Sampler, a media-mix agent. You already called run_sampler. "
        "Repeat the tool's targeting_accuracy exactly. Do not invent another number.",
        json.dumps({"n": tool["n"], "seed": tool["seed"], "targeting_accuracy": accuracy}),
        fallback,
        state["use_cache"],
    )
    feed = list(state.get("agent_feed") or [])
    turns = list(state.get("agent_turns") or [])
    _turn(feed, turns, "Sampler", "Sampler", text)
    return {
        "impressions": tool["impressions"],
        "targeting_accuracy": accuracy,
        "agent_feed": feed,
        "agent_turns": turns,
    }


def optimizer_node(state: LabState) -> dict[str, Any]:
    round_number = state["round_number"]
    campaign = Campaign.model_validate(state["campaign"])
    feed = list(state.get("agent_feed") or [])
    turns = list(state.get("agent_turns") or [])
    error = None

    if round_number == 1:
        company = campaign.company
        fallback = (
            f"I have no write tools this round. {company}'s ad stays as it is — leaky targeting, no price on the page."
        )
        text = _speak(
            "You are Optimizer. Round 1: you must not change targeting or copy. Say that in first person. Name the company.",
            json.dumps({"company": company, "round": 1}),
            fallback,
            state["use_cache"],
        )
    elif round_number == 2:
        tight = state.get("tight_targeting")
        campaign = tighten_targeting(campaign, tight)
        leak_roles = ", ".join(state.get("leak_roles") or ["student"])
        audience = state.get("audience_label") or "intended buyers"
        fallback = (
            f"I called tighten_targeting for {campaign.company}. Dropped leak role ({leak_roles}). "
            f"Audience is now {audience}. Copy stays frozen — same headline, same missing price."
        )
        text = _speak(
            "You are Optimizer. You just invoked tighten_targeting. Say the company, who you dropped, who remains. Do not mention copy changes.",
            json.dumps(
                {
                    "company": campaign.company,
                    "targeting": campaign.targeting.model_dump(mode="json"),
                    "audience": audience,
                }
            ),
            fallback,
            state["use_cache"],
        )
    else:
        tight = state.get("tight_targeting")
        campaign = tighten_targeting(campaign, tight)
        required_price = state.get("required_price") or "from €199/mo"
        northline = bool(state.get("northline", True))
        live = bool(state.get("live"))
        cached = None if live else (_load_round_three_campaign() if northline else None)
        campaign, error = rewrite_copy(
            campaign,
            use_cache=state["use_cache"],
            cached_campaign=cached,
            allow_fixture=northline and not live,
            required_price=required_price,
            proof_line=state.get("proof_line"),
        )
        if error:
            text = error
        else:
            fallback = (
                f"I called rewrite_copy. Price is {required_price}, no unsourced #1, CTA is Book a demo. "
                "Targeting is unchanged."
            )
            text = _speak(
                "You are Optimizer. You just invoked rewrite_copy. Describe only the copy change. Targeting stayed.",
                json.dumps({"ad": campaign.ad.model_dump(mode="json"), "page": campaign.page.model_dump(mode="json")}),
                fallback,
                state["use_cache"],
            )

    _turn(feed, turns, "Optimizer", "Optimizer", text)
    return {
        "campaign": campaign_as_dict(campaign),
        "agent_feed": feed,
        "agent_turns": turns,
        "optimizer_error": error,
    }


def _one_shopper(meta: dict, campaign: dict, use_cache: bool, leak_ids: list[str], leak_roles: list[str]) -> dict:
    persona_id = meta["id"]
    targeting = campaign.get("targeting") or {}
    reached = shopper_is_reached(persona_id, targeting, leak_ids=leak_ids, leak_roles=leak_roles)
    seed = {
        "id": meta["id"],
        "name": meta["name"],
        "segment": meta.get("segment"),
        "title": meta.get("title"),
        "is_icp": meta.get("is_icp"),
        "objection": meta.get("objection"),
        "trait": meta.get("trait"),
        "reached": reached,
    }
    try:
        evaluation = evaluate_shopper(seed, campaign, use_cache=use_cache)
    except CacheFallback:
        evaluation = cached_verdict(seed, campaign) if reached else {
            "id": persona_id,
            "reached": False,
            "status": "Not reached this round",
        }
    return {**seed, **evaluation}


def shoppers_node(state: LabState) -> dict[str, Any]:
    campaign = state["campaign"]
    use_cache = state["use_cache"]
    metas = {row["id"]: row for row in state["personas_meta"]}
    order = [row["id"] for row in state["personas_meta"]] or list(SHOPPER_ORDER)
    leak_ids = state.get("leak_ids") or ["jules", "leak"]
    leak_roles = state.get("leak_roles") or ["student"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(
            pool.map(
                lambda pid: _one_shopper(metas[pid], campaign, use_cache, leak_ids, leak_roles),
                order,
            )
        )

    feed = list(state.get("agent_feed") or [])
    turns = list(state.get("agent_turns") or [])
    for row in rows:
        name = row["name"]
        if not row.get("reached"):
            text = "I was not in this audience. I did not change my mind."
        elif row.get("would_click"):
            quote = row.get("quote") or "I would click."
            text = f"Would click. “{quote}”"
        else:
            quote = row.get("quote") or "I would not click."
            text = f"Would not click. “{quote}”"
        _turn(feed, turns, "Persona", name, text)

    return {"personas": rows, "agent_feed": feed, "agent_turns": turns}


def critic_node(state: LabState) -> dict[str, Any]:
    accuracy = state["targeting_accuracy"]
    round_number = state["round_number"]
    personas = state["personas"]
    try:
        summary = critic_summary(
            accuracy,
            personas=personas,
            round_number=round_number,
            use_cache=state["use_cache"],
        )
    except CacheFallback:
        summary = cached_critic_summary(accuracy, round_number=round_number, personas=personas)

    feed = list(state.get("agent_feed") or [])
    turns = list(state.get("agent_turns") or [])
    _turn(feed, turns, "Critic", "Critic", summary)
    return {
        "critic_summary": summary,
        "agent_feed": feed,
        "agent_turns": turns,
    }


def _build_graph():
    graph = StateGraph(LabState)
    graph.add_node("sampler", sampler_node)
    graph.add_node("optimizer", optimizer_node)
    graph.add_node("shoppers", shoppers_node)
    graph.add_node("critic", critic_node)
    graph.add_edge(START, "optimizer")
    graph.add_edge("optimizer", "sampler")
    graph.add_edge("sampler", "shoppers")
    graph.add_edge("shoppers", "critic")
    graph.add_edge("critic", END)
    return graph.compile()


LAB_GRAPH = _build_graph()


def build_chapter(
    round_number: int,
    personas: list,
    company: str,
    accuracy: float,
    purchase: str,
    audience_label: str | None = None,
) -> dict:
    leak = next((row for row in personas if row.get("is_icp") is False), None)
    buyers = [row for row in personas if row.get("is_icp")]
    leak_name = (leak or {}).get("name") or "the leak"
    buyer_names = ", ".join(row.get("name") or "buyer" for row in buyers) or "the intended buyers"
    audience = audience_label or "intended buyers"
    if round_number == 1:
        return {
            "eyes": "Wrong eyes",
            "words": "Wrong words",
            "people_title": "Wrong audience clicked — intended buyers refused",
            "people_sub": (
                f"{leak_name} is not a buyer. {buyer_names} are — "
                "and they would not click."
            ),
            "body": (
                f"{leak_name} saw the {company} ad and would click (wasted spend). "
                f"{buyer_names} saw it too and still would not click: "
                "no price on the page, unsourced #1. Two failures, same campaign."
            ),
            "accuracy_sub": f"Broad targeting leaked off-ICP. Intended: {audience}.",
        }
    if round_number == 2:
        return {
            "eyes": "Right eyes",
            "words": "Wrong words",
            "people_title": "Right audience — same words, same refusals",
            "people_sub": (
                f"{leak_name} is out. The ad did not change, so {buyer_names} still would not click."
            ),
            "body": (
                f"Targeting now matches {audience}. {leak_name} was not reached this round. "
                f"Copy is frozen — that is why {buyer_names} still refuse. "
                "Step 3 is the words, not the audience."
            ),
            "accuracy_sub": f"Leak dropped. Audience: {audience}.",
        }
    return {
        "eyes": "Right eyes",
        "words": "Right words",
        "people_title": "Right audience + copy the buyers will click",
        "people_sub": (
            f"Same targeting as step 2. Price, no #1, Book a demo. {purchase} buyers would click."
        ),
        "body": (
            f"Targeting stayed on {audience}. Copy now states the brief's price, drops the unsourced ranking, "
            f"and asks to book a demo. {buyer_names} would click. {leak_name} was not reached."
        ),
        "accuracy_sub": "Same tight targeting as step 2.",
    }


def run_lab_round(
    round_number: int,
    use_cache: bool = False,
    client: Campaign | None = None,
    required_price: str | None = None,
    northline: bool = True,
    briefing: dict | None = None,
) -> dict:
    from app.agents.optimizer import FIXED_PRICE

    campaign = client if client is not None else _load_client_campaign()
    price = required_price or (briefing or {}).get("price") or FIXED_PRICE
    live = live_key_present() and not use_cache_requested(use_cache)
    personas_meta = (briefing or {}).get("personas") or _persona_meta()
    leak_roles = [str((briefing or {}).get("leak_role") or "student")]
    leak_ids = [str((briefing or {}).get("leak_id") or "jules")]
    if "jules" not in leak_ids:
        leak_ids.append("leak")
    tight = (briefing or {}).get("tight_targeting")
    audience_label = (briefing or {}).get("audience_label")
    proof_line = (briefing or {}).get("proof")
    result = LAB_GRAPH.invoke(
        {
            "round_number": round_number,
            "use_cache": use_cache,
            "live": live,
            "northline": northline,
            "required_price": price,
            "proof_line": proof_line,
            "tight_targeting": tight,
            "leak_roles": leak_roles,
            "leak_ids": leak_ids,
            "audience_label": audience_label,
            "campaign": campaign_as_dict(campaign),
            "personas_meta": personas_meta,
            "agent_feed": [],
            "agent_turns": [],
            "optimizer_error": None,
        }
    )
    personas = result["personas"]
    icp_reached = [p for p in personas if p.get("is_icp") and p.get("reached")]
    icp_clicked = [p for p in icp_reached if p.get("would_click")]
    purchase = f"{len(icp_clicked)}/{len(icp_reached)}" if icp_reached else "0/0"
    company = result["campaign"].get("company") or campaign.company
    feed = list(result["agent_feed"])
    turns = list(result["agent_turns"])
    if briefing and briefing.get("reasoning"):
        reason = briefing["reasoning"]
        feed.insert(0, f"Brief: {reason}")
        turns.insert(0, {"role": "Brief", "name": "Brief", "text": reason})
    return {
        "round": round_number,
        "mode": "simulated",
        "live": live,
        "lab": "northline" if northline else "custom",
        "campaign": result["campaign"],
        "personas": personas,
        "impressions": result["impressions"],
        "targeting_accuracy": result["targeting_accuracy"],
        "icp_purchase_rate": purchase,
        "critic_summary": result["critic_summary"],
        "agent_feed": feed,
        "agent_turns": turns,
        "optimizer_error": result.get("optimizer_error"),
        "briefing": {
            "company": company,
            "price": price,
            "audience": audience_label,
            "reasoning": (briefing or {}).get("reasoning"),
            "interpreted_by": (briefing or {}).get("interpreted_by"),
        } if briefing else None,
        "chapter": build_chapter(
            round_number,
            personas,
            company,
            result["targeting_accuracy"],
            purchase,
            audience_label,
        ),
    }
