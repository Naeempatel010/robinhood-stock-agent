"""
Historical Trend Agent

Input  (from state.full_history — last N runs, N from run_config.trend_history_runs):
  - date, equity, cash per run
  - holdings per run: ticker → {equity, price}

Output (str):
  4 bullet points:
    1. Overall equity trend (growing/flat/declining) with % change over period
    2. Top performers and laggards over time
    3. Concentration shifts — positions growing or shrinking significantly
    4. Forward outlook based on trajectory

  Returns early with a message if fewer than 2 runs exist.
"""

from .base import BaseAgent, NodeContract, compact_json


class TrendAgent(BaseAgent):
    name     = "trend"
    llm_tier = "summary"
    contract = NodeContract(
        required_snapshot_keys  = [],   # uses full_history from state, not snapshot
        required_output_phrases = ["equity", "trend"],
        min_output_length       = 80,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a portfolio performance analyst. Be concise. "
            "Focus on meaningful trends, not noise."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Portfolio equity and holdings history ({n} runs):\n{timeline}\n\n"
            "Provide exactly 4 bullet points:\n"
            "1. Overall equity trend: growing/flat/declining, % change over the period\n"
            "2. Top performers and laggards — tickers that grew or shrank most\n"
            "3. Concentration shifts — positions with notable % changes\n"
            "4. Forward outlook based on the trajectory"
        )

    def build_prompt_inputs(self, state) -> dict:
        cfg     = state["run_config"]
        limit   = getattr(cfg, "trend_history_runs", 5)
        history = state.get("full_history") or []
        recent  = history[-limit:]
        timeline = [
            {
                "date":     r["date"][:10],
                "equity":   r.get("equity"),
                "cash":     r.get("cash"),
                "holdings": {
                    t: {"equity": v.get("equity"), "price": v.get("price")}
                    for t, v in (r.get("holdings") or {}).items()
                },
            }
            for r in recent
        ]
        return {"n": len(timeline), "timeline": compact_json(timeline, limit=3000)}

    def __call__(self, state) -> dict:
        """Override to skip without LLM call when history is insufficient."""
        from .base import budget_ok
        if not budget_ok(state, self.name):
            print(f"  [{self.name}] SKIPPED — budget")
            return {"stopped_early": True}

        cfg   = state["run_config"]
        limit = getattr(cfg, "trend_history_runs", 5)
        if len(state.get("full_history") or []) < 2:
            print(f"  [{self.name}] Insufficient history — skipping LLM call")
            return {
                "trend":         f"Insufficient history (need ≥2 runs, last {limit} used).",
                "input_tokens":  0,
                "output_tokens": 0,
            }
        return super().__call__(state)
