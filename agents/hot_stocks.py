"""
Hot Stocks Agent

Input  (live yfinance fetch at runtime — not from snapshot):
  - HOT_TICKERS config list
  - Current portfolio holdings (to exclude already-held tickers)
  - Per-ticker: price, P/E, forward P/E, revenue growth, analyst rating, target price

Output (str):
  Top 3 buy candidates outside the current portfolio:
    - Ticker, current price, suggested entry price
    - One-line thesis
"""

import yfinance as yf

from config import HOT_TICKERS
from .base import BaseAgent, NodeContract, compact_json


class HotStocksAgent(BaseAgent):
    name     = "hot_stocks"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["portfolio_summary"],
        required_output_phrases = [],   # free-form output, just check length
        min_output_length       = 60,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a growth stock analyst. Be specific — "
            "recommend actual entry prices based on the data provided."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Current portfolio tickers: {current}\n"
            "Hot stocks not yet in portfolio: {hot}\n\n"
            "Select the top 3 buy candidates. For each: ticker, current price, "
            "suggested entry price (with brief reasoning), one-line thesis. "
            "Only recommend stocks with strong analyst conviction or clear catalyst."
        )

    def build_prompt_inputs(self, state) -> dict:
        current = list(state["snapshot"]["portfolio_summary"]["holdings"].keys())
        hot_data = {}
        for ticker in HOT_TICKERS:
            if ticker in current:
                continue
            try:
                info = yf.Ticker(ticker).fast_info
                full = yf.Ticker(ticker).info or {}
                hot_data[ticker] = {
                    "price":      getattr(info, "last_price", None),
                    "pe":         full.get("trailingPE"),
                    "fwd_pe":     full.get("forwardPE"),
                    "rev_growth": full.get("revenueGrowth"),
                    "analyst":    full.get("recommendationKey"),
                    "target":     full.get("targetMeanPrice"),
                    "sector":     full.get("sector"),
                }
            except Exception:
                pass
        return {
            "current": ", ".join(current),
            "hot":     compact_json(hot_data),
        }
