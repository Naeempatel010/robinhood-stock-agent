"""
Cost Agent (no LLM call)

Runs after all parallel agents complete, before sequential agents.

Input  (from state):
  - All parallel agent result fields
  - run_config: total_usd, reserve_usd
  - input_tokens, output_tokens accumulated so far

Output:
  - budget_report (str): summary of what ran/skipped and remaining budget
  - stopped_early (bool): True if sequential nodes cannot run

Responsibilities:
  1. Tally what ran vs was skipped in the parallel phase.
  2. Estimate cost needed for sequential nodes.
  3. Warn and set stopped_early if budget is insufficient.
  4. In budget-crunch mode, log which low-priority outputs will be trimmed
     in the final_summary prompt (trimming is done there, not here).
"""

from .base import spent as _spent, remaining as _remaining, token_cost, NODE_MIN_COST, NODE_PRIORITY

_PARALLEL_FIELDS = [
    "fundamental", "technical", "dcf", "sentiment", "hot_stocks",
    "portfolio", "macro_risk", "alerts", "comparative", "trend",
]
_SEQUENTIAL_MIN = NODE_MIN_COST["market_opinion"] + NODE_MIN_COST["final_summary"]


def cost_agent_node(state) -> dict:
    """
    LangGraph-compatible node function (not a BaseAgent subclass — no LLM needed).

    Input:
      state["run_config"]    : budget limits
      state["input_tokens"]  : total tokens consumed so far
      state["output_tokens"] : total tokens consumed so far
      state[field]           : each parallel agent's output string

    Output fields:
      budget_report (str)
      stopped_early (bool, optional)
    """
    cfg       = state["run_config"]
    current_remaining = _remaining(state)
    current_spent     = _spent(state)

    # What ran vs skipped
    ran     = [f for f in _PARALLEL_FIELDS if state.get(f) and state[f] not in ("", None)]
    skipped = [
        f for f in _PARALLEL_FIELDS
        if f in cfg.enabled_analyses and not (state.get(f) and state[f] not in ("", None))
    ]

    # Budget needed for sequential nodes (market_opinion + final_summary + reserve)
    seq_needed = _SEQUENTIAL_MIN + cfg.reserve_usd

    lines = [
        f"Parallel phase: {len(ran)}/{len(cfg.enabled_analyses)} agents ran",
        f"Spent: ${current_spent:.4f} | Remaining: ${current_remaining:.4f}",
        f"Sequential nodes need: ~${_SEQUENTIAL_MIN:.4f} + reserve ${cfg.reserve_usd:.2f}",
    ]

    if skipped:
        # Sort by priority so most important skipped show first
        skipped_sorted = sorted(skipped, key=lambda n: NODE_PRIORITY.get(n, 99))
        lines.append(f"Skipped (budget/disabled): {', '.join(skipped_sorted)}")

    if current_remaining < seq_needed:
        lines.append(
            f"⚠ CRITICAL: only ${current_remaining:.4f} left — "
            f"sequential nodes need ${seq_needed:.4f}. Partial report only."
        )
        print(f"  [cost_agent] CRITICAL — ${current_remaining:.4f} remaining, "
              f"sequential nodes may be skipped")
        return {"budget_report": "\n".join(lines), "stopped_early": True}

    # Budget-crunch warning (tight but viable)
    trim_threshold = seq_needed * 2
    if current_remaining < trim_threshold:
        lines.append(
            f"Budget tight (${current_remaining:.4f}) — "
            f"low-priority inputs will be trimmed in final summary"
        )

    print(f"  [cost_agent] ${current_spent:.4f} spent | "
          f"${current_remaining:.4f} remaining | "
          f"{len(ran)}/{len(cfg.enabled_analyses)} agents ran")

    return {"budget_report": "\n".join(lines)}
