# Agent Architecture

## Graph Flow Diagram

```
                                    START
                                      │
   ┌──────────┬──────────┬───────┬────┴──────┬───────────┐
   │          │          │       │           │           │
[1]fund.  [2]tech.  [3]dcf  [4]sent.  [5]hot_stocks  [6]portfolio
   │          │          │       │           │           │
   └──────────┴──────────┴───┬───┴───────────┘           │
                             │                           │
   ┌─────────────────────────┘           ┌───────────────┘
   │          │          │               │
[7]macro  [8]alerts  [9]comp.  [10]trend
   │          │          │          │
   └──────────┴──────────┴────┬─────┘
                              │
                         [cost_agent]    ← no LLM: budget review + trim decision
                              │
                       [market_opinion]  ← synthesises parallel outputs → 3-bullet outlook
                              │
                       [final_summary]   ← 5-section actionable report
                              │
                          [evaluator]    ← structural check (no LLM)
                         ┌────┴────┐
                       retry      done
                         │           │
                  [final_summary]   END
                   (retry, once)
```

---

## Parallel Agents

Each parallel agent runs concurrently from START. They share no state with each other during execution — only the final merged state is visible to downstream agents.

Each agent implements `BaseAgent` with:
- `contract: NodeContract` — validates inputs before LLM call and output after
- Per-node quality evaluation + one retry if output fails quality check
- Retry-with-backoff for network/API failures (up to 3 attempts, exponential backoff)

---

### [1] fundamental
| | |
|---|---|
| **File** | `agents/fundamental.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Per-stock valuation, financial health, insider + institutional signals |

**Required inputs (snapshot keys):** `fundamental_data`, `portfolio_summary`

**Input fields used:**
```
fundamental_data:  P/E, fwd P/E, P/B, P/S, PEG, EV/EBITDA
                   revenue_growth_yoy, revenue_growth_qoq
                   earnings_growth_yoy, earnings_growth_qoq
                   profit_margin, operating_margin, ROE, ROA
                   debt_to_equity, current_ratio, quick_ratio
                   free_cash_flow, operating_cash_flow, EPS
                   analyst_rating, target_price, analyst_count
                   52w_high, 52w_low, pct_below_52w_high
short_interest_data: short_percent_of_float, short_ratio_days
                     short_interest_mom_change{direction, pct}
insider_data:      open-market transactions only (gifts/awards filtered)
institutional_data: top 10 holders (13F)
```

**Output contract:**
- Min 150 characters
- Must contain "strong", "neutral", or "weak"
- One paragraph per stock ending with: `Verdict: Strong / Neutral / Weak`

---

### [2] technical
| | |
|---|---|
| **File** | `agents/technical.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Price action, momentum, volatility, support/resistance, correlation |

**Required inputs:** `technical_data`

**Input fields used:**
```
technical_data (per ticker):
  current_price, trend_direction
  rsi_14, macd, macd_signal, macd_histogram
  bb_upper, bb_lower, bb_mid
  sma_50, sma_200, ema_20
  volatility_20d_annualized_pct
  volume, avg_volume_20d, volume_spike_ratio
  support, resistance
  change_1w/1m/3m/6m/1y_pct
  alerts[]          (pre-computed rule-based flags)
  vs_benchmark{}    (relative to SPY, QQQ)

correlation_data:
  matrix, avg_correlation, diversification_score
```

**Output contract:**
- Min 120 characters
- Must contain "rsi", "macd", "sma", "support"
- Per stock: trend, RSI flag, MACD, BB, SMA, volume, support/resistance, vol
- Then: correlated pairs, diversification score, rebalancing suggestion

---

### [3] dcf
| | |
|---|---|
| **File** | `agents/dcf.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Intrinsic value vs market price (10% discount, 3% terminal, 5yr) |

**Required inputs:** `dcf_results`

**Input fields used:**
```
dcf_results (per ticker):
  intrinsic_value, current_price
  margin_of_safety_pct
  verdict: Undervalued / Fair Value / Overvalued
  (or note: "ETF — DCF not applicable" / "Insufficient data")
```

**Output contract:**
- Min 80 characters
- Must contain "undervalued", "overvalued", or "margin"
- One line per stock with verdict and position sizing implication

---

### [4] sentiment
| | |
|---|---|
| **File** | `agents/sentiment.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | News + analyst consensus + earnings estimate direction |

**Required inputs:** `news_data`

**Input fields used:**
```
news_data:         up to 6 headlines per ticker (title, publisher, date)
market_news:       up to 8 SPY/market headlines
fundamental_data:  analyst_rating, target_price, target_high, target_low,
                   analyst_count, current_price, eps_next_year_est
```

**Output contract:**
- Min 100 characters
- Must contain "bullish", "bearish", or "neutral"
- Per stock: sentiment rating + reason, analyst consensus + upside/downside %
- One-sentence overall market sentiment

---

### [5] hot_stocks
| | |
|---|---|
| **File** | `agents/hot_stocks.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Buy candidates from HOT_TICKERS not currently held |

**Required inputs:** `portfolio_summary`

**Input (live yfinance fetch at runtime):**
```
HOT_TICKERS (from config.py) minus current holdings:
  price, P/E, fwd P/E, revenue_growth, analyst_rating,
  target_price, sector
```

**Output contract:**
- Min 60 characters
- Top 3 candidates: ticker, current price, suggested entry price, one-line thesis

---

### [6] portfolio
| | |
|---|---|
| **File** | `agents/portfolio.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Portfolio structure: concentration, sector, ETF overlap, noise |

**Required inputs:** `portfolio_metrics`, `portfolio_summary`

**Input fields used:**
```
portfolio_metrics:
  total_equity
  concentration{ticker: {equity, pct_of_portfolio, noise}}
  sector_exposure{sector: pct}
  noise_positions[]    (<1% positions)
  etf_overlaps{etf: [overlapping_tickers]}
```

**Output contract:**
- Min 100 characters
- Must contain "concentration", "sector", "position"
- Covers: oversized positions, sector imbalance, ETF double-counting, noise

---

### [7] macro_risk
| | |
|---|---|
| **File** | `agents/macro_risk.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Market risk, 52-week proximity, upcoming catalysts, geo/regulatory flags |

**Required inputs:** `fundamental_data`, `technical_data`

**Input fields used (per holding):**
```
fundamental_data:  beta, country, sector,
                   pct_below_52w_high, pct_above_52w_low
technical_data:    volatility_20d_annualized_pct
calendar_data:     next_earnings_date, ex_dividend_date
```

**Output contract:**
- Min 100 characters
- Must contain "beta", "risk", "earnings"
- Per holding: beta/vol, 52w positioning, earnings/dividend dates, geo risk
- ⚠ flags for tickers needing immediate attention

---

### [8] alerts
| | |
|---|---|
| **File** | `agents/alerts.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Rule-based trigger summary — skips LLM if no alerts fired |

**Required inputs:** `technical_data`

**Input (pre-computed rules):**

| Rule | Trigger Condition |
|---|---|
| RSI overbought | RSI-14 > 70 |
| RSI oversold | RSI-14 < 30 |
| Volume spike | current volume > 2× 20-day avg |
| BB upper breach | price ≥ Bollinger upper band |
| BB lower breach | price ≤ Bollinger lower band |
| MACD crossover forming | \|MACD − signal\| < 0.5 |
| SMA50/200 imminent cross | \|SMA50 − SMA200\| / SMA200 < 0.5% |
| Short interest spike | MoM change > 20% |
| Open-market insider sale | sale transaction in insider_data |

**Output contract:**
- Min 20 characters (may legitimately be "No active alerts triggered.")
- Per alert: 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW + signal meaning + suggested action
- Sorted by severity

---

### [9] comparative
| | |
|---|---|
| **File** | `agents/comparative.py` |
| **LLM tier** | analysis (max_tokens=1024) |
| **Purpose** | Stock performance vs S&P 500 and Nasdaq 100 |

**Required inputs:** `technical_data`

**Input fields used:**
```
technical_data (per holding):
  change_1w/1m/3m/6m/1y_pct
  vs_benchmark{"S&P 500": {1w,1m,3m,6m,1y}, "Nasdaq 100": {...}}
  trend_direction
```

**Output contract:**
- Min 80 characters
- Must contain "outperform", "underperform", "benchmark"
- One line per stock with relative return vs benchmarks
- Summary: outperformers to hold, underperformers to review

---

### [10] trend
| | |
|---|---|
| **File** | `agents/trend.py` |
| **LLM tier** | summary (max_tokens=512) |
| **Purpose** | Historical equity and holdings trend across past N runs |

**Required inputs:** `full_history` in state (last `trend_history_runs` runs, default 5)

**Input (from DB history):**
```
per run: date, equity, cash
         holdings{ticker: {equity, price}}
```

**Output contract:**
- Min 80 characters
- Must contain "equity", "trend"
- Exactly 4 bullet points: equity trend %, top performers/laggards,
  concentration shifts, forward outlook
- Skips LLM if fewer than 2 runs exist

---

## Cost Agent (sequential, no LLM)

**File:** `agents/cost_agent.py`

After all parallel agents complete, reviews budget status.

**Input:**
- `state["input_tokens"]`, `state["output_tokens"]` — accumulated so far
- `state["run_config"]` — budget limits
- All parallel result fields

**Output:**
- `budget_report` (str) — summary of runs/skips/remaining budget
- `stopped_early = True` if sequential nodes cannot afford to run

**Logic:**
1. Count what ran vs was skipped
2. Estimate sequential node cost (`market_opinion + final_summary + reserve`)
3. If remaining < needed → set `stopped_early`, return partial report
4. If remaining < 2× needed → log budget-crunch warning (final_summary will trim inputs)

---

## Sequential Agents

### market_opinion
**File:** `agents/market_opinion.py` | **LLM tier:** summary

**Inputs (truncated text from):** fundamental, technical, sentiment, alerts, macro_risk

**Output contract:** Min 80 chars, must contain "risk", "outlook"/"macro", "direction". Exactly 3 bullet points:
- Macro environment
- Key risk
- Overall portfolio direction

---

### final_summary
**File:** `agents/final_summary.py` | **LLM tier:** summary

**Inputs:** All parallel + sequential outputs + historical_comparison + portfolio + budget_report

**Budget-crunch mode:** If remaining < $0.30, input truncation tightens automatically.

**Output contract:** Min 100 chars, must contain all 5 headers. Retried once by evaluator if incomplete.

```
1. RISK RATING: X/10 — reason
2. PORTFOLIO RATING: X/10 — reason
3. REBALANCING: action or 'None needed'
4. SELL NOW: ticker + reason, or 'None'
5. BUY NOW: up to 3 — ticker, price, one-line thesis
```

---

### evaluator
**File:** `agents/evaluator.py` | **No LLM**

Checks `final_summary` for all 5 required section headers. Returns `retry_count=1` to re-run `final_summary` once if sections are missing and budget permits. Disabled when `run_config.evaluate_nodes = false`.

---

## Failure Handling

All LLM calls go through `invoke_with_retry` in `agents/base.py`:

| Error type | Behaviour |
|---|---|
| `APIConnectionError` | Retry with exponential backoff (×3, base 1s) |
| `APITimeoutError` | Retry with exponential backoff (×3, base 1s) |
| `RateLimitError` | Wait 60s then retry (×3) |
| `APIStatusError 5xx` | Retry with exponential backoff (×3) |
| `APIStatusError 4xx` | Raise `NodeExecutionError` immediately |
| `NodeExecutionError` | Agent returns `[failed — ...]` string, `stopped_early=True` |

Input validation errors (missing snapshot keys) → agent returns `[skipped — ...]` without calling LLM.

---

## Adding a New Agent

```
1. Create agents/my_agent.py:

   from .base import BaseAgent, NodeContract, compact_json

   class MyAgent(BaseAgent):
       name     = "my_agent"
       llm_tier = "analysis"
       contract = NodeContract(
           required_snapshot_keys  = ["my_data"],
           required_output_phrases = ["expected_phrase"],
           min_output_length       = 100,
       )

       @property
       def system_prompt(self) -> str:
           return "You are ..."

       @property
       def human_prompt(self) -> str:
           return "Data: {my_data}\n\nAnalyse ..."

       def build_prompt_inputs(self, state) -> dict:
           return {"my_data": compact_json(state["snapshot"].get("my_data", {}))}

2. Register in agents/__init__.py:
   from .my_agent import MyAgent
   ALL_PARALLEL_AGENTS["my_agent"] = MyAgent()

3. Add to RunConfig (run_config.py):
   my_agent: bool = True

4. Add to analysis.toml:
   my_agent = true

Done — the graph includes it automatically.
```
