"""
Pre-run validation for the portfolio analyzer.

Checks performed before any analysis runs:
  1. API key validity  — lightweight Anthropic call to confirm key works
  2. User budget       — run_config.total_usd must not exceed user's remaining allowance
  3. Budget floor      — configured budget must be enough to run at least one enabled node
  4. Snapshot exists   — if --analysis without --data, a snapshot must exist in the DB

All checks raise ValidationError on failure so analyze.py can catch and exit cleanly.
"""

import anthropic

from run_config import RunConfig
from db import PortfolioDB

# Rough minimum cost per enabled analysis node (input ~800 tok, output ~400 tok at sonnet-4-6 pricing)
_NODE_MIN_COST = {
    "fundamental":  0.012,
    "technical":    0.010,
    "dcf":          0.008,
    "sentiment":    0.008,
    "hot_stocks":   0.010,
    "trend":        0.007,
    "portfolio":    0.008,
    "macro_risk":   0.008,
    "alerts":       0.006,
    "comparative":  0.008,
}
# Sequential nodes always run
_SEQUENTIAL_MIN_COST = 0.015   # market_opinion + final_summary + evaluator


class ValidationError(Exception):
    pass


def validate_all(api_key: str, run_cfg: RunConfig, db: PortfolioDB, need_snapshot: bool) -> None:
    """
    Run all pre-flight checks. Raises ValidationError with a clear message on failure.

    Args:
        api_key:       Anthropic API key.
        run_cfg:       The active RunConfig for this run.
        db:            Opened PortfolioDB (user already resolved).
        need_snapshot: True when --analysis is requested (snapshot must exist).
    """
    _check_api_key(api_key)
    _check_user_budget(run_cfg, db)
    _check_budget_floor(run_cfg)
    if need_snapshot:
        _check_snapshot_exists(db)


# ------------------------------------------------------------------ #
# Individual checks                                                   #
# ------------------------------------------------------------------ #

def _check_api_key(api_key: str) -> None:
    """Verify the Anthropic API key is valid with a minimal models.list() call."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        # models.list() is the cheapest non-billed call to confirm key validity
        client.models.list(limit=1)
    except anthropic.AuthenticationError:
        raise ValidationError(
            "Anthropic API key is invalid or expired.\n"
            "Check credentials.py and ensure ANTHROPIC_API_KEY is correct."
        )
    except Exception as e:
        raise ValidationError(f"Could not reach Anthropic API: {e}")


def _check_user_budget(run_cfg: RunConfig, db: PortfolioDB) -> None:
    """
    Ensure the user has enough remaining allowance to cover run_cfg.total_usd.
    This prevents a single run from exceeding the user's lifetime spending limit.
    """
    spending = db.user_spending()
    remaining = spending["remaining_usd"]
    limit     = spending["spending_limit_usd"]
    spent     = spending["total_spent_usd"]

    if remaining <= 0:
        raise ValidationError(
            f"User '{db._username}' has exhausted their spending limit.\n"
            f"  Limit   : ${limit:.2f}\n"
            f"  Spent   : ${spent:.4f}\n"
            f"  Remaining: ${remaining:.4f}\n"
            f"Increase the limit with: db.set_spending_limit(<new_limit>)"
        )

    if run_cfg.total_usd > remaining:
        raise ValidationError(
            f"Run config budget (${run_cfg.total_usd:.2f}) exceeds user's remaining allowance "
            f"(${remaining:.4f}).\n"
            f"  Limit    : ${limit:.2f}\n"
            f"  Spent    : ${spent:.4f}\n"
            f"  Remaining: ${remaining:.4f}\n"
            f"Lower [budget] total_usd in your config file, or increase the user spending limit."
        )


def _check_budget_floor(run_cfg: RunConfig) -> None:
    """
    Ensure the configured budget is large enough to run at least the sequential
    nodes plus the cheapest enabled parallel node.
    """
    enabled_min = sum(
        _NODE_MIN_COST.get(n, 0.008) for n in run_cfg.enabled_analyses
    )
    required = _SEQUENTIAL_MIN_COST + enabled_min
    effective_budget = run_cfg.total_usd - run_cfg.reserve_usd

    if effective_budget < required:
        raise ValidationError(
            f"Configured budget is too low for the selected analyses.\n"
            f"  Enabled nodes  : {', '.join(run_cfg.enabled_analyses) or 'none'}\n"
            f"  Estimated min  : ${required:.3f}\n"
            f"  Effective budget: ${effective_budget:.3f} "
            f"(total ${run_cfg.total_usd:.2f} - reserve ${run_cfg.reserve_usd:.2f})\n"
            f"Increase [budget] total_usd or disable some analyses in your config."
        )


def _check_snapshot_exists(db: PortfolioDB) -> None:
    """Verify at least one snapshot exists before attempting analysis."""
    if db.snapshot_count() == 0:
        raise ValidationError(
            "No snapshots found in the database.\n"
            "Run with --data first to collect portfolio data."
        )
