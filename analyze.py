import argparse
import os
import sys
import time
from datetime import datetime

# Ensure Unicode output works on all platforms (e.g. Windows cp1252 terminals)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from config import STATIC_HOLDINGS, SNAPSHOTS_FILE, HISTORY_FILE
from db import PortfolioDB
from run_config import load_run_config
from validation import validate_all, ValidationError
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
    print("[2/4] Fetching fundamentals, short interest, insider, institutional, calendar data...")
    fundamental_data, short_interest_data, dcf_inputs, insider_data, institutional_data, calendar_data = \
        market_data.fetch_market_data(tickers)

    print("[3/4] Computing technical indicators, correlation matrix, and benchmark comparison...")
    technical_data, price_history = market_data.compute_technicals(tickers)
    correlation_data = market_data.compute_correlation(price_history)

    print("[4/4] Computing DCF, portfolio metrics, and fetching news...")
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

    # Portfolio-level metrics (concentration, sector, noise, ETF overlap)
    portfolio_metrics = market_data.compute_portfolio_metrics(
        merged_holdings, fundamental_data, technical_data
    )

    timestamp_ms = int(time.time() * 1000)
    snapshot = {
        "timestamp_ms": timestamp_ms,
        "timestamp_iso": datetime.fromtimestamp(timestamp_ms / 1000).isoformat(),
        "portfolio_summary": portfolio_summary,
        "portfolio_metrics": portfolio_metrics,
        "fundamental_data": fundamental_data,
        "short_interest_data": short_interest_data,
        "dcf_inputs": dcf_inputs,
        "insider_data": insider_data,
        "institutional_data": institutional_data,
        "calendar_data": calendar_data,
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

def run_analysis(snapshot: dict, snapshot_id: int, db: PortfolioDB, api_key: str, run_cfg=None) -> None:
    """Run full Claude analysis on a snapshot and save all outputs."""
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

    history = db.get_history()
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
    analyses = analysis.run_all(
        snapshot,
        historical_comparison,
        full_history=history,
        run_config=run_cfg,
        api_key=api_key,
    )

    # Save outputs
    print("\n[3/3] Saving outputs...")

    # Persist analysis to DB
    db.save_analysis(
        snapshot_id,
        analyses,
        input_tokens=analyses.pop("input_tokens", 0),
        output_tokens=analyses.pop("output_tokens", 0),
    )
    db.save_history_entry(snapshot_id, current_run)

    # Write report files
    history_for_report = history + [current_run]
    if run_cfg is None or run_cfg.report_txt:
        report.write_txt(snapshot, analyses, historical_comparison)
    if run_cfg is None or run_cfg.report_xlsx:
        report.write_xlsx(snapshot, analyses, history_for_report)

    print("\nDone!")
    if run_cfg is None or run_cfg.report_txt:
        print("  analysis.txt             — Full narrative report")
    if run_cfg is None or run_cfg.report_xlsx:
        print("  portfolio_analysis.xlsx  — Excel workbook (8 sheets)")
    print("  portfolio_db.json        — TinyDB: snapshots + analyses + history")


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
  python analyze.py --data --holdings-file mine.txt add text-file holdings to snapshot
  python analyze.py --migrate                       import legacy .json.gz + history.json into DB""",
    )
    parser.add_argument("--data", action="store_true",
                        help="collect and store portfolio + market data snapshot")
    parser.add_argument("--analysis", action="store_true",
                        help="run Claude analysis and generate report files")
    parser.add_argument("--holdings-file", metavar="PATH",
                        help="text file with natural-language holdings description")
    parser.add_argument("--user", metavar="USERNAME", default="naeem",
                        help="username to run analysis for (default: naeem)")
    parser.add_argument("--config", metavar="PATH", default=None,
                        help="TOML config file to control which analyses run "
                             "(default: analysis.toml if present, else all analyses enabled)")
    parser.add_argument("--credentials", metavar="PATH", default="credentials.py",
                        help="credentials file for first-time setup (default: credentials.py). "
                             "Not needed after credentials are saved to the local DB.")
    parser.add_argument("--migrate", action="store_true",
                        help="import legacy portfolio_snapshots.json.gz and portfolio_history.json into DB")
    args = parser.parse_args()

    if not args.data and not args.analysis and not args.migrate:
        parser.print_help()
        sys.exit(1)

    try:
        run_cfg = load_run_config(args.config)
    except FileNotFoundError as e:
        sys.exit(str(e))

    print(f"\nAnalysis config:\n{run_cfg.summary()}")

    # DB must be initialised before loading credentials so they can be stored/retrieved.
    db = PortfolioDB(username=args.user)

    rh_username, rh_password, api_key = config.load_credentials(args.credentials, db)

    # Pre-flight validation
    if args.analysis or args.data:
        try:
            validate_all(
                api_key=api_key,
                run_cfg=run_cfg,
                db=db,
                need_snapshot=args.analysis and not args.data,
            )
            spending = db.user_spending()
            print(f"\n  Budget check passed — "
                  f"${spending['remaining_usd']:.2f} remaining of "
                  f"${spending['spending_limit_usd']:.2f} user limit")
        except ValidationError as e:
            sys.exit(f"\nValidation failed:\n{e}")

    # Migration from legacy files
    if args.migrate:
        n = db.migrate_from_gzip(SNAPSHOTS_FILE)
        print(f"Migrated {n} snapshot(s) from {SNAPSHOTS_FILE}")
        n = db.migrate_from_history_json(HISTORY_FILE)
        print(f"Migrated {n} history entry/entries from {HISTORY_FILE}")
        if not args.data and not args.analysis:
            return

    # Build broker list
    brokers = [RobinhoodBroker(rh_username, rh_password, db=db)]
    if STATIC_HOLDINGS:
        brokers.append(StaticBroker(STATIC_HOLDINGS))
    if args.holdings_file:
        brokers.append(TextFileBroker(args.holdings_file, api_key))

    snapshot = None
    snapshot_id = None

    if args.data:
        snapshot = collect_data(brokers)
        snapshot_id = db.save_snapshot(snapshot)
        print(f"Snapshot saved to portfolio_db.json (id={snapshot_id}, total={db.snapshot_count()})")

    if args.analysis:
        if snapshot is None:
            snapshot, snapshot_id = db.latest_snapshot()
            if not snapshot:
                sys.exit("No snapshots found in portfolio_db.json. Run with --data first.")
            print(
                f"Loaded latest snapshot from "
                f"{datetime.fromtimestamp(snapshot['timestamp_ms'] / 1000).strftime('%Y-%m-%d %H:%M:%S')} "
                f"(id={snapshot_id})"
            )
        run_analysis(snapshot, snapshot_id, db, api_key, run_cfg)


if __name__ == "__main__":
    main()
