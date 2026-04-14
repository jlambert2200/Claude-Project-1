"""
Data Persistence Layer.

Stores suppliers, their scores, and discovery metadata in a SQLite
database so the iterative discovery loop can:
  - resume across sessions without re-processing known suppliers
  - track which suppliers were added by which query / iteration
  - serve as an audit trail for compliance analysts

Schema
------
suppliers  : one row per supplier, JSON blob for the full record.
scores     : one row per scoring event (a supplier can be re-scored).

SQLite is used because it requires zero infrastructure and produces a
single portable file. In production this could be swapped for Postgres
by changing the connection string.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import CombinedScore, Supplier


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_SUPPLIERS = """
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    location        TEXT,
    source_query    TEXT,
    discovery_depth INTEGER DEFAULT 0,
    data_json       TEXT NOT NULL,       -- full Supplier.as_dict() JSON
    first_seen_at   TEXT NOT NULL,       -- ISO-8601 UTC
    last_scored_at  TEXT                 -- NULL until first scoring
)
"""

_CREATE_SCORES = """
CREATE TABLE IF NOT EXISTS scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id     TEXT NOT NULL,
    risk_score      REAL,
    positioning_score REAL,
    combined_score  REAL,
    combined_band   TEXT,
    score_json      TEXT NOT NULL,       -- full CombinedScore.as_dict() JSON
    scored_at       TEXT NOT NULL        -- ISO-8601 UTC
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Store class
# ---------------------------------------------------------------------------


class SupplierStore:
    """
    Simple SQLite-backed store for suppliers and their scores.

    Usage:
        store = SupplierStore("chemical_risk.db")
        store.save_supplier(supplier)
        store.save_score(combined_score)
        new = store.get_unscored_suppliers()
    """

    def __init__(self, db_path: str | Path = ":memory:"):
        self._path = str(db_path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()

    def _bootstrap(self) -> None:
        with self._conn:
            self._conn.execute(_CREATE_SUPPLIERS)
            self._conn.execute(_CREATE_SCORES)

    # --- Suppliers -----------------------------------------------------------

    def save_supplier(self, supplier: Supplier) -> bool:
        """
        Insert a supplier. If the supplier_id already exists, skip.
        Returns True if a new row was inserted, False if it already existed.
        """
        existing = self._conn.execute(
            "SELECT supplier_id FROM suppliers WHERE supplier_id = ?",
            (supplier.supplier_id,),
        ).fetchone()
        if existing:
            return False
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO suppliers
                    (supplier_id, name, location, source_query, discovery_depth,
                     data_json, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    supplier.supplier_id,
                    supplier.name,
                    supplier.location,
                    supplier.source_query,
                    supplier.discovery_depth,
                    json.dumps(supplier.as_dict()),
                    _now(),
                ),
            )
        return True

    def has_supplier(self, supplier_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM suppliers WHERE supplier_id = ?", (supplier_id,)
        ).fetchone()
        return row is not None

    def get_all_suppliers(self) -> list[Supplier]:
        rows = self._conn.execute(
            "SELECT data_json FROM suppliers ORDER BY first_seen_at"
        ).fetchall()
        return [Supplier.from_dict(json.loads(r["data_json"])) for r in rows]

    def get_unscored_suppliers(self) -> list[Supplier]:
        """Return suppliers that have not yet been scored in this session."""
        rows = self._conn.execute(
            "SELECT data_json FROM suppliers WHERE last_scored_at IS NULL ORDER BY first_seen_at"
        ).fetchall()
        return [Supplier.from_dict(json.loads(r["data_json"])) for r in rows]

    def get_new_suppliers(self, since: str | None = None) -> list[Supplier]:
        """
        Return suppliers added after `since` (ISO-8601 UTC string).
        If `since` is None, returns all suppliers.
        """
        if since is None:
            return self.get_all_suppliers()
        rows = self._conn.execute(
            "SELECT data_json FROM suppliers WHERE first_seen_at > ? ORDER BY first_seen_at",
            (since,),
        ).fetchall()
        return [Supplier.from_dict(json.loads(r["data_json"])) for r in rows]

    def known_ids(self) -> set[str]:
        rows = self._conn.execute("SELECT supplier_id FROM suppliers").fetchall()
        return {r["supplier_id"] for r in rows}

    # --- Scores --------------------------------------------------------------

    def save_score(self, score: CombinedScore) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO scores
                    (supplier_id, risk_score, positioning_score,
                     combined_score, combined_band, score_json, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score.supplier_id,
                    score.risk_score,
                    score.positioning_score,
                    score.combined_score,
                    score.combined_band,
                    json.dumps(score.as_dict()),
                    _now(),
                ),
            )
            # Mark the supplier row as scored.
            self._conn.execute(
                "UPDATE suppliers SET last_scored_at = ? WHERE supplier_id = ?",
                (_now(), score.supplier_id),
            )

    def get_scores(
        self,
        supplier_id: str | None = None,
        min_combined: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve score records, optionally filtered by supplier_id or a
        minimum combined score.
        """
        query = "SELECT score_json FROM scores WHERE 1=1"
        params: list[Any] = []
        if supplier_id is not None:
            query += " AND supplier_id = ?"
            params.append(supplier_id)
        if min_combined is not None:
            query += " AND combined_score >= ?"
            params.append(min_combined)
        query += " ORDER BY scored_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [json.loads(r["score_json"]) for r in rows]

    def get_latest_score(self, supplier_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT score_json FROM scores WHERE supplier_id = ? ORDER BY scored_at DESC LIMIT 1",
            (supplier_id,),
        ).fetchone()
        return json.loads(row["score_json"]) if row else None

    def update_supplier(self, supplier: Supplier) -> None:
        """Overwrite the data_json for an existing supplier (e.g. after re-scraping)."""
        with self._conn:
            self._conn.execute(
                "UPDATE suppliers SET data_json = ?, name = ?, location = ? WHERE supplier_id = ?",
                (
                    json.dumps(supplier.as_dict()),
                    supplier.name,
                    supplier.location,
                    supplier.supplier_id,
                ),
            )

    # --- Convenience --------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a quick statistics snapshot."""
        n_suppliers = self._conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
        n_scored = self._conn.execute(
            "SELECT COUNT(DISTINCT supplier_id) FROM scores"
        ).fetchone()[0]
        bands = self._conn.execute(
            "SELECT combined_band, COUNT(*) as n FROM scores GROUP BY combined_band"
        ).fetchall()
        return {
            "total_suppliers": n_suppliers,
            "scored_suppliers": n_scored,
            "band_counts": {r["combined_band"]: r["n"] for r in bands},
        }

    def close(self) -> None:
        self._conn.close()
