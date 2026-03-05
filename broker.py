from abc import ABC, abstractmethod
import json
import re


class Broker(ABC):
    @abstractmethod
    def login(self): ...

    @abstractmethod
    def logout(self): ...

    @abstractmethod
    def get_holdings(self) -> dict:
        """Returns {TICKER: {shares, avg_buy_price, equity, percent_change, equity_change, source}}"""
        ...

    @abstractmethod
    def get_account_summary(self) -> dict:
        """Returns {equity, market_value, cash, buying_power}"""
        ...


class StaticBroker(Broker):
    """For hardcoded/vesting holdings (e.g. AMZN from STATIC_HOLDINGS)."""

    def __init__(self, holdings: dict):
        self._holdings = holdings

    def login(self):
        pass

    def logout(self):
        pass

    def get_holdings(self) -> dict:
        return {
            ticker: {
                "shares": float(info["shares"]),
                "avg_buy_price": float(info.get("avg_buy_price", 0)),
                "equity": 0,  # updated after market data fetch
                "percent_change": 0,
                "equity_change": 0,
                "source": "vesting",
                "plan": info.get("plan", ""),
            }
            for ticker, info in self._holdings.items()
        }

    def get_account_summary(self) -> dict:
        return {"equity": 0, "market_value": 0, "cash": 0, "buying_power": 0}


class TextFileBroker(Broker):
    """
    Parses a natural-language text file into holdings using Claude.
    Users describe their portfolio in plain English; Claude extracts tickers+shares as JSON.
    """

    def __init__(self, filepath: str, api_key: str):
        self.filepath = filepath
        self.api_key = api_key

    def login(self):
        pass

    def logout(self):
        pass

    def get_holdings(self) -> dict:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        with open(self.filepath, encoding="utf-8") as f:
            text = f.read()

        llm = ChatAnthropic(model="claude-sonnet-4-6", api_key=self.api_key, max_tokens=1024)
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a financial data parser. Extract stock holdings from text."),
            ("human", """Parse the following text and extract all stock holdings.
Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "TICKER": {{"shares": <number>, "avg_buy_price": <number or 0>}},
  ...
}}

Text:
{text}"""),
        ])
        result = (prompt | llm | StrOutputParser()).invoke({"text": text})

        match = re.search(r"\{.*\}", result, re.DOTALL)
        holdings_raw = json.loads(match.group() if match else result)

        return {
            ticker: {
                "shares": float(info["shares"]),
                "avg_buy_price": float(info.get("avg_buy_price", 0)),
                "equity": 0,  # updated after market data fetch
                "percent_change": 0,
                "equity_change": 0,
                "source": "text",
            }
            for ticker, info in holdings_raw.items()
        }

    def get_account_summary(self) -> dict:
        return {"equity": 0, "market_value": 0, "cash": 0, "buying_power": 0}
