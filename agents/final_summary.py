"""
Final Summary Agent (sequential)

Input  (from state — synthesises all agent outputs):
  - portfolio_summary   : equity, cash, holdings
  - historical_comparison: equity delta vs prior run
  - All parallel agent outputs (fundamental, technical, dcf, sentiment,
    portfolio, macro_risk, alerts, comparative, trend, hot_stocks)
  - market_opinion
  - budget_report (from cost_agent)
  - retry_count (1 = this is a retry, must include all 5 sections)

Output (str):
  Exactly 5 sections, one line each, ≤200 words total:
    1. RISK RATING: X/10 — reason
    2. PORTFOLIO RATING: X/10 — reason
    3. REBALANCING: action or None needed
    4. SELL NOW: ticker + reason, or None
    5. BUY NOW: up to 3 — ticker, price, one-line thesis
"""

from .base import BaseAgent, NodeContract, budget_ok, remaining as _remaining, compact_json, slim_holdings


class FinalSummaryAgent(BaseAgent):
    name     = "final_summary"
    llm_tier = "summary"
    contract = NodeContract(
        required_snapshot_keys  = ["portfolio_summary"],
        required_output_phrases = ["risk rating", "portfolio rating", "rebalancing", "sell now", "buy now"],
        min_output_length       = 100,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a senior portfolio advisor. Under 200 words total. "
            "You MUST include all 5 numbered sections."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Portfolio: {portfolio}\nHistory vs prior run: {history}\n"
            "Fundamental: {f}\nTechnical: {t}\nDCF: {d}\nSentiment: {s}\n"
            "Opinion: {o}\nPortfolio risk: {pr}\nMacro: {mr}\n"
            "Alerts: {al}\nComparative: {cp}\nTrend: {tr}\nHot stocks: {h}\n"
            "Budget: {budget}\n\n"
            "Respond with EXACTLY these 5 numbered sections (one line each):\n"
            "1. RISK RATING: X/10 — reason\n"
            "2. PORTFOLIO RATING: X/10 — reason\n"
            "3. REBALANCING: specific action or 'None needed'\n"
            "4. SELL NOW: ticker + reason, or 'None'\n"
            "5. BUY NOW: up to 3 — ticker, price, one-line thesis"
            "{retry_note}"
        )

    def build_prompt_inputs(self, state) -> dict:
        ps       = state["snapshot"]["portfolio_summary"]
        hc       = state["historical_comparison"]
        is_retry = state["retry_count"] == 1
        retry_note = (
            "\n\nIMPORTANT: Previous attempt was missing required sections. "
            "You MUST include all 5 numbered sections."
            if is_retry else ""
        )
        # In budget-crunch mode, trim lower-priority inputs aggressively
        tight = _remaining(state) < 0.30
        trunc = lambda s, hi, lo: (s or "N/A")[:lo if tight else hi]
        return {
            "portfolio":   compact_json({
                **slim_holdings(ps["holdings"]),
                "equity": ps["equity"],
                "cash":   ps["cash"],
            }),
            "history":     compact_json(hc) if hc else "First run",
            "f":           trunc(state.get("fundamental"),    500, 200),
            "t":           trunc(state.get("technical"),      500, 200),
            "d":           trunc(state.get("dcf"),            300, 150),
            "s":           trunc(state.get("sentiment"),      300, 100),
            "o":           trunc(state.get("market_opinion"), 300, 150),
            "pr":          trunc(state.get("portfolio"),      250, 100),
            "mr":          trunc(state.get("macro_risk"),     250, 100),
            "al":          trunc(state.get("alerts"),         250, 100),
            "cp":          trunc(state.get("comparative"),    250, 100),
            "tr":          trunc(state.get("trend"),          200,  80),
            "h":           trunc(state.get("hot_stocks"),     200,  80),
            "budget":      (state.get("budget_report") or "N/A")[:200],
            "retry_note":  retry_note,
        }

    def __call__(self, state) -> dict:
        if not budget_ok(state, self.name):
            print(f"  [{self.name}] SKIPPED — budget")
            return {"stopped_early": True}
        return super().__call__(state)
