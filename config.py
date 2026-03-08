import importlib.util
import os
import sys

HISTORY_FILE   = "portfolio_history.json"
SNAPSHOTS_FILE = "portfolio_snapshots.json.gz"

STATIC_HOLDINGS = {}

HOT_TICKERS = ["NVDA", "META", "TSLA", "AMZN", "MSFT", "AAPL", "GOOGL", "AMD", "PLTR", "ARM", "AVGO", "SMCI"]

DCF_DISCOUNT_RATE   = 0.10
DCF_TERMINAL_GROWTH = 0.03
DCF_YEARS           = 5


def load_credentials(path: str = "credentials.py", db=None) -> tuple[str, str, str]:
    """
    Load RH_USERNAME, RH_PASSWORD, ANTHROPIC_API_KEY.

    Priority:
      1. DB (if db is provided and credentials are stored)
      2. Credentials file at `path`

    When credentials are loaded from a file they are saved to DB so future
    runs don't need the file.  For a brand-new user, create credentials.py
    from credentials.py.example and run once — the file is only needed that
    first time.

    Returns:
        (rh_username, rh_password, anthropic_api_key)
    """
    # ── 1. Try DB first ──────────────────────────────────────────────
    if db is not None:
        creds = db.get_credentials()
        if creds.get("rh_username") and creds.get("anthropic_api_key"):
            return creds["rh_username"], creds["rh_password"], creds["anthropic_api_key"]

    # ── 2. Fall back to credentials file ─────────────────────────────
    if not os.path.exists(path):
        if db is not None:
            sys.exit(
                f"\nError: No credentials found in DB for this user and credentials "
                f"file '{path}' not found.\n"
                f"Copy credentials.py.example → credentials.py and fill in your values.\n"
                f"Your credentials will be saved to the local DB after the first run.\n"
            )
        else:
            sys.exit(
                f"\nError: credentials file not found: '{path}'\n"
                f"Copy credentials.py.example → credentials.py and fill in your values.\n"
                f"Or pass a custom path:  --credentials /path/to/my_creds.py\n"
            )

    rh_username, rh_password, api_key = _load_from_file(path)

    # ── 3. Persist to DB so next run loads from DB ───────────────────
    if db is not None:
        db.set_credentials(rh_username, rh_password, api_key)
        print(
            f"  Credentials saved to local DB — "
            f"credentials.py is not needed for future runs."
        )

    return rh_username, rh_password, api_key


def _load_from_file(path: str) -> tuple[str, str, str]:
    spec = importlib.util.spec_from_file_location("_credentials", os.path.abspath(path))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    missing = [k for k in ("RH_USERNAME", "RH_PASSWORD", "ANTHROPIC_API_KEY") if not hasattr(mod, k)]
    if missing:
        sys.exit(f"\nError: credentials file '{path}' is missing: {', '.join(missing)}\n")

    return mod.RH_USERNAME, mod.RH_PASSWORD, mod.ANTHROPIC_API_KEY
