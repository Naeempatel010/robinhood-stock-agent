import argparse
import json
import os
import sys
import time
from datetime import datetime

import config
from config import (
    HISTORY_FILE,
    SNAPSHOTS_FILE,
    STATIC_HOLDINGS,
)
from data_store import PortfolioDataStore
from broker import StaticBroker, TextFileBroker
from broker_robinhood import RobinhoodBroker
import market_data
import analysis
import report


# ------------------------------------------------------------------ #
# Data collection                                                     #
# ------------------------------------------------------------------ #

def collect_data(brokers: list) -> dict:
    """Login to all brokers, merge holdings, fetch market data, return snapshot."""

    # Step 1: Get holdings + account summary from each broker
    print("\n[1/4] Collecting portfolio data from brokers...")
    broker_results = []
    for broker in brokers:
        broker.login()
        holdings = broker.get_holdings()
        summary = broker.get_account_summary()
        broker.logout()
        broker_results.append((holdings, summary))

    # Collect all unique tickers across all brokers
    tickers_set = set()
    for holdings, _ in broker_results:
        tickers_set.update(holdings.keys())
    tickers = sorted(tickers_set)

    # Steps 2-4: Fetch all market data
    print("[2/4] Fetching fundamentals, short interest, insider data...")
    fundamental_data, short_interest_data, dcf_inputs, insider_data = market_data.fetch_market_data(tickers)

    print("[3/4] Computing technical indicators and correlation matrix...")
    technical_data, price_history = market_data.compute_technicals(tickers)
    correlation_data = market_data.compute_correlation(price_history)

    print("[4/4] Computing DCF valuations and fetching news...")
    dcf_results = market_data.compute_dcf(dcf_inputs)
    news_data, market_news = market_data.fetch_news(tickers)

    # Update equity for vesting/text holdings using live current_price * shares
    for holdings, _ in broker_results:
        for ticker, holding in holdings.items():
            if holding.get("source") in ("vesting", "text"):
                price = technical_data.get(ticker, {}).get("current_price", 0)
                holding["equity"] = round(holding["shares"] * price, 2)

    # Merge holdings: same ticker across brokers → sum shares + equity
    merged_holdings = {}
    for holdings, _ in broker_results:
        for ticker, holding in holdings.items():
            if ticker not in merged_holdings:
                merged_holdings[ticker] = {
                    "shares": 0,
                    "avg_buy_price": holding["avg_buy_price"],
                    "equity": 0,
                    "percent_change": holding.get("percent_change", 0),
                    "equity_change": holding.get("equity_change", 0),
                }
            merged_holdings[ticker]["shares"] = round(
                merged_holdings[ticker]["shares"] + holding["shares"], 4
            )
            merged_holdings[ticker]["equity"] = round(
                merged_holdings[ticker]["equity"] + holding["equity"], 2
            )

    # Portfolio equity: primary broker (RH) equity + non-primary broker equities
    primary_summary = broker_results[0][1]
    extra_equity = sum(
        holding["equity"]
        for holdings, _ in broker_results[1:]
        for holding in holdings.values()
    )

    portfolio_summary = {
        "equity": round(primary_summary["equity"] + extra_equity, 2),
        "market_value": round(primary_summary.get("market_value", 0) + extra_equity, 2),
        "cash": primary_summary["cash"],
        "buying_power": primary_summary["buying_power"],
        "holdings": merged_holdings,
    }

    timestamp_ms = int(time.time() * 1000)
    snapshot = {
        "timestamp_ms": timestamp_ms,
        "timestamp_iso": datetime.fromtimestamp(timestamp_ms / 1000).isoformat(),
        "portfolio_summary": portfolio_summary,
        "fundamental_data": fundamental_data,
        "short_interest_data": short_interest_data,
        "dcf_inputs": dcf_inputs,
        "insider_data": insider_data,
        "technical_data": technical_data,
        "correlation_data": correlation_data,
        "dcf_results": dcf_results,
        "news_data": news_data,
        "market_news": market_news,
    }

    print(
        f"\nData collected at "
        f"{datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')} "
        f"(ts={timestamp_ms})"
    )
    return snapshot


# ------------------------------------------------------------------ #
# Analysis                                                            #
# ------------------------------------------------------------------ #

def run_analysis(snapshot: dict, api_key: str) -> None:
    """Run full Claude analysis on a snapshot and generate output files."""
    ps = snapshot["portfolio_summary"]
    technical_data = snapshot["technical_data"]
    tickers = list(ps["holdings"].keys())
    collected_at = datetime.fromtimestamp(snapshot["timestamp_ms"] / 1000).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\nRunning analysis on snapshot from {collected_at}")

    # Build current_run for history
    print("\n[1/3] Loading historical run data...")
    current_run = {
        "date": snapshot["timestamp_iso"],
        "equity": ps["equity"],
        "cash": ps["cash"],
        "holdings": {
            t: {
                "equity": ps["holdings"][t]["equity"],
                "shares": ps["holdings"][t]["shares"],
                "price": technical_data.get(t, {}).get("current_price", 0),
            }
            for t in tickers
        },
    }

    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            history = json.load(f)

    historical_comparison = {}
    if history:
        prev = history[-1]
        eq_prev = prev["equity"]
        eq_curr = current_run["equity"]
        historical_comparison = {
            "previous_date": prev["date"][:10],
            "previous_equity": eq_prev,
            "current_equity": eq_curr,
            "equity_change": round(eq_curr - eq_prev, 2),
            "equity_change_pct": round((eq_curr - eq_prev) / eq_prev * 100, 2) if eq_prev else 0,
            "holdings_changes": {
                t: {
                    "prev_equity": prev["holdings"].get(t, {}).get("equity", 0),
                    "curr_equity": current_run["holdings"].get(t, {}).get("equity", 0),
                    "change": round(
                        current_run["holdings"].get(t, {}).get("equity", 0)
                        - prev["holdings"].get(t, {}).get("equity", 0),
                        2,
                    ),
                    "change_pct": round(
                        (
                            current_run["holdings"].get(t, {}).get("equity", 0)
                            - prev["holdings"].get(t, {}).get("equity", 0)
                        )
                        / prev["holdings"].get(t, {}).get("equity", 1)
                        * 100,
                        2,
                    ),
                }
                for t in tickers
                if t in prev.get("holdings", {})
            },
        }

    # Run Claude analysis
    print("[2/3] Running Claude analysis (this may take a few minutes)...")
    analyses = analysis.run_all(snapshot, historical_comparison, api_key=api_key)

    # Save outputs
    print("\n[3/3] Saving outputs...")
    history_updated = history + [current_run]
    report.write_txt(snapshot, analyses, historical_comparison)
    report.write_xlsx(snapshot, analyses, history_updated)

    with open(HISTORY_FILE, "w") as f:
        json.dump(history_updated, f, indent=2)

    print("\nDone!")
    print("  analysis.txt             — Full narrative report")
    print("  portfolio_analysis.xlsx  — Excel workbook (8 sheets)")
    print("  portfolio_history.json   — Historical run data updated")


# ------------------------------------------------------------------ #
# Entry point                                                         #
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description="Robinhood Portfolio Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python analyze.py --data                          collect and store portfolio snapshot
  python analyze.py --analysis                      analyze latest stored snapshot
  python analyze.py --data --analysis               collect then analyze
  python analyze.py --data --holdings-file mine.txt add text-file holdings to snapshot""",
    )
    parser.add_argument("--data", action="store_true",
                        help="collect and store portfolio + market data snapshot")
    parser.add_argument("--analysis", action="store_true",
                        help="run Claude analysis and generate report files")
    parser.add_argument("--holdings-file", metavar="PATH",
                        help="text file with natural-language holdings description")
    parser.add_argument("--credentials", metavar="PATH", default="credentials.py",
                        help="path to credentials file (default: credentials.py)")
    args = parser.parse_args()

    if not args.data and not args.analysis:
        parser.print_help()
        sys.exit(1)

    rh_username, rh_password, api_key = config.load_credentials(args.credentials)

    # Build broker list
    brokers = [RobinhoodBroker(rh_username, rh_password)]
    if STATIC_HOLDINGS:
        brokers.append(StaticBroker(STATIC_HOLDINGS))
    if args.holdings_file:
        brokers.append(TextFileBroker(args.holdings_file, api_key))

    store = PortfolioDataStore(SNAPSHOTS_FILE)
    snapshot = None

    if args.data:
        snapshot = collect_data(brokers)
        total = store.append(snapshot)
        print(f"Snapshot saved to {SNAPSHOTS_FILE} (total snapshots: {total})")

    if args.analysis:
        if snapshot is None:
            snapshot = store.latest()
            if not snapshot:
                sys.exit(f"No snapshots found. Run with --data first.")
            print(
                f"Loaded latest snapshot from "
                f"{datetime.fromtimestamp(snapshot['timestamp_ms'] / 1000).strftime('%Y-%m-%d %H:%M:%S')} "
                f"(ts={snapshot['timestamp_ms']})"
            )
        run_analysis(snapshot, api_key)


if __name__ == "__main__":
    main()
