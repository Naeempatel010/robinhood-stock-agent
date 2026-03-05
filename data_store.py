"""
PortfolioDataStore — compressed, queryable store for portfolio snapshots.

Snapshots are stored in gzip-compressed JSON (portfolio_snapshots.json.gz).
If the legacy plain-JSON file exists and the .gz does not, it is migrated
automatically on first load.

Usage:
    from data_store import PortfolioDataStore

    store = PortfolioDataStore()

    # query latest snapshot
    snapshot = store.latest()

    # get all data for a ticker
    data = store.ticker_data("AAPL")

    # equity timeline
    history = store.equity_history()

    # summary of all snapshots
    for entry in store.summary():
        print(entry["collected_at"], entry["equity"])
"""

import gzip
import json
import os
from datetime import datetime


class PortfolioDataStore:
    """Compressed, queryable store for portfolio data snapshots."""

    def __init__(self, path: str = "portfolio_snapshots.json.gz"):
        self.path = path
        # Legacy plain-JSON path for automatic migration
        self._legacy = path[:-3] if path.endswith(".gz") else None

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    def load_all(self) -> list:
        """Return all snapshots sorted oldest-first. Migrates legacy file if needed."""
        if os.path.exists(self.path):
            with gzip.open(self.path, "rt", encoding="utf-8") as f:
                snapshots = json.load(f)
        elif self._legacy and os.path.exists(self._legacy):
            with open(self._legacy, encoding="utf-8") as f:
                snapshots = json.load(f)
            # Migrate to compressed format
            self.save_all(snapshots)
            print(f"Migrated {self._legacy} → {self.path}")
        else:
            return []
        return sorted(snapshots, key=lambda s: s["timestamp_ms"])

    def save_all(self, snapshots: list) -> None:
        """Persist snapshot list to compressed file."""
        with gzip.open(self.path, "wt", encoding="utf-8") as f:
            json.dump(snapshots, f, indent=2)

    def append(self, snapshot: dict) -> int:
        """Append a snapshot and persist. Returns total snapshot count."""
        snapshots = self.load_all()
        snapshots.append(snapshot)
        self.save_all(snapshots)
        return len(snapshots)

    # ------------------------------------------------------------------
    # Queries — snapshot selection
    # ------------------------------------------------------------------

    def latest(self) -> dict | None:
        """Return the most recent snapshot by timestamp_ms."""
        snapshots = self.load_all()
        return max(snapshots, key=lambda s: s["timestamp_ms"]) if snapshots else None

    def by_timestamp(self, ts_ms: int) -> dict | None:
        """Return snapshot with exact timestamp_ms, or None."""
        for s in self.load_all():
            if s["timestamp_ms"] == ts_ms:
                return s
        return None

    def between(self, start_ms: int, end_ms: int) -> list:
        """Return snapshots in [start_ms, end_ms] inclusive, sorted oldest-first."""
        return [s for s in self.load_all() if start_ms <= s["timestamp_ms"] <= end_ms]

    def count(self) -> int:
        """Return total number of stored snapshots."""
        return len(self.load_all())

    # ------------------------------------------------------------------
    # Queries — ticker-level
    # ------------------------------------------------------------------

    def tickers(self, snapshot: dict = None) -> list:
        """Return list of tickers in a snapshot (defaults to latest)."""
        s = snapshot or self.latest()
        return list(s["portfolio_summary"]["holdings"].keys()) if s else []

    def ticker_data(self, ticker: str, snapshot: dict = None) -> dict:
        """
        Return all available data for one ticker from a snapshot.

        Keys: timestamp_ms, timestamp_iso, holdings, fundamental,
              technical, short_interest, dcf, insider, news.
        """
        s = snapshot or self.latest()
        if not s:
            return {}
        return {
            "timestamp_ms":    s["timestamp_ms"],
            "timestamp_iso":   s["timestamp_iso"],
            "holdings":        s["portfolio_summary"]["holdings"].get(ticker),
            "fundamental":     s["fundamental_data"].get(ticker),
            "technical":       s["technical_data"].get(ticker),
            "short_interest":  s["short_interest_data"].get(ticker),
            "dcf":             s["dcf_results"].get(ticker),
            "insider":         s["insider_data"].get(ticker),
            "news":            s["news_data"].get(ticker),
        }

    def ticker_history(self, ticker: str) -> list:
        """
        Return per-snapshot equity and price for a ticker across all snapshots.

        Each entry: {timestamp_ms, timestamp_iso, equity, shares, price}
        """
        result = []
        for s in self.load_all():
            h = s["portfolio_summary"]["holdings"].get(ticker)
            t = s["technical_data"].get(ticker, {})
            if h:
                result.append({
                    "timestamp_ms":  s["timestamp_ms"],
                    "timestamp_iso": s["timestamp_iso"],
                    "equity":        h.get("equity"),
                    "shares":        h.get("shares"),
                    "price":         t.get("current_price"),
                })
        return result

    # ------------------------------------------------------------------
    # Queries — portfolio-level
    # ------------------------------------------------------------------

    def equity_history(self) -> list:
        """
        Return a lightweight equity timeline across all snapshots.

        Each entry: {timestamp_ms, timestamp_iso, equity, cash}
        """
        return [
            {
                "timestamp_ms":  s["timestamp_ms"],
                "timestamp_iso": s["timestamp_iso"],
                "equity":        s["portfolio_summary"]["equity"],
                "cash":          s["portfolio_summary"]["cash"],
            }
            for s in self.load_all()
        ]

    def summary(self) -> list:
        """
        Return a lightweight summary of every snapshot.

        Each entry: {timestamp_ms, collected_at, equity, cash, tickers}
        """
        return [
            {
                "timestamp_ms": s["timestamp_ms"],
                "collected_at": s["timestamp_iso"],
                "equity":       s["portfolio_summary"]["equity"],
                "cash":         s["portfolio_summary"]["cash"],
                "tickers":      list(s["portfolio_summary"]["holdings"].keys()),
            }
            for s in self.load_all()
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n = self.count()
        latest = self.latest()
        ts = latest["timestamp_iso"] if latest else "—"
        return f"<PortfolioDataStore path={self.path!r} snapshots={n} latest={ts}>"
