# Robinhood Portfolio Analyzer

Pulls your Robinhood holdings, fetches market data, and runs a multi-agent Claude analysis. Outputs a narrative report and an Excel workbook.

---

## Setup

```bash
pip install robin_stocks langchain langchain-anthropic langgraph yfinance ta openpyxl numpy pandas anthropic
```

Credentials and settings live in `config.py` — edit before first run.

---

## Usage

```bash
# Collect fresh data and store a snapshot
python analyze.py --data

# Analyze the latest stored snapshot (no network calls to Robinhood)
python analyze.py --analysis

# Collect then analyze in one go
python analyze.py --data --analysis

# Include additional holdings from a plain-English text file
python analyze.py --data --analysis --holdings-file mine.txt
```

### `--holdings-file` format

Write your holdings in plain English. Claude parses it into tickers and share counts:

```
I have 50 shares of Apple and 10 shares of Tesla bought at $220.
Also 5 shares of Berkshire B.
```

---

## Output Files

| File | Description |
|---|---|
| `analysis.txt` | Full narrative report (all 7 analysis sections + final summary) |
| `portfolio_analysis.xlsx` | Excel workbook with 8 data sheets |
| `portfolio_snapshots.json.gz` | Compressed history of every `--data` run |
| `portfolio_history.json` | Lightweight equity timeline used for run-to-run comparison |

### Excel sheets
`Holdings` · `Fundamental` · `Technical` · `DCF Valuation` · `Short Interest` · `Insider Trading` · `Correlation` · `History`

---

## Agent Pipeline

Five analysis agents run in parallel, followed by three sequential agents:

```
START → [fundamental] [technical] [dcf] [sentiment] [hot_stocks]  ← parallel
                              ↓ (all complete)
                       [market_opinion]
                              ↓
                       [final_summary]
                              ↓
                         [evaluator] → retry once if sections missing
                              ↓
                             END
```

See [`AGENTS.md`](AGENTS.md) for full diagram and agent descriptions.

---

## Multi-Broker Support

The analyzer merges holdings from multiple sources:

| Source | How |
|---|---|
| Robinhood | Live via `robin_stocks` API |
| Vesting / ESPP | Hardcoded in `config.py` under `STATIC_HOLDINGS` |
| Text file | `--holdings-file` — Claude parses natural language into tickers |

Same ticker across brokers → shares and equity are summed.

---

## Token Budget

Each run has a **$5.00 budget**. Analysis stops automatically if less than **$0.50** remains, returning partial results. Cost and token counts are printed after every agent call.

Typical full run cost: ~$0.50–$1.50 depending on portfolio size.

---

## Key Files

```
analyze.py          CLI entry point
config.py           Credentials, static holdings, DCF params
broker.py           Broker ABC + StaticBroker + TextFileBroker
broker_robinhood.py RobinhoodBroker
market_data.py      yfinance fetching + technical/DCF computation
analysis.py         LangGraph orchestration + all Claude calls
report.py           analysis.txt + portfolio_analysis.xlsx generation
data_store.py       Queryable compressed snapshot store
AGENTS.md           Agent architecture and mcp-agent design notes
```
