import os
import pickle as pkl

import robin_stocks.robinhood as rh

from broker import Broker
from utils import safe_float

# Default robin_stocks pickle location (~/.tokens/robinhood.pickle)
_PICKLE_DIR  = os.path.join(os.path.expanduser("~"), ".tokens")
_PICKLE_FILE = os.path.join(_PICKLE_DIR, "robinhood.pickle")


class RobinhoodBroker(Broker):
    def __init__(self, username: str = None, password: str = None, db=None):
        self.username = username
        self.password = password
        self.db = db

    def login(self):
        # Restore previously-saved session pickle from DB so robin_stocks
        # reuses the token without hitting the login endpoint each run.
        if self.db:
            self._restore_pickle_from_db()

        rh.login(self.username or "", self.password or "")

        # Back up the updated pickle (may have a refreshed token) to DB.
        if self.db:
            self._backup_pickle_to_db()

    def logout(self):
        rh.logout()

    def get_holdings(self) -> dict:
        holdings = rh.account.build_holdings()
        return {
            ticker: {
                # Position data
                "shares":                  safe_float(data.get("quantity")),
                "avg_buy_price":           safe_float(data.get("average_buy_price")),
                "equity":                  safe_float(data.get("equity")),
                "percent_change":          safe_float(data.get("percent_change")),
                "equity_change":           safe_float(data.get("equity_change")),
                # Current price / market data
                "price":                   safe_float(data.get("price")),
                "intraday_percent_change": safe_float(data.get("intraday_percent_change")),
                "intraday_quantity":       safe_float(data.get("intraday_quantity")),
                # Security info
                "name":                    data.get("name"),
                "type":                    data.get("type"),
                "pe_ratio":                safe_float(data.get("pe_ratio")),
                "percentage":              safe_float(data.get("percentage")),
                "country":                 data.get("country"),
                "source": "robinhood",
            }
            for ticker, data in holdings.items()
        }

    def get_account_summary(self) -> dict:
        portfolio_profile = rh.profiles.load_portfolio_profile()
        account_profile = rh.profiles.load_account_profile()
        return {
            "equity":       safe_float(portfolio_profile.get("equity")),
            "market_value": safe_float(portfolio_profile.get("market_value")),
            "cash":         safe_float(account_profile.get("cash")),
            "buying_power": safe_float(account_profile.get("buying_power")),
        }

    # ------------------------------------------------------------------
    # Token persistence helpers
    # ------------------------------------------------------------------

    def _restore_pickle_from_db(self) -> None:
        """Write DB-stored session pickle to disk so robin_stocks uses it."""
        pickle_bytes = self.db.get_rh_pickle_bytes()
        if pickle_bytes:
            os.makedirs(_PICKLE_DIR, exist_ok=True)
            with open(_PICKLE_FILE, "wb") as f:
                f.write(pickle_bytes)

    def _backup_pickle_to_db(self) -> None:
        """Read the on-disk pickle (updated by robin_stocks) and store it in DB."""
        if os.path.exists(_PICKLE_FILE):
            with open(_PICKLE_FILE, "rb") as f:
                self.db.save_rh_pickle(f.read())
