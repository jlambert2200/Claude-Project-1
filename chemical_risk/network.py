"""
Supplier similarity graph.

Builds a graph where:
  - nodes are suppliers
  - edges connect suppliers whose product sets overlap (Jaccard similarity
    above a threshold)

This is useful for spotting clusters — e.g. a set of suppliers that
advertise the same unusual combination of monitored precursors, which
may indicate coordinated storefronts or catalog copying.

The module uses only pandas + stdlib for the core, and optionally
networkx if installed (for connected-component clustering).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .schema import Supplier


@dataclass
class Edge:
    source: str
    target: str
    jaccard: float
    shared: list[str]


@dataclass
class SimilarityGraph:
    nodes: list[str]  # supplier_ids
    edges: list[Edge]
    clusters: list[list[str]]  # list of supplier_id groups


def _product_set(supplier: Supplier, normalized_map: dict[str, list]) -> set[str]:
    """
    Represent a supplier as the set of canonical chemical names it lists.
    Falls back to raw product names when no canonical match was possible.
    """
    names: set[str] = set()
    for np in normalized_map.get(supplier.supplier_id, []):
        if np.canonical_name:
            names.add(np.canonical_name.lower())
        else:
            # keep raw name so two suppliers with identical "intermediate"
            # stubs still register as similar
            raw = (np.raw_name or "").lower().strip()
            if raw:
                names.add(raw)
    return names


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def _connected_components(nodes: list[str], edges: list[Edge]) -> list[list[str]]:
    """Simple union-find over edges above threshold."""
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in edges:
        union(e.source, e.target)

    groups: dict[str, list[str]] = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    # Only return groups with more than one member (singletons aren't clusters).
    return [sorted(g) for g in groups.values() if len(g) > 1]


def build_similarity_graph(
    suppliers: list[Supplier],
    normalized_map: dict[str, list],
    threshold: float = 0.3,
) -> SimilarityGraph:
    """
    Build a similarity graph from normalized supplier catalogs.

    `normalized_map` maps supplier_id -> list[NormalizedProduct]
    (populated by the pipeline).
    """
    sets = {s.supplier_id: _product_set(s, normalized_map) for s in suppliers}
    nodes = [s.supplier_id for s in suppliers]
    edges: list[Edge] = []

    for a, b in combinations(nodes, 2):
        sa, sb = sets[a], sets[b]
        score = _jaccard(sa, sb)
        if score >= threshold:
            edges.append(
                Edge(
                    source=a,
                    target=b,
                    jaccard=round(score, 3),
                    shared=sorted(sa & sb),
                )
            )

    clusters = _connected_components(nodes, edges)
    return SimilarityGraph(nodes=nodes, edges=edges, clusters=clusters)
