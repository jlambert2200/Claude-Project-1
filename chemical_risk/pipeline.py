"""
End-to-end pipeline orchestrator.

Phase 1 (original): chemical risk scoring.
Phase 2 (new):      commercial positioning scoring.
Phase 3 (new):      combined score + unified explanations.

The primary public function is `analyze_suppliers(data)` which now returns
an `AnalysisResult` that includes:
  - scores          : list[SupplierScore]      (Phase 1, backward-compatible)
  - combined_scores : list[CombinedScore]      (Phase 1 + 2 merged, new)
  - dataframe       : pd.DataFrame             (one row per supplier, all scores)
  - graph           : SimilarityGraph
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .features import build_supplier_features
from .ingestion import load_suppliers_from_dicts, load_suppliers_from_json
from .network import SimilarityGraph, build_similarity_graph
from .positioning import analyze_positioning
from .scoring import score_supplier
from .schema import CombinedScore, Supplier, SupplierScore


# ---------------------------------------------------------------------------
# Combined-score weights
# ---------------------------------------------------------------------------
# combined_score = risk_score + POSITIONING_WEIGHT * positioning_score
# Capped at 100.
#
# At POSITIONING_WEIGHT = 0.35, a supplier with risk=0 and positioning=100
# gets combined = 35 (medium band), which is correct — the supplier has
# no chemical signal but is highly commercially permissive.
# A supplier with risk=60 (high) and positioning=100 gets combined = 95.

POSITIONING_WEIGHT = 0.35


def _combined_band(score: float) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _merge_score(
    supplier: Supplier,
    risk: SupplierScore,
    positioning_score: float,
    positioning_signals: dict[str, list[str]],
    positioning_explanations: list[str],
) -> CombinedScore:
    """Merge Phase-1 and Phase-2 results into a single CombinedScore."""
    combined = min(100.0, risk.risk_score + POSITIONING_WEIGHT * positioning_score)

    # Unified explanation: Phase-1 bullets first, then Phase-2.
    # We de-duplicate exact strings (can happen if both phases detect the
    # same keyword in different contexts).
    seen: set[str] = set()
    merged: list[str] = []
    for line in risk.explanations + positioning_explanations:
        if line not in seen:
            seen.add(line)
            merged.append(line)

    return CombinedScore(
        supplier_id=supplier.supplier_id,
        name=supplier.name,
        location=supplier.location,
        source_query=supplier.source_query,
        discovery_depth=supplier.discovery_depth,
        risk_score=round(risk.risk_score, 2),
        positioning_score=round(positioning_score, 2),
        combined_score=round(combined, 2),
        combined_band=_combined_band(combined),
        risk_contributions=risk.contributions,
        positioning_signals=positioning_signals,
        explanations=merged,
        matched_precursors=risk.matched_precursors,
    )


# ---------------------------------------------------------------------------
# AnalysisResult
# ---------------------------------------------------------------------------


@dataclass
class AnalysisResult:
    scores: list[SupplierScore]           # Phase-1 only (backward-compatible)
    combined_scores: list[CombinedScore]  # Phase-1 + Phase-2 (new)
    dataframe: pd.DataFrame
    graph: SimilarityGraph

    def to_json(self) -> dict[str, Any]:
        return {
            "suppliers": [s.as_dict() for s in self.combined_scores],
            "graph": {
                "nodes": self.graph.nodes,
                "edges": [e.__dict__ for e in self.graph.edges],
                "clusters": self.graph.clusters,
            },
        }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _coerce_to_suppliers(data: Any) -> list[Supplier]:
    if isinstance(data, (str, Path)):
        return load_suppliers_from_json(data)
    if isinstance(data, list):
        if not data:
            return []
        if isinstance(data[0], Supplier):
            return data  # type: ignore[return-value]
        if isinstance(data[0], dict):
            return load_suppliers_from_dicts(data)
    raise TypeError("analyze_suppliers expects a list of dicts/Suppliers or a path to JSON")


def score_one(supplier: Supplier) -> tuple[SupplierScore, CombinedScore]:
    """
    Score a single Supplier through both Phase-1 and Phase-2.
    Returns (SupplierScore, CombinedScore).
    Useful when the agent loop processes suppliers one-at-a-time.
    """
    features, _normalized, matched = build_supplier_features(supplier)
    risk = score_supplier(supplier, features, matched)

    pct_vague = float(features.get("pct_vague_names", 0.0))
    pos_result = analyze_positioning(supplier, pct_vague=pct_vague)

    combined = _merge_score(
        supplier,
        risk,
        pos_result.positioning_score,
        pos_result.signals,
        pos_result.explanation,
    )
    return risk, combined


def analyze_suppliers(data: Any, graph_threshold: float = 0.3) -> AnalysisResult:
    """Run the full pipeline end-to-end (Phase 1 + Phase 2)."""
    suppliers = _coerce_to_suppliers(data)

    scores: list[SupplierScore] = []
    combined_scores: list[CombinedScore] = []
    normalized_map: dict[str, list] = {}

    for supplier in suppliers:
        features, normalized, matched = build_supplier_features(supplier)
        normalized_map[supplier.supplier_id] = normalized

        risk = score_supplier(supplier, features, matched)
        scores.append(risk)

        pct_vague = float(features.get("pct_vague_names", 0.0))
        pos_result = analyze_positioning(supplier, pct_vague=pct_vague)

        combined = _merge_score(
            supplier,
            risk,
            pos_result.positioning_score,
            pos_result.signals,
            pos_result.explanation,
        )
        combined_scores.append(combined)

    # DataFrame: one row per supplier, all scores.
    rows = []
    cs_by_id = {cs.supplier_id: cs for cs in combined_scores}
    for s in scores:
        cs = cs_by_id[s.supplier_id]
        row = {
            "supplier_id": s.supplier_id,
            "name": s.name,
            "risk_score": s.risk_score,
            "positioning_score": cs.positioning_score,
            "combined_score": cs.combined_score,
            "combined_band": cs.combined_band,
            "discovery_depth": cs.discovery_depth,
            "source_query": cs.source_query,
            **s.features,
        }
        rows.append(row)

    dataframe = (
        pd.DataFrame(rows)
        .sort_values("combined_score", ascending=False)
        .reset_index(drop=True)
    )

    graph = build_similarity_graph(suppliers, normalized_map, threshold=graph_threshold)

    return AnalysisResult(
        scores=scores,
        combined_scores=combined_scores,
        dataframe=dataframe,
        graph=graph,
    )
