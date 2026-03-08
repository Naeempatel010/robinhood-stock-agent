"""
Shared LangGraph state definition for the analysis pipeline.
All agents read from and write to this TypedDict.
"""

from operator import add
from typing import Annotated, TypedDict

from run_config import RunConfig


class AnalysisState(TypedDict):
    # ── Inputs ─────────────────────────────────────────────────────────
    snapshot:              dict    # full portfolio snapshot from data collection
    historical_comparison: dict    # prev run vs current equity delta
    full_history:          list    # all past DB runs for trend analysis
    run_config:            RunConfig

    # ── Parallel agent outputs (empty string = skipped/disabled) ───────
    fundamental:  str    # per-stock: valuation, ratios, insider, institutional
    technical:    str    # per-stock: RSI, MACD, BB, SMA, volume, alerts
    dcf:          str    # per-stock: intrinsic value vs market price
    sentiment:    str    # per-stock: news + analyst + earnings estimate sentiment
    hot_stocks:   str    # buy candidates outside current portfolio
    portfolio:    str    # concentration, sector exposure, ETF overlap, noise flags
    macro_risk:   str    # beta, vol, 52w proximity, earnings dates, geo risk
    alerts:       str    # rule-based trigger summary
    comparative:  str    # stock vs SPY/QQQ benchmark performance
    trend:        str    # historical equity/holdings trend

    # ── Sequential agent outputs ───────────────────────────────────────
    budget_report:  str  # from cost_agent: what ran/skipped, remaining budget
    market_opinion: str  # 1-3 month outlook synthesising parallel results
    final_summary:  str  # 5-section actionable summary

    # ── Token tracking (add reducer correctly sums parallel updates) ───
    input_tokens:  Annotated[int, add]
    output_tokens: Annotated[int, add]

    # ── Control ────────────────────────────────────────────────────────
    retry_count:   int    # evaluator: 0=first pass, 1=retry pending, 2=done
    stopped_early: bool   # True if any node was skipped due to budget
