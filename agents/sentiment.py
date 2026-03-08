"""
Sentiment Analysis Agent

Input  (from snapshot):
  - news_data        : up to 6 headlines per stock (title, publisher, date)
  - market_news      : up to 8 SPY market headlines
  - fundamental_data : analyst_rating, target_price, target_high, target_low,
                       analyst_count, current_price, eps_next_year_est

Output (str):
  Per stock:
    - News sentiment: Bullish / Neutral / Bearish + one-sentence reason
    - Analyst consensus: rating, mean target vs current price (upside/downside %)
    - Earnings estimate direction (rising / falling / stable)
  Overall market sentiment: one sentence.
"""

from .base import BaseAgent, NodeContract, compact_json, slim_news


class SentimentAgent(BaseAgent):
    name     = "sentiment"
    llm_tier = "analysis"
    contract = NodeContract(
        required_snapshot_keys  = ["news_data"],
        required_output_phrases = ["bullish", "bearish", "neutral"],
        min_output_length       = 100,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a market sentiment analyst. Be direct. "
            "Rate each stock Bullish, Neutral, or Bearish based on the news and analyst data."
        )

    @property
    def human_prompt(self) -> str:
        return (
            "Stock news headlines: {stock_news}\n"
            "Market news headlines: {market_news}\n"
            "Analyst ratings and targets: {ratings}\n\n"
            "For each stock: news sentiment (Bullish/Neutral/Bearish) with one-sentence reason, "
            "analyst rating and mean price target vs current price (show upside/downside %), "
            "earnings estimate direction. "
            "End with one sentence on overall market sentiment from the market headlines."
        )

    def build_prompt_inputs(self, state) -> dict:
        s  = state["snapshot"]
        fd = s.get("fundamental_data", {})
        return {
            "stock_news":  compact_json(slim_news(s["news_data"])),
            "market_news": compact_json([n.get("title", "") for n in s.get("market_news", [])[:5]]),
            "ratings": compact_json({
                t: {
                    "rating":    f.get("analyst_rating"),
                    "target":    f.get("target_price"),
                    "target_hi": f.get("target_high"),
                    "target_lo": f.get("target_low"),
                    "price":     f.get("current_price"),
                    "count":     f.get("analyst_count"),
                    "eps_fwd":   f.get("eps_next_year_est"),
                }
                for t, f in fd.items()
                if f.get("type") != "ETF"
            }, limit=1500),
        }
