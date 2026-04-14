"""
End-to-end pipeline orchestrator.

The primary public function is `analyze_suppliers(data)` which accepts:
    - list[dict]   : already-parsed supplier records
    - list[Supplier]: dataclasses
    - str / Path   : path to a JSON file on disk

and returns a single `AnalysisResult` bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .features import build_supplier_features
from .ingestion import load_suppliers_from_dicts, load_suppliers_from_json
from .network import SimilarityGraph, build_similarity_graph
from .scoring import score_supplier
from .schema import Supplier, SupplierScore


@dataclass
class AnalysisResult:
    scores: list[SupplierScore]
    dataframe: pd.DataFrame
    graph: SimilarityGraph

    # Convenience
    def to_json(self) -> dict[str, Any]:
        return {
            "suppliers": [s.as_dict() for s in self.scores],
            "graph": {
                "nodes": self.graph.nodes,
                "edges": [e.__dict__ for e in self.graph.edges],
                "clusters": self.graph.clusters,
            },
        }


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


def analyze_suppliers(data: Any, graph_threshold: float = 0.3) -> AnalysisResult:
    """Run the full pipeline end-to-end."""
    suppliers = _coerce_to_suppliers(data)

    scores: list[SupplierScore] = []
    normalized_map: dict[str, list] = {}

    for supplier in suppliers:
        features, normalized, matched = build_supplier_features(supplier)
        normalized_map[supplier.supplier_id] = normalized
        scores.append(score_supplier(supplier, features, matched))

    # Flat dataframe view (one row per supplier)
    rows = []
    for s in scores:
        row = {
            "supplier_id": s.supplier_id,
            "name": s.name,
            "risk_score": s.risk_score,
            "risk_band": s.risk_band,
            **s.features,
        }
        rows.append(row)
    dataframe = pd.DataFrame(rows).sort_values("risk_score", ascending=False).reset_index(drop=True)

    graph = build_similarity_graph(suppliers, normalized_map, threshold=graph_threshold)

    return AnalysisResult(scores=scores, dataframe=dataframe, graph=graph)
