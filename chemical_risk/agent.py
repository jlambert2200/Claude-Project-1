"""
Semi-autonomous discovery agent.

`run_discovery_cycle` is the top-level entry point. It:

  1. Starts with user-provided seed queries.
  2. Calls the discovery module to find candidate suppliers.
  3. Runs each new supplier through the full pipeline (Phase 1 + 2).
  4. Persists everything to the SupplierStore.
  5. Generates expansion queries from high-scoring results.
  6. Repeats for `iterations` rounds, growing the supplier graph with
     each pass.
  7. Returns a DiscoveryReport with per-iteration logs.

ANALYST CONTROLS
----------------
  iterations          : How many discovery rounds to run (default 3).
  risk_threshold      : Combined score above which a supplier is flagged
                        for expansion query generation (default 30).
  positioning_threshold: Positioning score above which a supplier's
                         commercial posture is flagged in the report.
  max_new_per_iter    : Upper bound on new suppliers ingested per iteration.
  graph_threshold     : Jaccard threshold for the similarity graph.
  db_path             : Path for the SQLite store (":memory:" for in-session).
  verbose             : Print progress to stdout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .discovery import discover_suppliers, generate_expansion_queries
from .pipeline import score_one
from .schema import CombinedScore, Supplier
from .storage import SupplierStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class IterationLog:
    iteration: int
    queries_used: list[str]
    suppliers_found: int          # raw count from discovery
    suppliers_new: int            # after deduplication against store
    suppliers_scored: int
    high_band: int                # combined_band == "high"
    medium_band: int              # combined_band == "medium"
    new_queries_generated: list[str]
    top_findings: list[dict[str, Any]]  # top-3 by combined_score


@dataclass
class DiscoveryReport:
    seed_queries: list[str]
    iterations_run: int
    iteration_logs: list[IterationLog]
    all_combined_scores: list[CombinedScore]
    store_summary: dict[str, Any]

    def top_suppliers(self, n: int = 10, min_band: str = "medium") -> list[CombinedScore]:
        """Return the top-N suppliers by combined_score, filtered by band."""
        band_order = {"low": 0, "medium": 1, "high": 2}
        threshold = band_order.get(min_band, 0)
        filtered = [
            cs for cs in self.all_combined_scores
            if band_order.get(cs.combined_band, 0) >= threshold
        ]
        return sorted(filtered, key=lambda x: x.combined_score, reverse=True)[:n]

    def print_summary(self) -> None:
        print(f"\n{'='*60}")
        print(f"Discovery complete — {self.iterations_run} iteration(s)")
        print(f"{'='*60}")
        for log in self.iteration_logs:
            print(
                f"\nIter {log.iteration}: {len(log.queries_used)} queries → "
                f"{log.suppliers_new} new suppliers scored "
                f"(high={log.high_band}, medium={log.medium_band})"
            )
            for t in log.top_findings:
                print(
                    f"  [{t['band'].upper():6}] {t['combined']:.1f} "
                    f"(risk={t['risk']:.1f}, pos={t['pos']:.1f})  {t['name']}"
                )
            if log.new_queries_generated:
                print(f"  Expansion queries: {log.new_queries_generated}")

        print(f"\nStore summary: {self.store_summary}")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------


def run_discovery_cycle(
    seed_queries: list[str],
    *,
    iterations: int = 3,
    risk_threshold: float = 30.0,
    positioning_threshold: float = 30.0,
    max_new_per_iter: int = 8,
    graph_threshold: float = 0.3,
    db_path: str = ":memory:",
    verbose: bool = True,
) -> DiscoveryReport:
    """
    Run the iterative supplier discovery cycle.

    Parameters
    ----------
    seed_queries          : Starting search strings.
    iterations            : Number of expansion rounds.
    risk_threshold        : Minimum combined_score to use a supplier as an
                            expansion seed (default 30).
    positioning_threshold : Minimum positioning_score worth flagging in logs.
    max_new_per_iter      : Cap on new suppliers per iteration (avoids
                            runaway expansion on large mock indexes).
    graph_threshold       : Jaccard threshold for similarity edges.
    db_path               : SQLite path or ":memory:".
    verbose               : Print per-iteration progress.
    """
    store = SupplierStore(db_path)
    all_combined: list[CombinedScore] = []
    current_queries = list(seed_queries)
    iteration_logs: list[IterationLog] = []

    for iteration in range(1, iterations + 1):
        if verbose:
            print(f"\n[Iter {iteration}/{iterations}] Queries: {current_queries}")

        # ── Step 1: Discover candidates ────────────────────────────────────
        discovered: list[Supplier] = discover_suppliers(
            current_queries,
            depth=iteration,
            max_per_query=max_new_per_iter,
            already_seen=store.known_ids(),
        )
        n_found = len(discovered)

        # ── Step 2: Deduplicate against store, persist new ─────────────────
        new_suppliers: list[Supplier] = []
        for supplier in discovered:
            if store.save_supplier(supplier):    # returns True for inserts
                new_suppliers.append(supplier)

        n_new = len(new_suppliers)
        if verbose:
            print(f"  Found {n_found}, {n_new} new after deduplication.")

        if not new_suppliers:
            if verbose:
                print("  Nothing new — stopping early.")
            break

        # Cap to avoid scoring explosion in large mock runs
        new_suppliers = new_suppliers[:max_new_per_iter]

        # ── Step 3: Score every new supplier ──────────────────────────────
        iter_combined: list[CombinedScore] = []
        for supplier in new_suppliers:
            _risk, combined = score_one(supplier)
            store.save_score(combined)
            iter_combined.append(combined)
            all_combined.append(combined)

        n_high = sum(1 for cs in iter_combined if cs.combined_band == "high")
        n_med  = sum(1 for cs in iter_combined if cs.combined_band == "medium")

        if verbose:
            for cs in sorted(iter_combined, key=lambda x: x.combined_score, reverse=True)[:5]:
                print(
                    f"  [{cs.combined_band.upper():6}] {cs.combined_score:.1f} "
                    f"(risk={cs.risk_score:.1f}, pos={cs.positioning_score:.1f})  {cs.name}"
                )

        # ── Step 4: Generate expansion queries ────────────────────────────
        expansion_queries: list[str] = []
        for cs in iter_combined:
            if cs.combined_score >= risk_threshold:
                # Extract canonical names from matched precursors list
                chem_names = list({m["canonical_name"] for m in cs.matched_precursors})
                supplier_obj = next(
                    (s for s in new_suppliers if s.supplier_id == cs.supplier_id),
                    None,
                )
                if supplier_obj:
                    new_qs = generate_expansion_queries(
                        supplier_obj,
                        cs.combined_score,
                        chem_names,
                        max_queries=3,
                    )
                    for q in new_qs:
                        if q not in expansion_queries and q not in current_queries:
                            expansion_queries.append(q)

        # Top-3 findings for the log (lightweight dicts)
        top3 = [
            {
                "supplier_id": cs.supplier_id,
                "name": cs.name,
                "risk": cs.risk_score,
                "pos": cs.positioning_score,
                "combined": cs.combined_score,
                "band": cs.combined_band,
            }
            for cs in sorted(iter_combined, key=lambda x: x.combined_score, reverse=True)[:3]
        ]

        iteration_logs.append(
            IterationLog(
                iteration=iteration,
                queries_used=current_queries,
                suppliers_found=n_found,
                suppliers_new=n_new,
                suppliers_scored=len(iter_combined),
                high_band=n_high,
                medium_band=n_med,
                new_queries_generated=expansion_queries,
                top_findings=top3,
            )
        )

        # ── Step 5: Prepare next round ────────────────────────────────────
        if not expansion_queries:
            if verbose:
                print("  No expansion queries generated — stopping early.")
            break
        current_queries = expansion_queries

    report = DiscoveryReport(
        seed_queries=seed_queries,
        iterations_run=len(iteration_logs),
        iteration_logs=iteration_logs,
        all_combined_scores=all_combined,
        store_summary=store.summary(),
    )

    store.close()
    return report
