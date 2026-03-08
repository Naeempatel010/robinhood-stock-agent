# Robinhood Portfolio Analyzer

Multi-agent Claude pipeline that pulls your Robinhood holdings, fetches comprehensive market data, and produces an actionable portfolio analysis report.

---

## Installation

```bash
pip install robin_stocks langchain langchain-anthropic langgraph yfinance ta openpyxl numpy pandas anthropic tinydb
```

---

## First-time Setup

### 1. Create your credentials file

```bash
cp credentials.py.example credentials.py
# edit credentials.py with your Robinhood email/password and Anthropic API key
```

`credentials.py` is only needed **once**. On first run it is read and saved to the local database. All subsequent runs load credentials directly from the DB — you can delete (or ignore) `credentials.py` after that.

### 2. Run

```bash
python analyze.py --data --analysis
```

Your Robinhood session token is stored in the local DB after the first login and reused on every subsequent run (no password sent to Robinhood unless the token expires and cannot be refreshed).

---

## Usage

```bash
# Collect fresh portfolio data and store a snapshot
python analyze.py --data

# Analyse the latest snapshot (no Robinhood login needed)
python analyze.py --analysis

# Collect + analyse in one go (most common)
python analyze.py --data --analysis

# Run as a specific user
python analyze.py --data --analysis --user naeem

# Use a custom analysis config
python analyze.py --analysis --config my_quick.toml

# Include extra holdings from a plain-English text file
python analyze.py --data --analysis --holdings-file mine.txt

# Migrate legacy .json.gz and history.json into the DB
python analyze.py --migrate
```

---

## Analysis Config

Copy `analysis.toml` and edit to select which agents run:

```toml
[analyses]
fundamental        = true
technical          = true
dcf                = true
sentiment          = true
hot_stocks         = true
portfolio          = true   # concentration, sector, ETF overlap, noise flags
macro_risk         = true   # beta, volatility, earnings dates, geo risk
alerts             = true   # RSI, BB, volume spike, insider sells, short spikes
comparative        = true   # vs S&P 500 and Nasdaq 100
trend              = true   # historical equity trend (requires ≥2 past runs)
trend_history_runs = 5      # how many past runs to include in trend analysis
evaluate_nodes     = true   # per-node quality check + retry if output is weak

[budget]
total_usd   = 5.00
reserve_usd = 0.50

[report]
txt  = true
xlsx = true
```

Run with your custom config:
```bash
python analyze.py --analysis --config my_quick.toml
```

---

## Pre-run Validation

Before any analysis starts, the tool checks:

1. **API key validity** — lightweight Anthropic call to confirm key works
2. **User budget** — `run_config.total_usd` must not exceed user's remaining allowance
3. **Budget floor** — configured budget must cover at least the enabled agents
4. **Snapshot exists** — if `--analysis` without `--data`, a snapshot must be in the DB

---

## Agent Pipeline

10 parallel agents + cost agent + 2 sequential agents + evaluator:

```
START
├── fundamental   (valuation, ratios, insider, institutional)
├── technical     (RSI, MACD, BB, SMA, volume, support/resistance)
├── dcf           (intrinsic value vs market price)
├── sentiment     (news + analyst + earnings estimates)
├── hot_stocks    (buy candidates outside portfolio)
├── portfolio     (concentration, sector, ETF overlap, noise)
├── macro_risk    (beta, vol, 52w, earnings dates, geo risk)
├── alerts        (rule-based triggers, no LLM if nothing fired)
├── comparative   (vs S&P 500 and Nasdaq 100)
└── trend         (historical equity/holdings trend)
         │
    cost_agent    (budget review, dynamic trim if tight)
         │
   market_opinion (1-3 month outlook)
         │
   final_summary  (5-section actionable report)
         │
     evaluator    (structural check → retry once if incomplete)
         │
        END
```

See [`AGENTS.md`](AGENTS.md) for detailed input/output contracts per agent.

---

## Credential & Token Storage

All credentials are stored in the **local** `portfolio_db.json` — never committed to git.

| Item | How it's stored |
|---|---|
| Robinhood username & password | TinyDB `users` table (local only) |
| Robinhood session token | Binary pickle, base64-encoded in DB; restored before each login so the password is not sent unless the token has fully expired |
| Anthropic API key | TinyDB `users` table (local only) |

On first run, provide `credentials.py`. On subsequent runs, credentials are loaded from the DB automatically — `credentials.py` is no longer required.

---

## Storage

All data is stored in a local TinyDB database (`portfolio_db.json`). Large blobs (snapshots and analyses) are written as JSON files in `data/`.

| Store | Contents |
|---|---|
| `portfolio_db.json` | users (incl. credentials + token), snapshot metadata, analysis metadata, history |
| `data/snapshots/<date>_<ts>.json` | Full portfolio + market data snapshot |
| `data/analyses/<date>_<ts>.json` | Full Claude analysis output |

The database contains credentials and personal financial data — it is excluded from git via `.gitignore`.

---

## Output Files

| File | Description |
|---|---|
| `analysis.txt` | Full narrative report (all agent sections + final summary) |
| `portfolio_analysis.xlsx` | Excel workbook — 8 data sheets |

### Excel Sheets
`Holdings` · `Fundamental` · `Technical` · `DCF Valuation` · `Short Interest` · `Insider Trading` · `Correlation` · `History`

---

## Adding a New Agent

1. Create `agents/my_agent.py` subclassing `BaseAgent`
2. Define `name`, `contract`, `system_prompt`, `human_prompt`, `build_prompt_inputs`
3. Add an instance to `ALL_PARALLEL_AGENTS` in `agents/__init__.py`
4. Add a bool toggle to `RunConfig` in `run_config.py`
5. Add it to `analysis.toml`

The graph picks it up automatically.

---

## Key Files

```
analyze.py           CLI entry point + data collection
analysis.py          LangGraph graph definition (imports from agents/)
agents/              One file per agent
  __init__.py        Agent registry (ALL_PARALLEL_AGENTS)
  base.py            BaseAgent, NodeContract, retry logic, helpers
  state.py           AnalysisState TypedDict
  fundamental.py … trend.py   Individual agent implementations
  cost_agent.py      Budget reviewer (no LLM)
  market_opinion.py  Sequential synthesis agent
  final_summary.py   5-section report agent
  evaluator.py       Quality gate (no LLM)
config.py            HOT_TICKERS, DCF params, credential loader
run_config.py        RunConfig dataclass + TOML loader
validation.py        Pre-run checks (API key, budget, snapshot existence)
db.py                TinyDB store (users, snapshots, analyses, history, tokens)
market_data.py       yfinance fetching + technicals + portfolio metrics
broker.py            Broker ABC + StaticBroker + TextFileBroker
broker_robinhood.py  RobinhoodBroker (token-aware login with DB persistence)
report.py            analysis.txt + xlsx generation
credentials.py.example  Template — copy to credentials.py for first-time setup
AGENTS.md            Full agent contracts and flow diagram
```
