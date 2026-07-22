# Trend Research Agent

A trend-intelligence engine for marketing. Feed it any campaign — a screenshot, a link, or a rough idea — and it returns a complete campaign brief: what play it runs, why it worked, the emotion it fires, whether the trend is `new / rising / peaked / fading` (with live web citations), which of *our* audiences it can reach, **the honest case against copying it**, and a 0–100 relevance score with charts. It can also scan the market on its own every day and flag rising patterns before they saturate.

Built for [HiDevs](https://hidevs.xyz) (a GenAI upskilling brand), but company-agnostic — three editable config files retarget it to any business.

**Stack:** Python · FastAPI · LangGraph / LangChain · Google Gemini (multimodal + Google-Search grounding) · Qdrant (embedded — no Docker) · Crawl4AI + Playwright · APScheduler

---

## What it does

- **Deconstructs a campaign** — names the play, hook, emotional trigger, timing, and visual strategy; explains *why* it worked and gives one stealable takeaway for us.
- **Judges the trend** — `new / rising / peaked / fading`, grounded in memory frequency + live web search, with citations.
- **Maps it to our audiences** — which of our segments it fits, the angle, and what to actually make.
- **Argues the case against it** — a dedicated adversarial pass the schema won't let stay silent: weaknesses by severity, brand-safety flags, and what couldn't be verified. (LLMs default to praise; this is the safeguard against it.)
- **Scores it** — a relevance percentage across 10 dimensions, 4 of them computed in code, rendered as charts.
- **Watches the market** — a daily radar scans RSS + GDELT sources, filters ~80–90% of the noise, and deep-analyzes only what's notable; a weekly digest and monthly competitor map are generated automatically.

---

## Setup (local)

**Prerequisites:** Python 3.11+ and a free Gemini API key ([get one here](https://aistudio.google.com/apikey)).

```powershell
# 1. clone and enter
git clone <your-repo-url> trend-research-agent
cd trend-research-agent

# 2. create a virtual environment + install dependencies
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 3. install the headless browser the radar's crawler uses
.venv\Scripts\python -m playwright install chromium

# 4. configure your key
copy .env.example .env
#    then open .env and set GOOGLE_API_KEY=your-key
```

> On macOS / Linux use `.venv/bin/pip` and `.venv/bin/python` instead of `.venv\Scripts\...`, and `cp` instead of `copy`.

Everything runs locally with no Docker and no external services: vector memory is an embedded Qdrant, and reports are stored as local JSON by default.

---

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Then open:

| URL | What |
|---|---|
| **http://localhost:8000/** | Review UI — submit a campaign, read the brief, approve/reject |
| **http://localhost:8000/dashboard** | Trends, alerts, competitor map, weekly digest, analytics charts, ask-the-agent |
| **http://localhost:8000/docs** | Interactive API documentation |

**Quick test:** open `/`, paste a line like *"This Blinkit billboard was everywhere near the main road"*, optionally attach a screenshot, and click **Analyze**. A full brief comes back in ~90 seconds.

---

## How it works

```
user input (text + images)          radar (daily, automated)
        │                    RSS + GDELT → URL dedupe → Flash triage (~80-90% filtered)
        │                                   │ survivors: Crawl4AI → full text + screenshot
        ▼                                   ▼
   dedupe (never analyze the same campaign twice — image hashes + embeddings)
        ▼
   palette extraction (code, not LLM)
        ▼
   3 specialists in parallel: Strategy · Hook & Copy · Visual
        ▼
   recall similar past campaigns from memory (Qdrant)
        ▼
   composer → the campaign deconstruction
        ▼
   trend check: memory frequency + Google-Search-grounded verdict + citations
        ▼
   audience fit  ‖  critique (parallel): who to aim at + the case against
        ▼
   finalize: scorecard · store report · index into memory · lifecycle event · alert
```

---

## Configure for any company

Everything company-specific lives in three editable files — swap them and the same engine serves a different business:

- [`config/brand.md`](config/brand.md) — who "we" are, voice, channels
- [`config/buckets.json`](config/buckets.json) — audience segments with pains + channels
- [`config/sources.json`](config/sources.json) (+ [`players.json`](config/players.json)) — what the radar watches

Prompts and specialist "skill packs" (`app/prompts/`, `app/skill_packs/`) are versioned markdown; dropping a new doc into a specialist's folder upgrades it with zero code change.

---

## Tests

```powershell
.venv\Scripts\python -m pytest tests\ -q          # 94 tests, no API key needed — models are faked
.venv\Scripts\python -m scripts.eval_reports      # scored quality rubric (needs a real key)
```

---

## Cost

Roughly **$0.05 per campaign** (measured), ~90 seconds per report, $0 infrastructure. Flash-class model everywhere except optional final synthesis; dedupe before every analysis and triage before every deep scan keep spend down; every model call's token usage is logged and surfaced at `GET /costs`. Runs on Gemini's free tier for low-volume use.
