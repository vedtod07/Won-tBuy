# Won'tBuy

> **Five AI agents put your campaign through a war room before your budget goes live.**
>
> They challenge the audience, inspect the spend, argue from buyer and non-buyer perspectives, isolate what failed, and iterate only the part of the campaign that needs fixing.

**Won'tBuy is a campaign pre-flight simulator for teams that refuse to learn from wasted ad spend.**

Most marketing tools generate more copy. Won'tBuy starts with a harder question: **will the right people buy this, and if not, is the audience wrong or are the words wrong?**

It stages a five-agent campaign war room around every run:

| Agent | Their job in the argument |
| --- | --- |
| **Brief** | Turns a product brief into the intended buyer, likely audience leak, offer, evidence, price, and CTA. |
| **Optimizer** | Changes one variable at a time: first targeting, then copy—never both at once. |
| **Sampler** | Simulates the paid audience and exposes targeting accuracy and off-ICP wasted spend. |
| **Buyer panel** | Gives intended buyers and likely non-buyers a voice: who clicks, who refuses, and why. |
| **Critic** | Challenges the current result, separates the failure modes, and tells the Optimizer what must change next. |

The agents do not jump straight to a polished answer. They work through a controlled three-step argument:

1. **Wrong eyes** — the buyer panel exposes that the campaign leaks to people who may click but will never buy.
2. **Wrong words** — targeting is tightened while copy is frozen, proving that reaching the right people is not enough when the offer still fails scrutiny.
3. **Right words** — only after the diagnosis is clear does the Optimizer rewrite the campaign with clear price, approved proof, and an offer-appropriate CTA.

> **The result is not “AI-generated copy.” It is an evidence-backed recommendation for what to change, why to change it, and the revised campaign to ship.**

Won'tBuy is an agentic marketing pre-flight lab for paid campaigns. It helps marketers answer two expensive questions before launching or scaling an ad:

1. **Wrong eyes:** Are we paying to reach people who will never buy?
2. **Wrong words:** Are the right people seeing the campaign but rejecting its message?

Rather than acting as a generic copy generator, Won'tBuy streams the campaign journey in real time, lets the five agents challenge the campaign from different angles, and produces an improved campaign only after the diagnosis is clear.

> **Important:** Won'tBuy is a simulator. It does not connect to Meta, Google, LinkedIn, or a live ad account. It makes this explicit in both the UI and API responses.

## Why this is useful

Paid campaigns are usually optimized after money has been spent. Won'tBuy is designed as a pre-flight layer:

- Give it a product brief and the intended buyer.
- Optionally paste spend, impressions, CPC, or simple CSV data from a previous campaign.
- Watch the agents test targeting and message quality in sequence.
- Receive a diagnosis, refined targeting, and revised ad / landing-page / email copy.
- Export the resulting campaign report and share a lab session with a teammate.

For users without historic data, the deterministic simulator provides a safe starting point. When the user supplies spend or CPC, Won'tBuy rescales the simulated off-ICP waste rate to show the likely monetary impact on their own campaign.

## Product capabilities

### Campaign control room

The UI is a campaign workspace with:

- A three-step campaign progression.
- Campaign health: audience quality, buyer conversion, wasted spend, and a combined campaign score.
- A funnel view: impressions reached → buyer engagement → intended buyers willing to click.
- Side-by-side comparison of the three rounds.
- A recommended next action based on the active round.
- Campaign previews for the ad, landing page, and follow-up email.

### Live agent theatre

Won'tBuy uses an NDJSON stream to show the graph executing in real time. During a run, the interface receives independent updates from:

1. **Optimizer** — freezes or changes targeting/copy for the current step.
2. **Sampler** — simulates paid impressions and calculates audience quality and waste.
3. **Buyer panel** — evaluates the campaign from intended-buyer and audience-leak perspectives.
4. **Critic** — explains the current failure and identifies the next move.

Each turn records whether it used a live model or cache fallback, the model name, and latency. This makes the agent workflow inspectable rather than a black-box final answer.

### Custom briefs and user-owned personas

A custom brief is converted into a campaign, intended audience, audience leak, price, proof, CTA, and buyer personas.

Use explicit clauses when helpful:

```text
Cloudline: uptime monitoring for cloud operations managers at banks.
From $149/month. Buyer: cloud operations managers at banks.
Leak: solo indie hackers. Proof: 99.95% alert delivery SLA.
```

The brief parser creates buyer and leak personas from the user’s own audience language. It does not simply relabel the Northline demonstration personas.

The **audience builder** lets you review and edit those generated personas — firmographics, objections, and exclusion lists — before a run, so the war room argues about *your* buyers, not a demo's.

### Campaign economics

Won'tBuy accepts any of these inputs:

- Total spend and impressions
- CPC / cost per impression
- A simple CSV with columns such as `spend`, `impressions`, and `cpc`

Example CSV:

```csv
spend,impressions
1200,8000
```

The simulator still creates the audience sample; supplied economics rescale the waste calculation and are marked as `user_spend` or `user_cpc` in the response.

You can also **upload a CSV** in the UI. The file is inspected in code (columns mapped onto spend/impressions/cpc, totals summed deterministically) and read by the live model to guess who the export was aimed at and who might be wasted reach. A realistic sample is bundled at `app/static/demo/last-campaign.csv` for the demo.

### Reliability and fallback behavior

The app is usable with or without an LLM key.

- `USE_CACHE=1` runs entirely on deterministic fixtures and fallbacks.
- Missing API keys also use safe fallback behavior.
- Gemini HTTP 429 rate limits are surfaced in `/api/status` and fall back immediately instead of freezing the UI during long retries.
- The UI distinguishes live, cached, and rate-limited states.

### Persistence and sharing

Custom lab sessions are stored locally in SQLite at `.data/labs.sqlite`.

- Labs have independent IDs, preventing two users from overwriting each other’s in-memory state.
- `/api/labs` lists saved labs.
- A `?lab=<id>` session link can be used to restore a saved lab locally.
- The database is ignored by Git.

## Architecture

```text
Browser dashboard
  ├─ Custom brief, economics, campaign previews, comparison, export
  └─ Streams node updates from FastAPI as NDJSON

FastAPI
  ├─ Lab/session state keyed by X-Lab-Id or lab_id
  ├─ SQLite persistence for custom labs
  ├─ Campaign export and integrations catalog
  └─ Static UI assets

LangGraph campaign lab
  START
    → Optimizer
    → Sampler
    → Buyer panel (parallel persona evaluation)
    → Critic
    → END

Supporting services
  ├─ Brief interpreter: product, buyer, leak, price, CTA, proof
  ├─ Impression sampler: deterministic sample and audience accuracy
  ├─ Economics: off-ICP spend/waste calculations
  ├─ Persona evaluator: intended buyers and audience leak
  ├─ Optimizer: targeting correction then copy rewrite
  └─ LLM adapter: Gemini / compatible endpoint with cache fallback
```

### Key modules

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI routes, lab lifecycle, stream responses, persistence integration, exports. |
| `app/agents/graph.py` | LangGraph definition, streamed node updates, trace metadata, round finalization. |
| `app/agents/brief.py` | Interprets a custom brief into campaign constraints and personas. |
| `app/agents/optimizer.py` | Tightens targeting and rewrites copy while enforcing brief-derived requirements. |
| `app/agents/personas.py` | Buyer / leak persona reactions and fallback behavior. |
| `app/agents/critic.py` | Campaign diagnosis and next-step explanation. |
| `app/impressions.py` | Deterministic impression sampling, audience accuracy, waste calculation, CSV economics parsing. |
| `app/labs_store.py` | Local SQLite persistence. |
| `app/llm.py` | Gemini and compatible LLM adapter, cache fallback, rate-limit status. |
| `app/static/index.html` | Product workflow and browser-side NDJSON stream consumer. |
| `app/static/lab.css` | Control-room design system and responsive UI. |

## Run locally

### Prerequisites

- Python 3.11+ recommended
- A Gemini API key is optional; cache mode works without one

### 1. Configure environment

Copy `.env.example` to `.env`:

```bash
GEMINI_API_KEY=
LLM_API_KEY=
GEMINI_MODEL=gemini-3.6-flash
USE_CACHE=0
```

Use one of the following modes:

**Live Gemini mode**

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.6-flash
USE_CACHE=0
```

**Reliable local/demo cache mode**

```dotenv
USE_CACHE=1
```

Do not commit `.env`. It is ignored by Git.

### 2. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Start the app

Use port `8001` because port `8000` may be occupied by another local application:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Open [http://127.0.0.1:8001/](http://127.0.0.1:8001/).

## Demo flow

For a dependable walkthrough, use cache mode or wait for the Gemini free-tier quota to be available.

1. Enter the lab as a judge or with a local display name.
2. Run **Step 1** and point out the audience leak, waste, and intended-buyer objections.
3. Run **Step 2** and show audience quality improve while copy remains unchanged.
4. Run **Step 3** and show the optimizer revise price/proof/CTA while targeting remains frozen.
5. Open **Custom brief** and use a different business/audience to show the product is not Northline-specific.
6. Paste campaign economics to rescale the waste metric using user-provided numbers.
7. Use the agent timeline to explain the Sampler → Optimizer → buyers → Critic workflow.
8. Export the campaign Markdown report or share the lab link.

## API reference

### Health and status

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Basic health response. |
| `GET /api/status` | Live/cache/rate-limit state and active model. |

### Campaign rounds

| Endpoint | Purpose |
| --- | --- |
| `GET /api/round/{1,2,3}` | Return a completed round payload. |
| `GET /api/round/{1,2,3}/stream` | Return newline-delimited JSON node updates followed by the final payload. |
| `GET /api/lab/play` | Run all three rounds and return comparison data. |
| `POST /api/lab/reset` | Reset the current lab to the Northline baseline. |

Append `?use_cache=1` for deterministic cache behavior. Use `X-Lab-Id: <id>` or `?lab_id=<id>` to isolate a session.

### Custom labs and data

| Endpoint | Purpose |
| --- | --- |
| `POST /api/custom` | Interpret and activate a custom brief. Body: `{ "brief": "..." }`. |
| `POST /api/lab/numbers` | Attach spend/impressions/CPC/CSV economics to the current lab. |
| `GET /api/labs` | List locally persisted labs. |
| `POST /api/labs/{lab_id}/restore` | Restore a persisted lab. |
| `GET /api/export/campaign.md` | Download the current campaign report as Markdown. |
| `GET /api/integrations` | Show what is and is not wired today. |

## Testing

Run the full suite from the project directory:

```bash
python -m pytest tests -q -p no:cacheprovider
```

The suite covers:

- Brief parsing, price extraction, custom audience/persona generation, CTA and proof derivation
- Round progression and frozen-targeting/copy invariants
- LangGraph streaming events and partial metric availability
- Impression targeting accuracy and economics/CSV parsing
- LLM retry/rate-limit status helpers
- Local SQLite lab persistence
- Optimizer safeguards
- UI smoke contracts for core controls, streaming, dashboard, and agent theatre

## Current limitations

Won'tBuy is intentionally honest about the following boundaries:

- Impressions and buyer outcomes are simulated, not historical ad-account results.
- Ad-platform integrations are placeholders; there is no Meta/Google/LinkedIn OAuth or campaign write access.
- Sharing is local to the machine’s SQLite database; it is not a hosted multi-user workspace.
- The export is Markdown, not a styled PDF.
- Gemini free-tier limits can trigger a cached fallback; the UI exposes that state rather than implying a live result.

## Recommended next features

The product should stay focused on campaign diagnosis and evidence, rather than becoming another generic content generator.

### Highest-value features to ship

1. **CSV file uploader with validation** — the current paste/upload path accepts simple CSV text and is inspected in code. A dedicated file dropzone, interactive column-mapping screen, and validation report would make real-campaign import feel like a product rather than a prototype.
2. **Platform adapters, read-only first** — import campaign/ad-set metrics from Meta, Google Ads, and LinkedIn; do not write changes automatically. This would let the simulator seed itself from actual audience and spend data.
3. **Audience builder polish** — the persona editor exists; extend it with saved audience templates, exclusion lists, and firmographic constraints that feed the optimizer's targeting rules directly.
4. **Evidence-backed copy constraints** — let users attach proof sources, customer quotes, product docs, or approved claims. The optimizer can then distinguish permissible proof from unsupported marketing claims.
5. **Experiment history** — persist round history and show score/waste/conversion movement over multiple campaign experiments rather than one three-step lab run.
6. **Shareable hosted reports** — replace local-only lab links with signed hosted reports and a small team workspace.
7. **Styled PDF / slide export** — turn the existing Markdown report into a presentation-ready client or stakeholder artifact.
8. **Learning loop** — the future differentiator. Close the loop between prediction and outcome: let a run record its *predicted* buyer/waste numbers, then later import the campaign's *actual* post-launch metrics (or even the platform's native spend/conversion data) so the agents learn which of their calls were right and get measurably better on your account over time. That turns a one-shot simulator into a model that compounds with every campaign.

### Useful but later

- A/B variant generation with explicit hypotheses and predicted buyer objections
- Budget allocation recommendations across audiences/channels
- Incrementality and holdout-test guidance
- Approval workflow before pushing campaign changes to an ad platform
- Role-based accounts and team collaboration

## Hackathon positioning

The strongest positioning is:

> **Won'tBuy is an AI campaign pre-flight simulator that shows who will not buy before you pay to reach them, then fixes the audience and message in the right order.**

That is stronger than “AI copywriter” because it connects copy generation to an observable diagnosis: it shows *why* a campaign is wrong, what changed, and how the expected campaign health improves.

For a live demo, lead with the agent theatre and the two-failure story, then use a custom brief to prove generality. Keep the claim precise: simulated buyer evaluation and campaign diagnostics today; live ad-account ingestion is the next product step.

## License

No license has been selected yet. Add one before public reuse or commercial distribution.
