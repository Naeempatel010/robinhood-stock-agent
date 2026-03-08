"""
Comparative Performance Agent

Input  (from snapshot):
  - technical_data per holding: change_1w/1m/3m/6m/1y_pct, vs_benchmark dict,
                                trend_direction

Output (str):
  One line per stock:
    - Return vs S&P 500 and Nasdaq 100 over 1M/3M/1Y
    - Classification: outperformer / underperformer / benchmark-hugger
  Summary: consistent outperformers to hold/add, underperformers to review/trim.
"""

from .base import BaseAgent, NodeContract, compact_json


class ComparativeAgent(BaseAgent):
    name     = "comparative"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["technical_data"],
        required_output_phrases = ["outperform", "underperform", "benchmark"],
        min_output_length       = 80,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a performance attribution analyst. Be concise and data-driven. "
            "Use the exact return numbers provided."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Stock returns and benchmark-relative performance: {comp}\n\n"
            "For each stock: absolute returns (1M/3M/1Y) and performance vs S&P 500 "
            "and Nasdaq 100 (show +/- vs benchmark). Classify as: outperformer, "
            "underperformer, or benchmark-hugger. One line per ticker.\n\n"
            "Conclude with: top outperformers to hold/add and "
            "consistent underperformers to review or trim."
        )

    def build_prompt_inputs(self, state) -> dict:
        s  = state["snapshot"]
        td = s.get("technical_data", {})
        comp_data = {
            ticker: {
                "1w":       t.get("change_1w_pct"),
                "1m":       t.get("change_1m_pct"),
                "3m":       t.get("change_3m_pct"),
                "6m":       t.get("change_6m_pct"),
                "1y":       t.get("change_1y_pct"),
                "vs_SP500":  (t.get("vs_benchmark") or {}).get("S&P 500"),
                "vs_Nasdaq": (t.get("vs_benchmark") or {}).get("Nasdaq 100"),
                "trend":    t.get("trend_direction"),
            }
            for ticker, t in td.items()
            if ticker in s["portfolio_summary"]["holdings"]
        }
        return {"comp": compact_json(comp_data, limit=3000)}
