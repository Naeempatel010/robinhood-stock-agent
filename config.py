import importlib.util
import os
import sys

HISTORY_FILE   = "portfolio_history.json"
SNAPSHOTS_FILE = "portfolio_snapshots.json.gz"

STATIC_HOLDINGS = {
    "AMZN": {"plan": "Amazon Long Share Savings Plan", "shares": 74.41, "avg_buy_price": 0},
}

HOT_TICKERS = ["NVDA", "META", "TSLA", "AMZN", "MSFT", "AAPL", "GOOGL", "AMD", "PLTR", "ARM", "AVGO", "SMCI"]

DCF_DISCOUNT_RATE  = 0.10
DCF_TERMINAL_GROWTH = 0.03
DCF_YEARS          = 5


def load_credentials(path="credentials.py"):
    """
    Load RH_USERNAME, RH_PASSWORD, ANTHROPIC_API_KEY from a Python file.
    Exits with a helpful message if the file is missing or incomplete.
    """
    if not os.path.exists(path):
        sys.exit(
            f"\nError: credentials file not found: '{path}'\n"
            f"Copy credentials.py.example -> credentials.py and fill in your values.\n"
            f"Or pass a custom path:  --credentials /path/to/my_creds.py\n"
        )
    spec = importlib.util.spec_from_file_location("_credentials", os.path.abspath(path))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    missing = [k for k in ("RH_USERNAME", "RH_PASSWORD", "ANTHROPIC_API_KEY") if not hasattr(mod, k)]
    if missing:
        sys.exit(f"\nError: credentials file '{path}' is missing: {', '.join(missing)}\n")

    return mod.RH_USERNAME, mod.RH_PASSWORD, mod.ANTHROPIC_API_KEY
