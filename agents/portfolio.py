"""
Portfolio Structure Agent

Input  (from snapshot):
  - portfolio_metrics : concentration per position (equity, pct_of_portfolio, noise flag),
                        sector_exposure (pct breakdown), noise_positions list,
                        etf_overlaps dict
  - portfolio_summary.holdings

Output (str):
  One paragraph covering:
    - Concentration risks (positions >15%)
    - Sector over/under-exposure vs balanced benchmark
    - ETF overlap: individual stocks double-counted inside ETFs held
    - Noise positions (<1%) — recommend consolidation
"""

from .base import BaseAgent, NodeContract, compact_json, slim_holdings


class PortfolioAgent(BaseAgent):
    name     = "portfolio"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["portfolio_metrics", "portfolio_summary"],
        required_output_phrases = ["concentration", "sector", "position"],
        min_output_length       = 100,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a portfolio risk analyst. Focus on structure and diversification. "
            "Be specific about which tickers are problematic and why."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Portfolio structure metrics: {pm}\n"
            "Holdings detail: {holdings}\n\n"
            "Analyse: 1) concentration — flag positions >15% of total portfolio, "
            "2) sector exposure — identify over-concentration vs a balanced portfolio, "
            "3) ETF overlap — list individual stocks that duplicate ETF exposure, "
            "4) noise positions <1% — recommend consolidating into existing positions or ETFs. "
            "Be specific with ticker names and percentages."
        )

    def build_prompt_inputs(self, state) -> dict:
        s = state["snapshot"]
        return {
            "pm":       compact_json(s.get("portfolio_metrics", {})),
            "holdings": compact_json(slim_holdings(s["portfolio_summary"]["holdings"])),
        }
