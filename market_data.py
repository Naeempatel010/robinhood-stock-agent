import numpy as np
import pandas as pd
import ta
import yfinance as yf

from config import DCF_DISCOUNT_RATE, DCF_TERMINAL_GROWTH, DCF_YEARS
from utils import safe_float

# Tickers used as benchmarks for comparative analysis
_BENCHMARKS = {"SPY": "S&P 500", "QQQ": "Nasdaq 100"}


# ------------------------------------------------------------------ #
# Fundamentals / Short Interest / Insider / DCF inputs               #
# ------------------------------------------------------------------ #

def fetch_market_data(tickers: list) -> tuple:
    """
    Returns (fundamental_data, short_interest_data, dcf_inputs, insider_data,
             institutional_data, calendar_data).
    """
    fundamental_data    = {}
    short_interest_data = {}
    dcf_inputs          = {}
    insider_data        = {}
    institutional_data  = {}
    calendar_data       = {}

    for ticker in tickers:
        yf_ticker = yf.Ticker(ticker)

        # fast_info never 404s and gives us quote_type
        try:
            fi         = yf_ticker.fast_info
            quote_type = getattr(fi, "quote_type", "EQUITY") or "EQUITY"
            fast_price = getattr(fi, "last_price", None)
            fast_52h   = getattr(fi, "year_high", None)
            fast_52l   = getattr(fi, "year_low", None)
            fast_mcap  = getattr(fi, "market_cap", None)
        except Exception:
            quote_type = "EQUITY"
            fast_price = fast_52h = fast_52l = fast_mcap = None

        is_etf = quote_type.upper() == "ETF"

        try:
            info = yf_ticker.info or {}
        except Exception:
            info = {}

        # ---- ETF branch ----
        if is_etf:
            fundamental_data[ticker] = {
                "name":          info.get("longName", ticker),
                "type":          "ETF",
                "category":      info.get("category", "N/A"),
                "fund_family":   info.get("fundFamily", "N/A"),
                "expense_ratio": info.get("annualReportExpenseRatio"),
                "ytd_return":    info.get("ytdReturn"),
                "3y_return":     info.get("threeYearAverageReturn"),
                "5y_return":     info.get("fiveYearAverageReturn"),
                "dividend_yield": info.get("yield") or info.get("dividendYield"),
                "beta":          info.get("beta3Year") or info.get("beta"),
                "total_assets":  fast_mcap or info.get("totalAssets"),
                "52w_high":      fast_52h or info.get("fiftyTwoWeekHigh"),
                "52w_low":       fast_52l or info.get("fiftyTwoWeekLow"),
                "current_price": fast_price or info.get("regularMarketPrice"),
            }
            short_interest_data[ticker] = {"name": info.get("longName", ticker), "note": "ETF — no short interest data"}
            dcf_inputs[ticker]          = {"note": "ETF — DCF not applicable"}
            insider_data[ticker]        = []
            institutional_data[ticker]  = []
            calendar_data[ticker]       = {}

        # ---- Stock branch ----
        else:
            price       = info.get("currentPrice") or fast_price
            high_52w    = info.get("fiftyTwoWeekHigh") or fast_52h
            low_52w     = info.get("fiftyTwoWeekLow") or fast_52l

            # 52-week proximity (% below 52w high, % above 52w low)
            pct_below_52h = round((high_52w - price) / high_52w * 100, 1) if high_52w and price else None
            pct_above_52l = round((price - low_52w)  / low_52w  * 100, 1) if low_52w  and price else None

            fundamental_data[ticker] = {
                "name":             info.get("longName", ticker),
                "sector":           info.get("sector", "N/A"),
                "industry":         info.get("industry", "N/A"),
                "country":          info.get("country", "N/A"),
                "market_cap":       info.get("marketCap"),
                # Valuation ratios
                "pe_ratio":         info.get("trailingPE"),
                "forward_pe":       info.get("forwardPE"),
                "pb_ratio":         info.get("priceToBook"),
                "ps_ratio":         info.get("priceToSalesTrailing12Months"),
                "peg_ratio":        info.get("pegRatio"),
                "ev_to_ebitda":     info.get("enterpriseToEbitda"),
                # Growth
                "revenue_growth_yoy":   info.get("revenueGrowth"),
                "earnings_growth_yoy":  info.get("earningsGrowth"),
                "earnings_growth_qoq":  info.get("earningsQuarterlyGrowth"),
                "revenue_growth_qoq":   info.get("revenueQuarterlyGrowth"),
                # Earnings estimates
                "eps_current_year_est": info.get("epsCurrentYear"),
                "eps_next_year_est":    info.get("epsForward"),
                "earnings_estimate_growth": info.get("earningsGrowth"),
                # Profitability
                "eps":              info.get("trailingEps"),
                "profit_margin":    info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "return_on_equity": info.get("returnOnEquity"),
                "return_on_assets": info.get("returnOnAssets"),
                # Balance sheet
                "debt_to_equity":   info.get("debtToEquity"),
                "current_ratio":    info.get("currentRatio"),
                "quick_ratio":      info.get("quickRatio"),
                "total_cash":       info.get("totalCash"),
                "total_debt":       info.get("totalDebt"),
                # Cash flow
                "free_cash_flow":   info.get("freeCashflow"),
                "operating_cash_flow": info.get("operatingCashflow"),
                # Dividends
                "dividend_yield":   info.get("dividendYield"),
                "payout_ratio":     info.get("payoutRatio"),
                # Price / analyst
                "current_price":    price,
                "52w_high":         high_52w,
                "52w_low":          low_52w,
                "pct_below_52w_high": pct_below_52h,
                "pct_above_52w_low":  pct_above_52l,
                "analyst_rating":   info.get("recommendationKey"),
                "analyst_count":    info.get("numberOfAnalystOpinions"),
                "target_price":     info.get("targetMeanPrice"),
                "target_high":      info.get("targetHighPrice"),
                "target_low":       info.get("targetLowPrice"),
                "beta":             info.get("beta"),
            }

            short_interest_data[ticker] = {
                "name":                    info.get("longName", ticker),
                "shares_short":            info.get("sharesShort"),
                "short_ratio_days":        info.get("shortRatio"),
                "short_percent_of_float":  info.get("shortPercentOfFloat"),
                "shares_short_prior_month": info.get("sharesShortPriorMonth"),
                # MoM change
                "short_interest_mom_change": _short_mom_change(
                    info.get("shortPercentOfFloat"),
                    info.get("sharesShort"),
                    info.get("sharesShortPriorMonth"),
                ),
            }

            dcf_inputs[ticker] = {
                "free_cash_flow":    info.get("freeCashflow"),
                "revenue_growth":    info.get("revenueGrowth"),
                "earnings_growth":   info.get("earningsGrowth"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "current_price":     price,
            }

            # Insider transactions — open-market buys/sells only
            try:
                transactions = yf_ticker.insider_transactions
                if transactions is not None and not transactions.empty:
                    records = []
                    for _, row in transactions.head(20).iterrows():
                        text = str(row.get("Text", row.get("Transaction", ""))).lower()
                        # Keep only open-market purchases and sales; skip gifts, awards, plan transactions
                        if any(k in text for k in ("purchase", "sale", "sold", "bought")):
                            if not any(k in text for k in ("gift", "award", "plan", "automatic", "401k", "exercise")):
                                records.append({str(col): str(row[col]) for col in transactions.columns})
                        if len(records) >= 10:
                            break
                    insider_data[ticker] = records
                else:
                    insider_data[ticker] = []
            except Exception:
                insider_data[ticker] = []

            # Institutional ownership (top 10 holders from 13F)
            try:
                inst = yf_ticker.institutional_holders
                if inst is not None and not inst.empty:
                    rows = inst.head(10).to_dict(orient="records")
                    # Convert any non-JSON-serializable types (e.g. pandas Timestamp)
                    for row in rows:
                        for k, v in row.items():
                            if hasattr(v, "isoformat"):
                                row[k] = v.isoformat()
                    institutional_data[ticker] = rows
                else:
                    institutional_data[ticker] = []
            except Exception:
                institutional_data[ticker] = []

            # Calendar: earnings date, ex-dividend date
            try:
                cal = yf_ticker.calendar or {}
                # calendar is a dict with keys like 'Earnings Date', 'Ex-Dividend Date'
                earnings_dates = cal.get("Earnings Date", [])
                ex_div         = cal.get("Ex-Dividend Date")
                calendar_data[ticker] = {
                    "next_earnings_date": str(earnings_dates[0])[:10] if earnings_dates else None,
                    "ex_dividend_date":   str(ex_div)[:10] if ex_div else None,
                    "dividend_date":      str(cal.get("Dividend Date", ""))[:10] or None,
                }
            except Exception:
                calendar_data[ticker] = {}

    return fundamental_data, short_interest_data, dcf_inputs, insider_data, institutional_data, calendar_data


def _short_mom_change(pct_float, shares_short, shares_prior) -> dict | None:
    """Compute MoM short interest change."""
    if not shares_short or not shares_prior or shares_prior == 0:
        return None
    change   = shares_short - shares_prior
    pct_chg  = round(change / shares_prior * 100, 1)
    return {"shares_change": int(change), "pct_change": pct_chg,
            "direction": "increasing" if change > 0 else "decreasing"}


# ------------------------------------------------------------------ #
# Technical indicators                                                #
# ------------------------------------------------------------------ #

def compute_technicals(tickers: list) -> tuple:
    """
    RSI, MACD, BB, SMA 50/200, volume, support/resistance, alerts, benchmark comparison.
    Returns (technical_data, price_history).
    """
    technical_data = {}
    price_history  = {}

    # Fetch benchmark returns once
    benchmark_returns = _fetch_benchmark_returns()

    for ticker in tickers:
        hist = yf.Ticker(ticker).history(period="1y")
        if hist.empty or len(hist) < 20:
            continue

        close  = hist["Close"]
        volume = hist["Volume"]
        price_history[ticker] = close

        prev_1w  = hist.iloc[-6]  if len(hist) >= 6   else hist.iloc[0]
        prev_1m  = hist.iloc[-21] if len(hist) >= 21  else hist.iloc[0]
        prev_3m  = hist.iloc[-63] if len(hist) >= 63  else hist.iloc[0]
        prev_6m  = hist.iloc[-126] if len(hist) >= 126 else hist.iloc[0]
        prev_1y  = hist.iloc[0]

        cur_price = safe_float(close.iloc[-1])

        # Core indicators
        rsi       = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
        macd_obj  = ta.trend.MACD(close)
        bb        = ta.volatility.BollingerBands(close, window=20)
        sma50     = ta.trend.SMAIndicator(close, window=50).sma_indicator().iloc[-1]
        sma200    = ta.trend.SMAIndicator(close, window=200).sma_indicator().iloc[-1] if len(hist) >= 200 else None
        ema20     = ta.trend.EMAIndicator(close, window=20).ema_indicator().iloc[-1]

        # Volume analysis
        avg_vol_20  = safe_float(volume.rolling(20).mean().iloc[-1])
        cur_vol     = int(volume.iloc[-1])
        vol_spike   = round(cur_vol / avg_vol_20, 2) if avg_vol_20 else None  # >2.0 = unusual spike

        # Annualised volatility (20-day)
        daily_returns  = close.pct_change().dropna()
        volatility_20d = safe_float(daily_returns.rolling(20).std().iloc[-1] * (252 ** 0.5) * 100)

        # Support / resistance via pivot points (prior day H/L/C)
        support, resistance = _pivot_support_resistance(hist)

        # Price changes
        def _chg(prev_row):
            p = safe_float(prev_row["Close"])
            return round((cur_price - p) / p * 100, 2) if p else None

        change_1w = _chg(prev_1w)
        change_1m = _chg(prev_1m)
        change_3m = _chg(prev_3m)
        change_6m = _chg(prev_6m)
        change_1y = _chg(prev_1y)

        # Trend direction label
        trend_dir = _trend_direction(cur_price, safe_float(sma50), safe_float(sma200) if sma200 is not None else None)

        # Alerts (rule-based, no LLM needed)
        alerts = _compute_alerts(
            rsi=safe_float(rsi),
            price=cur_price,
            sma50=safe_float(sma50),
            sma200=safe_float(sma200) if sma200 is not None else None,
            vol_spike=vol_spike,
            bb_upper=safe_float(bb.bollinger_hband().iloc[-1]),
            bb_lower=safe_float(bb.bollinger_lband().iloc[-1]),
            macd=safe_float(macd_obj.macd().iloc[-1]),
            macd_signal=safe_float(macd_obj.macd_signal().iloc[-1]),
        )

        # Benchmark-relative performance
        rel_perf = {}
        for bm_ticker, bm_name in _BENCHMARKS.items():
            bm = benchmark_returns.get(bm_ticker, {})
            for period in ("1w", "1m", "3m", "6m", "1y"):
                stock_chg = {"1w": change_1w, "1m": change_1m, "3m": change_3m,
                             "6m": change_6m, "1y": change_1y}.get(period)
                bm_chg = bm.get(period)
                if stock_chg is not None and bm_chg is not None:
                    rel_perf.setdefault(bm_name, {})[period] = round(stock_chg - bm_chg, 2)

        technical_data[ticker] = {
            "current_price":   cur_price,
            "trend_direction": trend_dir,
            # Momentum
            "rsi_14":          safe_float(rsi),
            "macd":            safe_float(macd_obj.macd().iloc[-1]),
            "macd_signal":     safe_float(macd_obj.macd_signal().iloc[-1]),
            "macd_histogram":  safe_float(macd_obj.macd_diff().iloc[-1]),
            # Bands / MAs
            "bb_upper":        safe_float(bb.bollinger_hband().iloc[-1]),
            "bb_lower":        safe_float(bb.bollinger_lband().iloc[-1]),
            "bb_mid":          safe_float(bb.bollinger_mavg().iloc[-1]),
            "sma_50":          safe_float(sma50),
            "sma_200":         safe_float(sma200) if sma200 is not None else None,
            "ema_20":          safe_float(ema20),
            # Volatility
            "volatility_20d_annualized_pct": volatility_20d,
            # Volume
            "volume":          cur_vol,
            "avg_volume_20d":  int(avg_vol_20) if avg_vol_20 else None,
            "volume_spike_ratio": vol_spike,
            # Support / Resistance
            "support":         support,
            "resistance":      resistance,
            # Price changes
            "change_1w_pct":   change_1w,
            "change_1m_pct":   change_1m,
            "change_3m_pct":   change_3m,
            "change_6m_pct":   change_6m,
            "change_1y_pct":   change_1y,
            # Alerts
            "alerts":          alerts,
            # Benchmark-relative
            "vs_benchmark":    rel_perf,
        }

    return technical_data, price_history


def _trend_direction(price, sma50, sma200) -> str:
    if sma50 is None:
        return "unknown"
    if sma200 is not None:
        if price > sma50 > sma200:
            return "strong_uptrend"
        if price > sma50 and sma50 < sma200:
            return "recovering"
        if price < sma50 < sma200:
            return "strong_downtrend"
        if price < sma50 and sma50 > sma200:
            return "weakening"
    return "uptrend" if price > sma50 else "downtrend"


def _pivot_support_resistance(hist: pd.DataFrame) -> tuple:
    """Classic pivot point support/resistance from last 20 days."""
    recent = hist.tail(20)
    h = recent["High"].max()
    l = recent["Low"].min()
    c = recent["Close"].iloc[-1]
    pivot      = (h + l + c) / 3
    support    = round(2 * pivot - h, 2)
    resistance = round(2 * pivot - l, 2)
    return support, resistance


def _compute_alerts(rsi, price, sma50, sma200, vol_spike, bb_upper, bb_lower, macd, macd_signal) -> list:
    """Rule-based alert flags — no LLM."""
    alerts = []
    if rsi and rsi > 70:
        alerts.append(f"RSI overbought ({rsi:.1f})")
    if rsi and rsi < 30:
        alerts.append(f"RSI oversold ({rsi:.1f})")
    if price and sma50:
        if abs(price - sma50) / sma50 < 0.01:
            alerts.append("Price testing SMA50")
        if price > sma50 * 1.0 and (not hasattr(_compute_alerts, "_prev") or True):
            pass  # would need prev-day price for crossover — skip
    if sma50 and sma200:
        if abs(sma50 - sma200) / sma200 < 0.005:
            alerts.append("SMA50/200 death-cross or golden-cross imminent")
    if vol_spike and vol_spike >= 2.0:
        alerts.append(f"Unusual volume spike ({vol_spike:.1f}x avg)")
    if price and bb_upper and price >= bb_upper:
        alerts.append("Price at/above Bollinger upper band")
    if price and bb_lower and price <= bb_lower:
        alerts.append("Price at/below Bollinger lower band")
    if macd is not None and macd_signal is not None:
        if macd > macd_signal and abs(macd - macd_signal) < 0.5:
            alerts.append("MACD bullish crossover forming")
        if macd < macd_signal and abs(macd - macd_signal) < 0.5:
            alerts.append("MACD bearish crossover forming")
    return alerts


def _fetch_benchmark_returns() -> dict:
    """Fetch SPY + QQQ price changes for 1w/1m/3m/6m/1y."""
    result = {}
    for ticker in _BENCHMARKS:
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            if hist.empty or len(hist) < 5:
                continue
            c = hist["Close"]
            cur = c.iloc[-1]
            def _chg(i):
                p = c.iloc[i] if len(c) > abs(i) else c.iloc[0]
                return round((cur - p) / p * 100, 2)
            result[ticker] = {
                "1w": _chg(-6),
                "1m": _chg(-21),
                "3m": _chg(-63),
                "6m": _chg(-126),
                "1y": _chg(0),
            }
        except Exception:
            pass
    return result


# ------------------------------------------------------------------ #
# Portfolio-level metrics                                             #
# ------------------------------------------------------------------ #

def compute_portfolio_metrics(holdings: dict, fundamental_data: dict, technical_data: dict) -> dict:
    """
    Concentration risk, sector exposure, ETF overlap check, noise flags.
    Returns a dict passed to the portfolio analysis node.
    """
    total_equity = sum(h.get("equity", 0) or 0 for h in holdings.values())

    # Concentration per position
    concentration = {}
    for ticker, h in holdings.items():
        eq = h.get("equity", 0) or 0
        pct = round(eq / total_equity * 100, 2) if total_equity else 0
        concentration[ticker] = {
            "equity": eq,
            "pct_of_portfolio": pct,
            "noise": pct < 1.0,  # flag positions < 1% as noise
        }

    # Sector exposure
    sector_exposure: dict[str, float] = {}
    for ticker, h in holdings.items():
        fd = fundamental_data.get(ticker, {})
        sector = fd.get("sector") or fd.get("type") or "Unknown"
        eq = h.get("equity", 0) or 0
        sector_exposure[sector] = sector_exposure.get(sector, 0) + eq

    sector_pct = {
        s: round(eq / total_equity * 100, 2)
        for s, eq in sorted(sector_exposure.items(), key=lambda x: -x[1])
        if total_equity
    }

    # Noise positions
    noise_positions = [t for t, v in concentration.items() if v["noise"]]

    # ETF overlap check (basic — flag if any ETF is held alongside its components)
    etf_tickers  = [t for t, fd in fundamental_data.items() if fd.get("type") == "ETF"]
    stock_tickers = [t for t in holdings if t not in etf_tickers]
    # Known large ETF → common components (rough heuristic)
    _known_overlap = {
        "VOO": ["AAPL","MSFT","AMZN","NVDA","GOOGL","META","TSLA","AVGO","BRK.B","JPM"],
        "VTI": ["AAPL","MSFT","AMZN","NVDA","GOOGL","META","TSLA","AVGO","BRK.B","JPM"],
        "QQQ": ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","COST"],
        "QQQM":["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","COST"],
        "SPY": ["AAPL","MSFT","AMZN","NVDA","GOOGL","META","TSLA","AVGO","BRK.B","JPM"],
    }
    etf_overlaps = {}
    for etf in etf_tickers:
        components = _known_overlap.get(etf, [])
        overlap = [t for t in stock_tickers if t in components]
        if overlap:
            etf_overlaps[etf] = overlap

    return {
        "total_equity":    round(total_equity, 2),
        "concentration":   concentration,
        "sector_exposure": sector_pct,
        "noise_positions": noise_positions,
        "etf_overlaps":    etf_overlaps,
    }


# ------------------------------------------------------------------ #
# Correlation                                                         #
# ------------------------------------------------------------------ #

def compute_correlation(price_history: dict) -> dict:
    if len(price_history) < 2:
        return {}
    prices_df  = pd.DataFrame(price_history).dropna()
    returns_df = prices_df.pct_change().dropna()
    corr_matrix = returns_df.corr()
    upper_tri   = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
    avg_corr    = float(np.mean(upper_tri))
    return {
        "matrix":               corr_matrix.round(3).to_dict(),
        "avg_correlation":      round(avg_corr, 3),
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
    terminal  = projected[-1] * (1 + DCF_TERMINAL_GROWTH) / (DCF_DISCOUNT_RATE - DCF_TERMINAL_GROWTH)
    pv = sum(cf / (1 + DCF_DISCOUNT_RATE) ** i for i, cf in enumerate(projected, 1))
    pv += terminal / (1 + DCF_DISCOUNT_RATE) ** DCF_YEARS
    return round(pv / shares, 2)


def compute_dcf(dcf_inputs: dict) -> dict:
    dcf_results = {}
    for ticker, inp in dcf_inputs.items():
        if "note" in inp:
            dcf_results[ticker] = inp
            continue
        fcf      = inp.get("free_cash_flow")
        growth   = inp.get("earnings_growth") or inp.get("revenue_growth")
        shares   = inp.get("shares_outstanding")
        price    = inp.get("current_price")
        intrinsic = _dcf_intrinsic(fcf, growth, shares)
        if intrinsic and price:
            mos = round((intrinsic - price) / price * 100, 1)
            dcf_results[ticker] = {
                "intrinsic_value":      intrinsic,
                "current_price":        price,
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
    news_data = {}
    for ticker in tickers:
        raw = yf.Ticker(ticker).news or []
        news_data[ticker] = [
            {
                "title":     n.get("content", {}).get("title") or n.get("title", ""),
                "publisher": n.get("content", {}).get("provider", {}).get("displayName") or n.get("publisher", ""),
                "date":      (n.get("content", {}).get("pubDate") or "")[:10],
            }
            for n in raw[:6]
        ]

    market_news_raw = yf.Ticker("SPY").news or []
    market_news = [
        {
            "title":     n.get("content", {}).get("title") or n.get("title", ""),
            "publisher": n.get("content", {}).get("provider", {}).get("displayName") or n.get("publisher", ""),
        }
        for n in market_news_raw[:8]
    ]

    return news_data, market_news
