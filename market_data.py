import numpy as np
import pandas as pd
import ta
import yfinance as yf

from config import DCF_DISCOUNT_RATE, DCF_TERMINAL_GROWTH, DCF_YEARS
from utils import safe_float


# ------------------------------------------------------------------ #
# Fundamentals / Short Interest / Insider / DCF inputs               #
# ------------------------------------------------------------------ #

def fetch_market_data(tickers: list) -> tuple:
    """
    One yfinance .info call per ticker.
    Returns (fundamental_data, short_interest_data, dcf_inputs, insider_data).
    """
    fundamental_data = {}
    short_interest_data = {}
    dcf_inputs = {}
    insider_data = {}

    for ticker in tickers:
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info

        fundamental_data[ticker] = {
            "name": info.get("longName", ticker),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "eps": info.get("trailingEps"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "debt_to_equity": info.get("debtToEquity"),
            "profit_margin": info.get("profitMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "current_ratio": info.get("currentRatio"),
            "dividend_yield": info.get("dividendYield"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "current_price": info.get("currentPrice"),
            "analyst_rating": info.get("recommendationKey"),
            "target_price": info.get("targetMeanPrice"),
            "beta": info.get("beta"),
        }

        short_interest_data[ticker] = {
            "name": info.get("longName", ticker),
            "shares_short": info.get("sharesShort"),
            "short_ratio_days": info.get("shortRatio"),
            "short_percent_of_float": info.get("shortPercentOfFloat"),
            "shares_short_prior_month": info.get("sharesShortPriorMonth"),
        }

        dcf_inputs[ticker] = {
            "free_cash_flow": info.get("freeCashflow"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "current_price": info.get("currentPrice"),
        }

        try:
            transactions = yf_ticker.insider_transactions
            if transactions is not None and not transactions.empty:
                records = []
                for _, row in transactions.head(10).iterrows():
                    records.append({str(col): str(row[col]) for col in transactions.columns})
                insider_data[ticker] = records
            else:
                insider_data[ticker] = []
        except Exception:
            insider_data[ticker] = []

    return fundamental_data, short_interest_data, dcf_inputs, insider_data


# ------------------------------------------------------------------ #
# Technical indicators                                                #
# ------------------------------------------------------------------ #

def compute_technicals(tickers: list) -> tuple:
    """
    RSI, MACD, Bollinger Bands, SMA50/200, price changes.
    Returns (technical_data, price_history).
    price_history is {ticker: pd.Series} — not JSON-serializable, used only for correlation.
    """
    technical_data = {}
    price_history = {}

    for ticker in tickers:
        hist = yf.Ticker(ticker).history(period="1y")
        if hist.empty or len(hist) < 20:
            continue

        close = hist["Close"]
        price_history[ticker] = close

        prev_month = hist.iloc[-21] if len(hist) >= 21 else hist.iloc[0]
        prev_3m = hist.iloc[-63] if len(hist) >= 63 else hist.iloc[0]
        prev_6m = hist.iloc[-126] if len(hist) >= 126 else hist.iloc[0]

        rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
        macd_obj = ta.trend.MACD(close)
        bb = ta.volatility.BollingerBands(close, window=20)
        sma50 = ta.trend.SMAIndicator(close, window=50).sma_indicator().iloc[-1]
        sma200 = ta.trend.SMAIndicator(close, window=200).sma_indicator().iloc[-1] if len(hist) >= 200 else None

        technical_data[ticker] = {
            "current_price": safe_float(close.iloc[-1]),
            "rsi_14": safe_float(rsi),
            "macd": safe_float(macd_obj.macd().iloc[-1]),
            "macd_signal": safe_float(macd_obj.macd_signal().iloc[-1]),
            "macd_histogram": safe_float(macd_obj.macd_diff().iloc[-1]),
            "bb_upper": safe_float(bb.bollinger_hband().iloc[-1]),
            "bb_lower": safe_float(bb.bollinger_lband().iloc[-1]),
            "bb_mid": safe_float(bb.bollinger_mavg().iloc[-1]),
            "sma_50": safe_float(sma50),
            "sma_200": safe_float(sma200) if sma200 is not None else "N/A",
            "volume": int(hist["Volume"].iloc[-1]),
            "change_1m_pct": safe_float((close.iloc[-1] - prev_month["Close"]) / prev_month["Close"] * 100),
            "change_3m_pct": safe_float((close.iloc[-1] - prev_3m["Close"]) / prev_3m["Close"] * 100),
            "change_6m_pct": safe_float((close.iloc[-1] - prev_6m["Close"]) / prev_6m["Close"] * 100),
        }

    return technical_data, price_history


# ------------------------------------------------------------------ #
# Correlation                                                         #
# ------------------------------------------------------------------ #

def compute_correlation(price_history: dict) -> dict:
    """
    Correlation matrix + avg_correlation + diversification_score.
    price_history: {ticker: pd.Series of close prices}
    """
    if len(price_history) < 2:
        return {}

    prices_df = pd.DataFrame(price_history).dropna()
    returns_df = prices_df.pct_change().dropna()
    corr_matrix = returns_df.corr()
    upper_tri = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
    avg_corr = float(np.mean(upper_tri))

    return {
        "matrix": corr_matrix.round(3).to_dict(),
        "avg_correlation": round(avg_corr, 3),
        "diversification_score": round((1 - avg_corr) * 10, 1),
    }


# ------------------------------------------------------------------ #
# DCF valuation                                                       #
# ------------------------------------------------------------------ #

def _dcf_intrinsic(fcf, growth_rate, shares):
    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return None
    g = min(max(float(growth_rate or 0.05), -0.20), 0.40)
    projected = [fcf * (1 + g) ** i for i in range(1, DCF_YEARS + 1)]
    terminal = projected[-1] * (1 + DCF_TERMINAL_GROWTH) / (DCF_DISCOUNT_RATE - DCF_TERMINAL_GROWTH)
    pv = sum(cf / (1 + DCF_DISCOUNT_RATE) ** i for i, cf in enumerate(projected, 1))
    pv += terminal / (1 + DCF_DISCOUNT_RATE) ** DCF_YEARS
    return round(pv / shares, 2)


def compute_dcf(dcf_inputs: dict) -> dict:
    """DCF valuation per ticker."""
    dcf_results = {}
    for ticker, inp in dcf_inputs.items():
        fcf = inp.get("free_cash_flow")
        growth = inp.get("earnings_growth") or inp.get("revenue_growth")
        shares = inp.get("shares_outstanding")
        price = inp.get("current_price")
        intrinsic = _dcf_intrinsic(fcf, growth, shares)
        if intrinsic and price:
            mos = round((intrinsic - price) / price * 100, 1)
            dcf_results[ticker] = {
                "intrinsic_value": intrinsic,
                "current_price": price,
                "margin_of_safety_pct": mos,
                "verdict": "Undervalued" if mos > 15 else "Overvalued" if mos < -15 else "Fair Value",
            }
        else:
            dcf_results[ticker] = {"note": "Insufficient data (ETF or negative/missing FCF)"}
    return dcf_results


# ------------------------------------------------------------------ #
# News                                                                #
# ------------------------------------------------------------------ #

def fetch_news(tickers: list) -> tuple:
    """
    Per-ticker news + SPY market news.
    Returns (news_data, market_news).
    """
    news_data = {}
    for ticker in tickers:
        raw = yf.Ticker(ticker).news or []
        news_data[ticker] = [
            {
                "title": n.get("content", {}).get("title") or n.get("title", ""),
                "publisher": n.get("content", {}).get("provider", {}).get("displayName") or n.get("publisher", ""),
                "date": (n.get("content", {}).get("pubDate") or "")[:10],
            }
            for n in raw[:6]
        ]

    market_news_raw = yf.Ticker("SPY").news or []
    market_news = [
        {
            "title": n.get("content", {}).get("title") or n.get("title", ""),
            "publisher": n.get("content", {}).get("provider", {}).get("displayName") or n.get("publisher", ""),
        }
        for n in market_news_raw[:8]
    ]

    return news_data, market_news
