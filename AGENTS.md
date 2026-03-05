# Agent Orchestration

## Flow Diagram

```
                              ┌─────────────────────────────────────────────────────────────┐
                              │                     PARALLEL PHASE                          │
                              │                                                             │
          ┌───────┐           │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐      │
          │       │ ─────────►│  │ fundamental │   │  technical  │   │     dcf     │      │
          │ START │           │  └─────────────┘   └─────────────┘   └─────────────┘      │
          │       │ ─────────►│  ┌─────────────┐   ┌─────────────┐                        │
          └───────┘           │  │  sentiment  │   │  hot_stocks │                        │
                              │  └─────────────┘   └─────────────┘                        │
                              └──────────────────────────┬──────────────────────────────────┘
                                                         │ all 5 complete (barrier sync)
                                                         ▼
                                              ┌──────────────────┐
                                              │  market_opinion  │
                                              └────────┬─────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │  final_summary   │◄──────────────────┐
                                              └────────┬─────────┘                   │
                                                       │                             │ retry
                                                       ▼                             │ (once)
                                              ┌──────────────────┐                  │
                                              │    evaluator     │──── missing ──────┘
                                              └────────┬─────────┘   sections?
                                                       │
                                                  all present
                                                       │
                                                       ▼
                                                    ┌─────┐
                                                    │ END │
                                                    └─────┘
```

---

## What We Borrowed from mcp-agent

Inspired by [lastmile-ai/mcp-agent financial analyzer](https://github.com/lastmile-ai/mcp-agent/tree/main/examples/usecases/mcp_financial_analyzer).

### Followed

**EvaluatorOptimizer loop** — Their `EvaluatorOptimizerLLM` wraps an agent with a quality-rating agent that loops until a minimum score (`GOOD`) is reached. We copied this as the `evaluator` node: it checks that the final summary contains all 5 required sections and routes back to `final_summary` for one retry if any are missing.

**Single-responsibility agents** — Their design gives each agent exactly one job and scopes its tool access to only what it needs (e.g. only the report writer touches the filesystem). Each of our LangGraph nodes follows the same principle — one job, reads only the snapshot keys it actually needs.

**Staged pipeline with quality gates** — Their orchestrator runs data collection → quality evaluation → analysis → report in sequence, where each stage only starts after the previous passes a bar. We follow the same staged structure: parallel analysis → market opinion → final summary → quality gate → END.

### Not Followed

**Dynamic LLM planner** — Their `Orchestrator` is an LLM that reads the task and plans the workflow at runtime (`plan_type="full"`). Ours is a static LangGraph topology fixed at build time. This makes our graph faster, cheaper, and fully predictable.

**MCP servers as tool backends** — They route tool access through MCP servers (Google Search, filesystem). We use direct Python calls (yfinance, LangChain) since our data sources are well-defined.

**Iterative data re-fetch loop** — Their data collector keeps searching until the evaluator rates the research as GOOD, potentially running many LLM + search iterations. We do not re-fetch market data on quality failure — only the final narrative summary is retried.

**LLM-based quality grading** — Their evaluator is an LLM that produces a 4-tier rating (EXCELLENT / GOOD / FAIR / POOR) with written feedback. Our evaluator is a deterministic string check (no LLM call, no cost) — it passes if all 5 section headings are present.

---

## Agents

**fundamental** — Reads yfinance fundamentals (P/E, EPS, revenue growth, D/E, ROE), short interest data, and recent insider transactions for each holding. Rates each stock Strong / Neutral / Weak and flags squeeze risk or insider selling signals.

**technical** — Reads RSI, MACD, Bollinger Bands, and SMA 50/200 for each ticker. Identifies trend direction and momentum signals. Then analyzes the correlation matrix and diversification score, flagging over-correlated pairs.

**dcf** — Runs a 5-year discounted cash flow valuation (10% discount rate, 3% terminal growth) and computes margin of safety vs current price. Notes caveats for ETFs, negative-FCF companies, and high-growth stocks where DCF is conservative.

**sentiment** — Reads the latest 3 headlines per ticker plus 5 SPY market headlines. Rates each stock Bullish / Neutral / Bearish and gives an overall market sentiment reading.

**hot_stocks** — Fetches live data for a watchlist (NVDA, META, TSLA, AMZN, MSFT, AAPL, GOOGL, AMD, PLTR, ARM, AVGO, SMCI), skipping any already held. Recommends up to 3 buy candidates with entry price and one-line thesis.

**market_opinion** — Sequential. Synthesizes the fundamental, technical, and sentiment outputs into a 3-bullet macro outlook for the next 1–3 months: macro environment, key risk, directional call.

**final_summary** — Sequential. Condenses everything into a ≤200-word structured report with exactly 5 sections: Risk Rating, Portfolio Rating, Rebalancing, Sell Now, Buy Now. If retried, receives a stricter prompt noting the missing sections.

**evaluator** — Quality gate (no LLM, no cost). Checks that the final summary contains all 5 required section headings. If any are missing and the run budget allows, routes back to `final_summary` for one retry. Otherwise passes to END.

---

## Token Budget

Each node checks remaining budget before calling the LLM. If less than $0.50 of the $5.00 run budget remains, the node is skipped and flagged as `stopped_early`. Parallel token counts are summed correctly via LangGraph's `Annotated[int, add]` reducer — without it, parallel nodes would overwrite each other's counts.

| Model tier | Used by | max_tokens |
|---|---|---|
| `_llm_analysis` | fundamental, technical, dcf, sentiment, hot_stocks | 1024 |
| `_llm_summary` | market_opinion, final_summary | 512 |

Pricing: $3.00 / 1M input tokens, $15.00 / 1M output tokens (claude-sonnet-4-6).
