"""
Fundamental Analysis Agent

Input  (from snapshot):
  - portfolio_summary.holdings
  - fundamental_data   : P/E, P/B, P/S, PEG, revenue/earnings growth YoY+QoQ,
                         profit margin, ROE, D/E, FCF, current ratio, EPS
  - short_interest_data: short %, short ratio, MoM change
  - insider_data       : open-market transactions only
  - institutional_data : top 10 institutional holders

Output (str):
  One paragraph per stock with:
    - Valuation (P/E vs sector, P/B, P/S)
    - Financial health (margins, ROE, D/E, FCF)
    - Short interest signal
    - Insider activity signal
    - Institutional ownership trend
    - Analyst consensus + price target vs current
    - Verdict: Strong / Neutral / Weak
"""

from .base import BaseAgent, NodeContract, compact_json, slim_holdings, slim_insider


class FundamentalAgent(BaseAgent):
    name     = "fundamental"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["fundamental_data", "portfolio_summary"],
        required_output_phrases = ["strong", "neutral", "weak", "verdict"],
        min_output_length       = 150,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a professional equity analyst. Be concise and data-driven. "
            "Use the provided metrics directly — do not make up values."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Holdings: {holdings}\n"
            "Fundamentals: {fundamental}\n"
            "Short interest: {short_interest}\n"
            "Insider transactions (open-market only): {insider}\n"
            "Institutional holders: {institutional}\n\n"
            "For each stock, cover: P/E, P/B, P/S, revenue and earnings growth (YoY + QoQ), "
            "profit margin, ROE, D/E ratio, free cash flow, short interest signal, "
            "insider activity, institutional ownership trend, analyst rating and price target "
            "vs current price. End each stock with: Verdict: Strong / Neutral / Weak."
        )

    def build_prompt_inputs(self, state) -> dict:
        s = state["snapshot"]
        return {
            "holdings":       compact_json(slim_holdings(s["portfolio_summary"]["holdings"])),
            "fundamental":    compact_json(s["fundamental_data"]),
            "short_interest": compact_json(s["short_interest_data"]),
            "insider":        compact_json(slim_insider(s["insider_data"])),
            "institutional":  compact_json(s.get("institutional_data", {}), limit=1500),
        }
