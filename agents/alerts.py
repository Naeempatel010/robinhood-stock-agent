"""
Alerts Agent

Input  (from snapshot — rule-based, pre-computed):
  - technical_data    : alerts list per ticker (RSI, BB, volume spike, MACD crossover)
  - short_interest_data: short_interest_mom_change (MoM direction + pct_change)
  - insider_data      : open-market sale transactions

Output (str):
  Per active alert (sorted by severity):
    - 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW
    - What the alert signals
    - Suggested action
  "No active alerts." if nothing triggered.
"""

from .base import BaseAgent, NodeContract, compact_json


class AlertsAgent(BaseAgent):
    name     = "alerts"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["technical_data"],
        required_output_phrases = [],   # may legitimately output "no active alerts"
        min_output_length       = 20,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a trading alert system. Be direct and actionable. "
            "Classify each alert by severity and give a specific suggested action."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Active rule-based alerts by ticker: {alerts}\n\n"
            "For each alert: assign severity (🔴 HIGH / 🟡 MEDIUM / 🟢 LOW), "
            "explain what it signals, and give a specific suggested action. "
            "Sort by severity descending. "
            "If no alerts, output: 'No active alerts triggered.'"
        )

    def build_prompt_inputs(self, state) -> dict:
        s   = state["snapshot"]
        td  = s.get("technical_data", {})
        si  = s.get("short_interest_data", {})
        ins = s.get("insider_data", {})

        all_alerts: dict[str, list] = {}
        for ticker, t in td.items():
            if ticker not in s["portfolio_summary"]["holdings"]:
                continue
            ta_list = list(t.get("alerts", []))
            # Short interest MoM spike >20%
            mom = (si.get(ticker) or {}).get("short_interest_mom_change") or {}
            if isinstance(mom, dict) and abs(mom.get("pct_change", 0)) > 20:
                ta_list.append(
                    f"Short interest {mom.get('direction', '')} {abs(mom['pct_change'])}% MoM"
                )
            # Open-market insider sale
            for rec in (ins.get(ticker) or [])[:3]:
                txt = str(rec.get("Transaction", rec.get("Text", ""))).lower()
                if "sale" in txt or "sold" in txt:
                    ta_list.append("Open-market insider sale detected")
                    break
            if ta_list:
                all_alerts[ticker] = ta_list

        return {"alerts": compact_json(all_alerts, limit=2000) if all_alerts else "{}"}

    def __call__(self, state) -> dict:
        """Override to return early when no alerts exist without calling LLM."""
        from .base import budget_ok
        if not budget_ok(state, self.name):
            print(f"  [{self.name}] SKIPPED — budget")
            return {"stopped_early": True}

        # Build inputs first to check if there are any alerts
        prompt_inputs = self.build_prompt_inputs(state)
        if prompt_inputs["alerts"] == "{}":
            print(f"  [{self.name}] No alerts triggered — skipping LLM call")
            return {"alerts": "No active alerts triggered.", "input_tokens": 0, "output_tokens": 0}

        return super().__call__(state)
