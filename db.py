"""
TinyDB-backed document store for the portfolio analyzer.

Storage layout:
  portfolio_db.json          — TinyDB (metadata, links, small fields)
  data/snapshots/<ts>.json   — full snapshot JSON (market data, holdings, etc.)
  data/analyses/<ts>.json    — full analysis JSON (all Claude sections)

Tables (TinyDB "tables"):
  users      — one row per user; extensible for multi-user later
  snapshots  — metadata + file_path link per --data run
  analyses   — Claude output metadata + file_path link per --analysis run
  history    — lightweight equity timeline for historical comparison
"""

import base64
import json
import os
from datetime import datetime
from pathlib import Path

from tinydb import Query, TinyDB
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

DB_FILE   = "portfolio_db.json"
DATA_DIR  = Path("data")
SNAP_DIR  = DATA_DIR / "snapshots"
ANAL_DIR  = DATA_DIR / "analyses"

_INPUT_CPT  = 3.00  / 1_000_000
_OUTPUT_CPT = 15.00 / 1_000_000

DEFAULT_USERNAME       = "naeem"
DEFAULT_SPENDING_LIMIT = 50.0   # USD lifetime limit per user (editable in DB)


class PortfolioDB:
    def __init__(self, db_file: str = DB_FILE, username: str = DEFAULT_USERNAME):
        # Ensure data directories exist
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        ANAL_DIR.mkdir(parents=True, exist_ok=True)

        self._db = TinyDB(db_file, storage=CachingMiddleware(JSONStorage), indent=2)
        self.users     = self._db.table("users")
        self.snapshots = self._db.table("snapshots")
        self.analyses  = self._db.table("analyses")
        self.history   = self._db.table("history")

        self._username = username
        self._user_id  = self._get_or_create_user(username)

    def close(self):
        self._db.close()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def _get_or_create_user(self, username: str) -> int:
        U = Query()
        row = self.users.get(U.username == username)
        if row:
            return row.doc_id
        return self.users.insert({
            "username":           username,
            "created_at":         datetime.now().isoformat(),
            "spending_limit_usd": DEFAULT_SPENDING_LIMIT,
            # Broker credentials — stored locally only, never committed to git
            "rh_username":        None,
            "rh_password":        None,
            "anthropic_api_key":  None,
            # Robinhood session token (base64-encoded Python pickle bytes)
            "rh_pickle_b64":      None,
            "rh_pickle_saved_at": None,
        })

    def set_credentials(
        self,
        rh_username: str = None,
        rh_password: str = None,
        anthropic_api_key: str = None,
    ) -> None:
        """Store broker/API credentials for the current user in the local DB."""
        updates = {}
        if rh_username        is not None: updates["rh_username"]        = rh_username
        if rh_password        is not None: updates["rh_password"]        = rh_password
        if anthropic_api_key  is not None: updates["anthropic_api_key"]  = anthropic_api_key
        if updates:
            self.users.update(updates, doc_ids=[self.user_id])

    def get_credentials(self) -> dict:
        """Return stored credentials for the current user."""
        row = self.users.get(doc_id=self.user_id) or {}
        return {
            "rh_username":       row.get("rh_username"),
            "rh_password":       row.get("rh_password"),
            "anthropic_api_key": row.get("anthropic_api_key"),
        }

    # ------------------------------------------------------------------
    # Robinhood session token (pickle)
    # ------------------------------------------------------------------

    def save_rh_pickle(self, pickle_bytes: bytes) -> None:
        """Store the robin_stocks session pickle (binary) as base64 in the DB."""
        b64 = base64.b64encode(pickle_bytes).decode("ascii")
        self.users.update(
            {"rh_pickle_b64": b64, "rh_pickle_saved_at": datetime.now().isoformat()},
            doc_ids=[self.user_id],
        )

    def get_rh_pickle_bytes(self) -> bytes | None:
        """Return the stored robin_stocks session pickle bytes, or None if not saved."""
        row = self.users.get(doc_id=self.user_id) or {}
        b64 = row.get("rh_pickle_b64")
        if not b64:
            return None
        return base64.b64decode(b64)

    def get_user(self, username: str) -> dict | None:
        U = Query()
        return self.users.get(U.username == username)

    def list_users(self) -> list[dict]:
        return self.users.all()

    def user_spending(self) -> dict:
        """Return total spent, limit, and remaining budget for the current user."""
        A = Query()
        rows = self.analyses.search(A.user_id == self.user_id)
        spent = sum(r.get("cost_usd", 0) or 0 for r in rows)
        user_row = self.users.get(doc_id=self.user_id) or {}
        limit = user_row.get("spending_limit_usd", DEFAULT_SPENDING_LIMIT)
        return {
            "total_spent_usd": round(spent, 4),
            "spending_limit_usd": limit,
            "remaining_usd": round(limit - spent, 4),
        }

    def set_spending_limit(self, limit_usd: float) -> None:
        """Update the spending limit for the current user."""
        self.users.update({"spending_limit_usd": limit_usd}, doc_ids=[self.user_id])

    @property
    def user_id(self) -> int:
        return self._user_id

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: dict) -> int:
        """
        Write full snapshot to data/snapshots/<ts>.json.
        Insert metadata + file path into snapshots table.
        Returns TinyDB document id.
        """
        ts  = snapshot["timestamp_ms"]
        ps  = snapshot["portfolio_summary"]
        iso = snapshot["timestamp_iso"]

        file_path = str(SNAP_DIR / f"{iso[:10]}_{ts}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)

        doc_id = self.snapshots.insert({
            "user_id":      self.user_id,
            "timestamp_ms": ts,
            "timestamp_iso": iso,
            "equity":       ps["equity"],
            "cash":         ps["cash"],
            "tickers":      sorted(ps["holdings"].keys()),
            "file_path":    file_path,
        })
        return doc_id

    def load_snapshot(self, doc_id: int) -> dict | None:
        """Load full snapshot from file given its TinyDB doc id."""
        row = self.snapshots.get(doc_id=doc_id)
        if not row:
            return None
        with open(row["file_path"], encoding="utf-8") as f:
            return json.load(f)

    def latest_snapshot(self) -> tuple[dict | None, int | None]:
        """Returns (snapshot_dict, doc_id) for the most recent snapshot."""
        rows = self.snapshots.all()
        if not rows:
            return None, None
        latest = max(rows, key=lambda r: r["timestamp_ms"])
        with open(latest["file_path"], encoding="utf-8") as f:
            return json.load(f), latest.doc_id

    def snapshot_count(self) -> int:
        return len(self.snapshots)

    # ------------------------------------------------------------------
    # Analyses
    # ------------------------------------------------------------------

    def save_analysis(
        self,
        snapshot_doc_id: int,
        analyses: dict,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> int:
        """
        Write full analysis sections to data/analyses/<ts>.json.
        Insert metadata + file path into analyses table.
        Returns TinyDB document id.
        """
        snap_row = self.snapshots.get(doc_id=snapshot_doc_id)
        ts  = snap_row["timestamp_ms"] if snap_row else int(datetime.now().timestamp() * 1000)
        iso = snap_row["timestamp_iso"] if snap_row else datetime.now().isoformat()

        cost = round(input_tokens * _INPUT_CPT + output_tokens * _OUTPUT_CPT, 6)

        file_path = str(ANAL_DIR / f"{iso[:10]}_{ts}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(analyses, f, indent=2)

        doc_id = self.analyses.insert({
            "user_id":       self.user_id,
            "snapshot_id":   snapshot_doc_id,
            "timestamp_iso": datetime.now().isoformat(),
            "final_summary": analyses.get("final_summary", ""),
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "cost_usd":      cost,
            "file_path":     file_path,
        })
        return doc_id

    def load_analysis(self, doc_id: int) -> dict | None:
        """Load full analysis from file given its TinyDB doc id."""
        row = self.analyses.get(doc_id=doc_id)
        if not row:
            return None
        with open(row["file_path"], encoding="utf-8") as f:
            return json.load(f)

    def latest_analysis(self) -> dict | None:
        """Returns full analysis dict for the most recent analysis run."""
        rows = self.analyses.all()
        if not rows:
            return None
        latest = max(rows, key=lambda r: r["timestamp_iso"])
        with open(latest["file_path"], encoding="utf-8") as f:
            return json.load(f)

    def analyses_for_snapshot(self, snapshot_doc_id: int) -> list[dict]:
        A = Query()
        rows = self.analyses.search(A.snapshot_id == snapshot_doc_id)
        result = []
        for row in sorted(rows, key=lambda r: r["timestamp_iso"]):
            with open(row["file_path"], encoding="utf-8") as f:
                result.append(json.load(f))
        return result

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def save_history_entry(self, snapshot_doc_id: int, current_run: dict) -> int:
        return self.history.insert({
            "user_id":     self.user_id,
            "snapshot_id": snapshot_doc_id,
            "date":        current_run["date"],
            "equity":      current_run["equity"],
            "cash":        current_run["cash"],
            "holdings":    current_run["holdings"],
        })

    def get_history(self) -> list[dict]:
        rows = self.history.search(Query().user_id == self.user_id)
        return sorted(rows, key=lambda r: r["date"])

    def previous_run(self) -> dict | None:
        history = self.get_history()
        return history[-1] if history else None

    # ------------------------------------------------------------------
    # Summary / reporting helpers
    # ------------------------------------------------------------------

    def snapshot_summary(self) -> list[dict]:
        """Metadata for all snapshots with their latest analysis summary."""
        A = Query()
        rows = self.snapshots.all()
        result = []
        for snap in sorted(rows, key=lambda r: r["timestamp_ms"]):
            anal_rows = self.analyses.search(A.snapshot_id == snap.doc_id)
            latest_anal = (
                max(anal_rows, key=lambda r: r["timestamp_iso"])
                if anal_rows else {}
            )
            result.append({
                "snapshot_id":   snap.doc_id,
                "timestamp_iso": snap["timestamp_iso"],
                "equity":        snap["equity"],
                "cash":          snap["cash"],
                "tickers":       snap["tickers"],
                "snapshot_file": snap["file_path"],
                "analysis_file": latest_anal.get("file_path"),
                "final_summary": latest_anal.get("final_summary"),
                "cost_usd":      latest_anal.get("cost_usd"),
            })
        return result

    # ------------------------------------------------------------------
    # Migration from legacy files
    # ------------------------------------------------------------------

    def migrate_from_gzip(self, gz_path: str) -> int:
        """Import snapshots from portfolio_snapshots.json.gz. Returns count imported."""
        import gzip
        if not os.path.exists(gz_path):
            return 0
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            snapshots = json.load(f)
        Q = Query()
        imported = 0
        for snap in snapshots:
            if self.snapshots.get(Q.timestamp_ms == snap["timestamp_ms"]):
                continue
            self.save_snapshot(snap)
            imported += 1
        return imported

    def migrate_from_history_json(self, json_path: str) -> int:
        """Import portfolio_history.json entries. Returns count imported."""
        if not os.path.exists(json_path):
            return 0
        with open(json_path, encoding="utf-8") as f:
            entries = json.load(f)
        Q = Query()
        imported = 0
        for entry in entries:
            if self.history.get(Q.date == entry["date"]):
                continue
            self.history.insert({
                "user_id":     self.user_id,
                "snapshot_id": None,
                "date":        entry["date"],
                "equity":      entry["equity"],
                "cash":        entry["cash"],
                "holdings":    entry.get("holdings", {}),
            })
            imported += 1
        return imported

    def __repr__(self) -> str:
        return (
            f"<PortfolioDB file={DB_FILE!r} "
            f"snapshots={self.snapshot_count()} "
            f"analyses={len(self.analyses)}>"
        )
