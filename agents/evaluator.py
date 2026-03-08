"""
Evaluator Agent (no LLM call — structural quality gate)

Checks final_summary for all 5 required sections.
Triggers one retry of final_summary if sections are missing and budget permits.

Input:
  state["final_summary"] : text to validate
  state["retry_count"]   : 0=first check, 1=retry was requested and ran, 2=done
  state["run_config"]    : budget limits

Output:
  retry_count: 1 if retry needed, 2 if done
"""

from .base import budget_ok, NODE_MIN_COST

_REQUIRED_SECTIONS = [
    "RISK RATING",
    "PORTFOLIO RATING",
    "REBALANCING",
    "SELL NOW",
    "BUY NOW",
]


def evaluator_node(state) -> dict:
    """
    LangGraph-compatible node function (not a BaseAgent subclass — no LLM needed).

    Input:
      state["final_summary"] (str)    : the summary to evaluate
      state["retry_count"] (int)      : 0=first eval, 1=after retry, 2=done
      state["run_config"] (RunConfig) : budget / evaluate_nodes flag

    Output:
      {"retry_count": 1}  → re-run final_summary
      {"retry_count": 2}  → done, proceed to END
    """
    cfg     = state["run_config"]
    summary = (state.get("final_summary") or "").upper()
    missing = [s for s in _REQUIRED_SECTIONS if s not in summary]

    # Skip structural evaluation if disabled in config
    if not cfg.evaluate_nodes:
        print("  [evaluator] Evaluation disabled by config — accepting output as-is")
        return {"retry_count": 2}

    if state["retry_count"] == 0 and missing:
        if budget_ok(state, "final_summary"):
            print(f"  [evaluator] Missing sections: {missing} — requesting retry")
            return {"retry_count": 1}
        else:
            print(f"  [evaluator] Missing: {missing} — no budget for retry, accepting as-is")
            return {"retry_count": 2}

    if missing:
        print(f"  [evaluator] Missing sections after retry: {missing} — accepting as-is")
    else:
        print(f"  [evaluator] All 5 sections present ✓")
    return {"retry_count": 2}


def route_evaluator(state) -> str:
    return "retry" if state["retry_count"] == 1 else "done"
