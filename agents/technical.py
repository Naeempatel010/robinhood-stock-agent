"""
Technical Analysis Agent

Input  (from snapshot):
  - technical_data: RSI-14, MACD/signal/histogram, Bollinger Bands (upper/mid/lower),
                    SMA-50, SMA-200, EMA-20, volume, avg_volume_20d, volume_spike_ratio,
                    support, resistance, trend_direction, volatility_20d_annualized_pct,
                    price changes 1w/1m/3m/6m/1y, alerts list
  - correlation_data: correlation matrix, avg_correlation, diversification_score

Output (str):
  Per stock (1-2 lines each):
    - Trend direction label
    - RSI (overbought >70 / oversold <30)
    - MACD signal (bullish/bearish crossover)
    - Bollinger Band position
    - SMA-50/200 crossover status
    - Volume spike if any
    - Support/resistance levels
    - 20-day annualised volatility
  Then:
    - Top correlated pairs
    - Diversification score X/10
    - One rebalancing suggestion
"""

from .base import BaseAgent, NodeContract, compact_json


class TechnicalAgent(BaseAgent):
    name     = "technical"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["technical_data"],
        required_output_phrases = ["rsi", "macd", "sma", "support"],
        min_output_length       = 120,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are an expert technical analyst. Be concise and specific — "
            "reference exact numbers from the data provided."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Technical indicators: {technical}\n"
            "Correlation matrix: {correlation}\n\n"
            "For each stock (1-2 lines): trend direction, RSI (flag if >70 or <30), "
            "MACD signal, Bollinger Band position (at upper/lower/mid), "
            "SMA-50/200 crossover status, volume spike if ratio >2x, "
            "support/resistance levels, 20-day annualised volatility, and active alerts.\n\n"
            "Then summarise: top 3 most-correlated pairs, "
            "diversification score {div}/10, and one specific rebalancing suggestion."
        )

    def build_prompt_inputs(self, state) -> dict:
        s  = state["snapshot"]
        cd = s.get("correlation_data", {})
        return {
            "technical":   compact_json(s["technical_data"]),
            "correlation": compact_json(cd),
            "div":         cd.get("diversification_score", "N/A"),
        }
