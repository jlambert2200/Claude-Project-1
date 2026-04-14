"""
Discovery Agent.

Finds new supplier candidates given a set of seed queries, and then
generates follow-on (expansion) queries from what it finds.

Two modes:
  1. Mock mode (default): searches the bundled mock_search_index.json.
     This lets the pipeline run with zero external dependencies and is
     enough for a realistic prototype.

  2. HTTP mode (opt-in): calls a user-supplied SearchBackend that
     returns raw text/HTML snippets. The agent parses those with the
     same ingestion adapters used for manual data.

Both modes return a list of Supplier dataclass objects so the rest of
the pipeline is mode-agnostic.

EXPANSION QUERY GENERATION
---------------------------
After scoring a batch of newly discovered suppliers, the agent distills
follow-on queries by:
  a. Pulling canonical chemical names from high-scoring supplier catalogs.
  b. Pulling distinctive commercial language tokens (e.g. "custom synthesis").
  c. Combining them into "<chemical> supplier" / "<chemical> bulk" style
     search phrases.

This drives the iterative expansion loop in agent.py.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Protocol

from .schema import Product, Supplier

# ---------------------------------------------------------------------------
# Mock search index
# ---------------------------------------------------------------------------

_INDEX_PATH = Path(__file__).parent / "data" / "mock_search_index.json"


def _load_index() -> list[dict]:
    data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    return data["entries"]


# Tokenize a query into individual lowercase words.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _score_entry(query_tokens: set[str], entry_keywords: list[str]) -> float:
    """
    Simple overlap score: fraction of query tokens that appear in the
    combined keyword string for this index entry.
    A score > 0 means the entry is a candidate result.
    """
    kw_tokens = _tokenize(" ".join(entry_keywords))
    overlap = query_tokens & kw_tokens
    return len(overlap) / max(len(query_tokens), 1)


# ---------------------------------------------------------------------------
# Search backend protocol (for real HTTP / API integration)
# ---------------------------------------------------------------------------


class SearchBackend(Protocol):
    """
    Minimal interface a real search adapter must implement.
    Not used in mock mode.
    """

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Return a list of dicts, each matching the Supplier.from_dict schema.
        """
        ...


# ---------------------------------------------------------------------------
# Expansion query generation
# ---------------------------------------------------------------------------

# Token pairs that, when found in a catalog, suggest useful follow-on queries.
_EXPANSION_TEMPLATES: tuple[str, ...] = (
    "{chemical} supplier china",
    "{chemical} bulk supplier",
    "{chemical} export manufacturer",
    "custom synthesis {chemical}",
    "{chemical} intermediates",
)

# Minimum combined score (risk + positioning combined) for a supplier to be
# used as a seed for expansion queries.
_EXPANSION_SCORE_THRESHOLD = 30.0

# Commercial language cues that, if present in a supplier listing, are worth
# using as explicit query terms in the next round.
_EXPANSION_LANGUAGE_CUES: tuple[str, ...] = (
    "custom synthesis",
    "research chemicals",
    "intermediates",
    "no documentation",
    "any destination",
    "stealth",
    "flexible arrangement",
    "special requests",
)


def generate_expansion_queries(
    supplier: Supplier,
    combined_score: float,
    canonical_names: list[str],
    max_queries: int = 4,
) -> list[str]:
    """
    Derive follow-on search queries from a supplier that scored above
    threshold. Returns up to `max_queries` new query strings.

    `canonical_names` should be the list of canonical chemical names matched
    from this supplier (already computed by the pipeline).
    """
    if combined_score < _EXPANSION_SCORE_THRESHOLD:
        return []

    queries: list[str] = []
    all_text = " ".join(filter(None, [
        supplier.about_text, supplier.payment_terms, supplier.shipping_terms,
        " ".join(p.name or "" for p in supplier.products),
    ])).lower()

    # Chemical-based expansion
    for name in canonical_names[:3]:  # limit to top 3 to avoid query explosion
        for template in _EXPANSION_TEMPLATES[:2]:
            queries.append(template.format(chemical=name))
            if len(queries) >= max_queries:
                return queries[:max_queries]

    # Language-cue expansion
    for cue in _EXPANSION_LANGUAGE_CUES:
        if cue in all_text and len(queries) < max_queries:
            queries.append(f"{cue} china supplier")

    return queries[:max_queries]


# ---------------------------------------------------------------------------
# Main discovery function
# ---------------------------------------------------------------------------


def discover_suppliers(
    seed_queries: list[str],
    *,
    depth: int = 0,
    max_per_query: int = 5,
    already_seen: set[str] | None = None,
    backend: SearchBackend | None = None,
) -> list[Supplier]:
    """
    Given seed search queries, return a deduplicated list of Supplier
    objects that match at least one query token.

    Parameters
    ----------
    seed_queries   : List of search strings (e.g. "acetic anhydride bulk china").
    depth          : Discovery depth to tag on returned Supplier objects.
    max_per_query  : Upper bound on results per query in mock mode.
    already_seen   : Set of supplier_ids already in the store (skipped).
    backend        : Optional real HTTP search adapter; uses mock if None.
    """
    if already_seen is None:
        already_seen = set()

    if backend is not None:
        return _discover_via_backend(seed_queries, depth, max_per_query, already_seen, backend)

    return _discover_via_mock(seed_queries, depth, max_per_query, already_seen)


def _discover_via_mock(
    queries: list[str],
    depth: int,
    max_per_query: int,
    already_seen: set[str],
) -> list[Supplier]:
    """Search the bundled mock index."""
    index = _load_index()
    seen_in_batch: set[str] = set(already_seen)
    results: list[Supplier] = []

    for query in queries:
        q_tokens = _tokenize(query)
        # Score all index entries against this query
        scored = [
            (entry, _score_entry(q_tokens, entry["keywords"]))
            for entry in index
        ]
        # Keep entries with any overlap, ranked by score
        matched = sorted(
            [(e, s) for e, s in scored if s > 0],
            key=lambda x: x[1],
            reverse=True,
        )[:max_per_query]

        for entry, _score in matched:
            raw = entry["supplier"]
            sid = raw["supplier_id"]
            if sid in seen_in_batch:
                continue
            seen_in_batch.add(sid)
            supplier = Supplier.from_dict(raw)
            supplier.source_query = query
            supplier.discovery_depth = depth
            results.append(supplier)

    return results


def _discover_via_backend(
    queries: list[str],
    depth: int,
    max_per_query: int,
    already_seen: set[str],
    backend: SearchBackend,
) -> list[Supplier]:
    """Search via a real HTTP backend, parsing returned dicts."""
    seen: set[str] = set(already_seen)
    results: list[Supplier] = []

    for query in queries:
        hits = backend.search(query, max_results=max_per_query)
        for raw in hits:
            # Assign a deterministic id if the backend didn't provide one.
            if "supplier_id" not in raw:
                raw["supplier_id"] = "http-" + uuid.uuid4().hex[:8]
            sid = raw["supplier_id"]
            if sid in seen:
                continue
            seen.add(sid)
            supplier = Supplier.from_dict(raw)
            supplier.source_query = query
            supplier.discovery_depth = depth
            results.append(supplier)

    return results
