"""
Agent registry — import all agents and expose ALL_AGENTS for graph construction.

To add a new agent:
  1. Create agents/my_agent.py subclassing BaseAgent
  2. Add an instance to ALL_AGENTS below with a unique key
  3. Add the key to RunConfig.enabled_analyses (run_config.py)
  4. Add it to analysis.toml [analyses] section
"""

from .fundamental   import FundamentalAgent
from .technical     import TechnicalAgent
from .dcf           import DCFAgent
from .sentiment     import SentimentAgent
from .hot_stocks    import HotStocksAgent
from .portfolio     import PortfolioAgent
from .macro_risk    import MacroRiskAgent
from .alerts        import AlertsAgent
from .comparative   import ComparativeAgent
from .trend         import TrendAgent
from .market_opinion import MarketOpinionAgent
from .final_summary  import FinalSummaryAgent
from .cost_agent     import cost_agent_node
from .evaluator      import evaluator_node, route_evaluator
from .base           import init_llms, BaseAgent, NodeContract, NODE_MIN_COST, NODE_PRIORITY
from .state          import AnalysisState

# ── Parallel agents (fan-out from START) ─────────────────────────────────────
# Add new parallel agents here. Key = LangGraph node name = RunConfig field name.
ALL_PARALLEL_AGENTS: dict[str, BaseAgent] = {
    "fundamental": FundamentalAgent(),
    "technical":   TechnicalAgent(),
    "dcf":         DCFAgent(),
    "sentiment":   SentimentAgent(),
    "hot_stocks":  HotStocksAgent(),
    "portfolio":   PortfolioAgent(),
    "macro_risk":  MacroRiskAgent(),
    "alerts":      AlertsAgent(),
    "comparative": ComparativeAgent(),
    "trend":       TrendAgent(),
}

# ── Sequential agents (fixed order after cost_agent) ─────────────────────────
MARKET_OPINION_AGENT = MarketOpinionAgent()
FINAL_SUMMARY_AGENT  = FinalSummaryAgent()

__all__ = [
    "ALL_PARALLEL_AGENTS",
    "MARKET_OPINION_AGENT",
    "FINAL_SUMMARY_AGENT",
    "cost_agent_node",
    "evaluator_node",
    "route_evaluator",
    "init_llms",
    "BaseAgent",
    "NodeContract",
    "NODE_MIN_COST",
    "NODE_PRIORITY",
    "AnalysisState",
]
