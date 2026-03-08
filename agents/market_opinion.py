"""
Market Opinion Agent (sequential)

Input  (from state — synthesises parallel agent outputs):
  - fundamental  : stock-by-stock fundamental verdict
  - technical    : stock-by-stock technical signals and alerts
  - sentiment    : news + analyst sentiment
  - alerts       : active trigger alerts
  - macro_risk   : beta, volatility, earnings dates, geo risk

Output (str):
  1-3 month portfolio outlook — 3 bullet points:
    • Macro environment
    • Key risk
    • Overall direction
"""

from .base import BaseAgent, NodeContract, budget_ok


class MarketOpinionAgent(BaseAgent):
    name     = "market_opinion"
    llm_tier = "summary"
    contract = NodeContract(
        required_snapshot_keys  = [],
        required_output_phrases = ["risk", "outlook", "macro", "direction"],
        min_output_length       = 80,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a senior portfolio manager synthesising multiple analyses. "
            "Be direct and forward-looking. Three bullet points maximum."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Fundamental analysis: {f}\n"
            "Technical analysis: {t}\n"
            "Sentiment: {s}\n"
            "Active alerts: {al}\n"
            "Macro risk: {mr}\n\n"
            "Provide a 1-3 month portfolio outlook in exactly 3 bullet points:\n"
            "• Macro environment\n"
            "• Key risk\n"
            "• Overall portfolio direction"
        )

    def build_prompt_inputs(self, state) -> dict:
        return {
            "f":  (state.get("fundamental") or "N/A")[:600],
            "t":  (state.get("technical")   or "N/A")[:600],
            "s":  (state.get("sentiment")   or "N/A")[:400],
            "al": (state.get("alerts")      or "N/A")[:300],
            "mr": (state.get("macro_risk")  or "N/A")[:300],
        }

    def __call__(self, state) -> dict:
        if not budget_ok(state, self.name):
            print(f"  [{self.name}] SKIPPED — budget")
            return {"stopped_early": True}
        if not any(state.get(f) for f in ["fundamental", "technical", "sentiment"]):
            return {"market_opinion": "Insufficient upstream data.", "input_tokens": 0, "output_tokens": 0}
        return super().__call__(state)
