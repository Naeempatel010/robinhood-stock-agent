"""
DCF Valuation Agent

Input  (from snapshot):
  - dcf_results   : intrinsic_value, current_price, margin_of_safety_pct, verdict
  - portfolio_summary.holdings: shares, avg_buy_price, equity

Output (str):
  One line per stock:
    - Intrinsic value vs current price
    - Margin of safety %
    - Verdict (Undervalued / Fair Value / Overvalued)
    - Position sizing implication
  ETFs and stocks with missing FCF are noted but not skipped.
"""

from .base import BaseAgent, NodeContract, compact_json, slim_holdings


class DCFAgent(BaseAgent):
    name     = "dcf"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["dcf_results"],
        required_output_phrases = ["undervalued", "overvalued", "fair value", "margin"],
        min_output_length       = 80,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a value investor applying DCF analysis. Be concise. "
            "Reference the exact intrinsic values and margins of safety from the data."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "DCF results (10% discount rate, 3% terminal growth, 5-year horizon):\n{dcf}\n"
            "Holdings: {holdings}\n\n"
            "For each stock: intrinsic value vs current price, margin of safety %, "
            "verdict (Undervalued / Fair Value / Overvalued), key caveats (growth assumptions, "
            "FCF quality), and position sizing implication. "
            "One line per stock. Note ETFs or missing FCF data."
        )

    def build_prompt_inputs(self, state) -> dict:
        s = state["snapshot"]
        return {
            "dcf":      compact_json(s["dcf_results"]),
            "holdings": compact_json(slim_holdings(s["portfolio_summary"]["holdings"])),
        }
