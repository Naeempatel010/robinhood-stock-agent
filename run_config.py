"""
Analysis run configuration loader.

Reads a TOML config file (default: analysis.toml).
If the file is missing or a key is absent, safe defaults are used
so the tool always works out of the box.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_FILE = "analysis.toml"


@dataclass
class RunConfig:
    # Which analysis nodes to enable
    fundamental: bool = True
    technical:   bool = True
    dcf:         bool = True
    sentiment:   bool = True
    hot_stocks:  bool = True
    portfolio:   bool = True
    macro_risk:  bool = True
    alerts:      bool = True
    comparative: bool = True
    trend:       bool = True

    # Token budget
    total_usd:   float = 5.00
    reserve_usd: float = 0.50

    # Historical runs to include in trend analysis (default: last 5)
    trend_history_runs: int = 5

    # Quality evaluation — per-node output check + one retry if output is weak
    evaluate_nodes: bool = True

    # Report outputs
    report_txt:  bool = True
    report_xlsx: bool = True

    @property
    def enabled_analyses(self) -> list[str]:
        """Names of enabled analysis nodes, in canonical order."""
        return [
            name for name in
            ["fundamental", "technical", "dcf", "sentiment", "hot_stocks",
             "portfolio", "macro_risk", "alerts", "comparative", "trend"]
            if getattr(self, name)
        ]

    def summary(self) -> str:
        enabled = ", ".join(self.enabled_analyses) or "none"
        reports = ", ".join(
            r for r, on in [("txt", self.report_txt), ("xlsx", self.report_xlsx)] if on
        ) or "none"
        return (
            f"  Analyses : {enabled}\n"
            f"  Budget   : ${self.total_usd:.2f} (reserve ${self.reserve_usd:.2f})\n"
            f"  Reports  : {reports}"
        )


def load_run_config(path: str | None = None) -> RunConfig:
    """
    Load RunConfig from a TOML file.

    - If path is given and the file exists, load it.
    - If path is given but missing, exit with an error.
    - If path is None, try the default 'analysis.toml'; if absent, use defaults silently.
    """
    cfg = RunConfig()  # start with all defaults

    # Resolve which file to read
    if path is None:
        toml_path = Path(DEFAULT_CONFIG_FILE)
        if not toml_path.exists():
            return cfg  # no default file → pure defaults, no error
    else:
        toml_path = Path(path)
        if not toml_path.exists():
            raise FileNotFoundError(
                f"Config file not found: '{path}'\n"
                f"Run without --config to use all defaults, or copy analysis.toml and edit it."
            )

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    analyses = data.get("analyses", {})
    cfg.fundamental = analyses.get("fundamental", cfg.fundamental)
    cfg.technical   = analyses.get("technical",   cfg.technical)
    cfg.dcf         = analyses.get("dcf",          cfg.dcf)
    cfg.sentiment   = analyses.get("sentiment",    cfg.sentiment)
    cfg.hot_stocks  = analyses.get("hot_stocks",   cfg.hot_stocks)
    cfg.portfolio   = analyses.get("portfolio",    cfg.portfolio)
    cfg.macro_risk  = analyses.get("macro_risk",   cfg.macro_risk)
    cfg.alerts      = analyses.get("alerts",       cfg.alerts)
    cfg.comparative = analyses.get("comparative",  cfg.comparative)
    cfg.trend       = analyses.get("trend",        cfg.trend)

    budget = data.get("budget", {})
    cfg.total_usd   = budget.get("total_usd",   cfg.total_usd)
    cfg.reserve_usd = budget.get("reserve_usd", cfg.reserve_usd)

    cfg.trend_history_runs = analyses.get("trend_history_runs", cfg.trend_history_runs)
    cfg.evaluate_nodes     = analyses.get("evaluate_nodes",     cfg.evaluate_nodes)

    report = data.get("report", {})
    cfg.report_txt  = report.get("txt",  cfg.report_txt)
    cfg.report_xlsx = report.get("xlsx", cfg.report_xlsx)

    return cfg
