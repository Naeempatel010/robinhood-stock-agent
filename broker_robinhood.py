import robin_stocks.robinhood as rh

from broker import Broker
from utils import safe_float


class RobinhoodBroker(Broker):
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    def login(self):
        rh.login(self.username, self.password)

    def logout(self):
        rh.logout()

    def get_holdings(self) -> dict:
        holdings = rh.account.build_holdings()
        return {
            ticker: {
                "shares": safe_float(data.get("quantity")),
                "avg_buy_price": safe_float(data.get("average_buy_price")),
                "equity": safe_float(data.get("equity")),
                "percent_change": safe_float(data.get("percent_change")),
                "equity_change": safe_float(data.get("equity_change")),
                "source": "robinhood",
            }
            for ticker, data in holdings.items()
        }

    def get_account_summary(self) -> dict:
        portfolio_profile = rh.profiles.load_portfolio_profile()
        account_profile = rh.profiles.load_account_profile()
        return {
            "equity": safe_float(portfolio_profile.get("equity")),
            "market_value": safe_float(portfolio_profile.get("market_value")),
            "cash": safe_float(account_profile.get("cash")),
            "buying_power": safe_float(account_profile.get("buying_power")),
        }
