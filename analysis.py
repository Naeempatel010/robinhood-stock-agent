"""
LangGraph graph definition for the portfolio analysis pipeline.

This file is the single source of truth for graph topology.
Individual agent logic lives in agents/*.py.

Graph topology:

  START
  ├── fundamental  ┐
  ├── technical    │  (parallel — only enabled agents added)
  ├── dcf          │
  ├── sentiment    │
  ├── hot_stocks   ├──► cost_agent ──► market_opinion ──► final_summary ──► evaluator ──► END
  ├── portfolio    │                                            ▲                │
  ├── macro_risk   │                                            └── retry ───────┘
  ├── alerts       │
  ├── comparative  │
  └── trend        ┘

To add a new agent:
  1. Create agents/my_agent.py subclassing BaseAgent
  2. Add to ALL_PARALLEL_AGENTS in agents/__init__.py
  3. Add toggle to RunConfig (run_config.py) and analysis.toml
"""

from langgraph.graph import END, START, StateGraph

from agents import (
    ALL_PARALLEL_AGENTS,
    MARKET_OPINION_AGENT,
    FINAL_SUMMARY_AGENT,
    AnalysisState,
    cost_agent_node,
    evaluator_node,
    route_evaluator,
    init_llms,
    NODE_MIN_COST,
)
from config import load_credentials
from run_config import RunConfig

_INPUT_CPT  = 3.00  / 1_000_000
_OUTPUT_CPT = 15.00 / 1_000_000


def _cost(in_tok: int, out_tok: int) -> float:
    return in_tok * _INPUT_CPT + out_tok * _OUTPUT_CPT


def _build_graph(enabled: list[str]):
    """Build LangGraph graph — only enabled parallel agents are included."""
    b = StateGraph(AnalysisState)

    # Sequential nodes (always present)
    b.add_node("cost_agent",     cost_agent_node)
    b.add_node("market_opinion", MARKET_OPINION_AGENT)
    b.add_node("final_summary",  FINAL_SUMMARY_AGENT)
    b.add_node("evaluator",      evaluator_node)

    # Parallel nodes — add only enabled ones
    parallel = [n for n in enabled if n in ALL_PARALLEL_AGENTS]
    for name in parallel:
        b.add_node(name, ALL_PARALLEL_AGENTS[name])
        b.add_edge(START, name)
        b.add_edge(name, "cost_agent")

    if not parallel:
        b.add_edge(START, "cost_agent")

    b.add_edge("cost_agent",     "market_opinion")
    b.add_edge("market_opinion", "final_summary")
    b.add_edge("final_summary",  "evaluator")
    b.add_conditional_edges(
        "evaluator",
        route_evaluator,
        {"retry": "final_summary", "done": END},
    )

    return b.compile()


def run_all(
    snapshot: dict,
    historical_comparison: dict,
    full_history: list = None,
    run_config: RunConfig = None,
    api_key: str = None,
) -> dict:
    """
    Run the full analysis pipeline.

    Args:
        snapshot:              Full portfolio snapshot from data collection.
        historical_comparison: Equity delta vs previous run.
        full_history:          All past DB runs (for trend agent).
        run_config:            Active RunConfig (defaults to all-enabled).
        api_key:               Anthropic API key.

    Returns:
        Dict of analysis strings keyed by agent name, plus input_tokens/output_tokens.
    """
    if run_config is None:
        run_config = RunConfig()

    if api_key:
        init_llms(api_key)
    elif True:
        _, _, default_key = load_credentials()
        init_llms(default_key)

    graph = _build_graph(run_config.enabled_analyses)

    initial: AnalysisState = {
        "snapshot":              snapshot,
        "historical_comparison": historical_comparison,
        "full_history":          full_history or [],
        "run_config":            run_config,
        # Parallel results
        "fundamental":  "",
        "technical":    "",
        "dcf":          "",
        "sentiment":    "",
        "hot_stocks":   "",
        "portfolio":    "",
        "macro_risk":   "",
        "alerts":       "",
        "comparative":  "",
        "trend":        "",
        # Sequential results
        "budget_report":  "",
        "market_opinion": "",
        "final_summary":  "",
        # Tracking
        "input_tokens":   0,
        "output_tokens":  0,
        "retry_count":    0,
        "stopped_early":  False,
    }

    final = graph.invoke(initial)

    total_cost = _cost(final["input_tokens"], final["output_tokens"])
    print(f"\n  ── Budget summary ───────────────────────────")
    print(f"  Spent    : ${total_cost:.4f} of ${run_config.total_usd:.2f}")
    print(f"  Remaining: ${run_config.total_usd - total_cost:.4f}")
    print(f"  Tokens   : {final['input_tokens']:,} in / {final['output_tokens']:,} out")
    if final.get("stopped_early"):
        print("  ⚠ One or more steps were SKIPPED — partial results")

    return {
        "fundamental":    final["fundamental"],
        "technical":      final["technical"],
        "dcf":            final["dcf"],
        "sentiment":      final["sentiment"],
        "hot_stocks":     final["hot_stocks"],
        "portfolio":      final["portfolio"],
        "macro_risk":     final["macro_risk"],
        "alerts":         final["alerts"],
        "comparative":    final["comparative"],
        "trend":          final["trend"],
        "budget_report":  final["budget_report"],
        "market_opinion": final["market_opinion"],
        "final_summary":  final["final_summary"],
        "input_tokens":   final["input_tokens"],
        "output_tokens":  final["output_tokens"],
    }
