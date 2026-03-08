"""
Macro & Risk Agent

Input  (from snapshot, per holding):
  - fundamental_data : beta, country, sector, pct_below_52w_high, pct_above_52w_low
  - technical_data   : volatility_20d_annualized_pct
  - calendar_data    : next_earnings_date, ex_dividend_date

Output (str):
  Per holding:
    - Beta/volatility vs market
    - 52-week positioning (near high = caution; near low = opportunity)
    - Upcoming earnings/dividend dates as near-term catalysts or risk events
    - Geopolitical or regulatory risk flags
  ⚠ flag tickers needing immediate attention.
"""

from .base import BaseAgent, NodeContract, compact_json


class MacroRiskAgent(BaseAgent):
    name     = "macro_risk"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["fundamental_data", "technical_data"],
        required_output_phrases = ["beta", "risk", "earnings"],
        min_output_length       = 100,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a macro and risk analyst. Be direct. "
            "Flag tickers with ⚠ when immediate attention is needed."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Per-ticker risk data: {risk}\n\n"
            "For each holding: 1) beta and 20-day annualised volatility vs market, "
            "2) 52-week positioning — within 5% of 52w high signals caution; "
            "within 5% of 52w low signals potential opportunity, "
            "3) upcoming earnings/dividend dates as near-term catalysts or risk events, "
            "4) geopolitical or regulatory risk — e.g. Taiwan risk for TSMC, "
            "antitrust risk for big tech, rate sensitivity for growth stocks. "
            "Use ⚠ for tickers that need immediate attention."
        )

    def build_prompt_inputs(self, state) -> dict:
        s   = state["snapshot"]
        fd  = s.get("fundamental_data", {})
        td  = s.get("technical_data", {})
        cd  = s.get("calendar_data", {})
        risk_data = {}
        for ticker in s["portfolio_summary"]["holdings"]:
            f = fd.get(ticker, {})
            t = td.get(ticker, {})
            c = cd.get(ticker, {})
            risk_data[ticker] = {
                "beta":               f.get("beta") or t.get("beta"),
                "volatility_20d_pct": t.get("volatility_20d_annualized_pct"),
                "pct_below_52w_high": f.get("pct_below_52w_high"),
                "pct_above_52w_low":  f.get("pct_above_52w_low"),
                "next_earnings":      c.get("next_earnings_date"),
                "ex_dividend_date":   c.get("ex_dividend_date"),
                "country":            f.get("country"),
                "sector":             f.get("sector"),
            }
        return {"risk": compact_json(risk_data, limit=3000)}
