"""
Data schema for the chemical supplier risk prototype.

The schema is intentionally minimal. Everything downstream (normalization,
features, scoring, explanations, graph) reads and writes these dataclasses
so a policy researcher can follow the pipeline without chasing dict keys.

NOTE ON PURPOSE
---------------
This prototype identifies *behavioral risk signals* in supplier listings
(for compliance / research / policy analysis). It does NOT:
  - produce synthesis routes,
  - rank which chemicals are "most useful" for misuse, or
  - suggest sourcing strategies.

It only flags patterns that compliance teams already look for when
screening Business-to-Business (B2B) catalogs.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Raw input (what an ingestion adapter produces from a B2B-style listing)
# ---------------------------------------------------------------------------


@dataclass
class Product:
    """A single product line item on a supplier catalog."""

    name: str
    description: str = ""
    cas: str | None = None  # CAS Registry Number if the listing exposes one

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Supplier:
    """
    A supplier / seller as it appears on a Chinese B2B marketplace.

    Only free-text-ish fields are modeled — the point of the prototype is
    to show that risk signals can be derived from fields that are already
    public in listings (company name, product names, payment/shipping copy).
    """

    supplier_id: str
    name: str
    location: str | None = None
    products: list[Product] = field(default_factory=list)
    payment_terms: str = ""   # free text from the listing
    shipping_terms: str = ""  # free text from the listing
    about_text: str = ""      # company description / "About us" blurb
    # Optional provenance: which discovery query / source surfaced this supplier
    source_query: str = ""
    discovery_depth: int = 0  # 0 = seed / manual; 1+ = discovered at iteration N

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Supplier":
        products = [Product(**p) for p in d.get("products", [])]
        return cls(
            supplier_id=d["supplier_id"],
            name=d["name"],
            location=d.get("location"),
            products=products,
            payment_terms=d.get("payment_terms", ""),
            shipping_terms=d.get("shipping_terms", ""),
            about_text=d.get("about_text", ""),
            source_query=d.get("source_query", ""),
            discovery_depth=int(d.get("discovery_depth", 0)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "name": self.name,
            "location": self.location,
            "products": [p.as_dict() for p in self.products],
            "payment_terms": self.payment_terms,
            "shipping_terms": self.shipping_terms,
            "about_text": self.about_text,
            "source_query": self.source_query,
            "discovery_depth": self.discovery_depth,
        }


# ---------------------------------------------------------------------------
# Enrichment + output  (Phase 1: chemical risk scoring)
# ---------------------------------------------------------------------------


@dataclass
class NormalizedProduct:
    """A product after the Chemical Normalization Module has run on it."""

    raw_name: str
    canonical_name: str | None  # e.g. "acetone" if we resolved it
    cas: str | None
    match_confidence: float     # 0.0 to 1.0 fuzzy-match score
    is_vague: bool              # True if the product name is generic/placeholder


@dataclass
class SupplierScore:
    """Phase-1 risk-scoring output for one supplier (chemical signal only)."""

    supplier_id: str
    name: str
    risk_score: float              # 0-100 (chemical + transactional features)
    risk_band: str                 # "low" | "medium" | "high"
    features: dict[str, float]     # raw feature values
    contributions: dict[str, float]  # feature -> points contributed to score
    explanations: list[str]        # human-readable bullet points
    matched_precursors: list[dict[str, Any]]  # canonical matches (for audit)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Phase 2: Commercial positioning (new in v2)
# ---------------------------------------------------------------------------


@dataclass
class PositioningResult:
    """
    How a supplier positions itself commercially toward uncertain / flexible
    demand. This is distinct from the chemical-match risk score — a supplier
    can have zero monitored chemicals yet still signal extreme willingness to
    accommodate ambiguous buyers.

    Sub-scores (each 0-25) sum to a positioning_score ∈ [0, 100].

    flexibility_score   : custom synthesis, MOQ flexibility, made-to-order.
    ambiguity_score     : vague listings, info-on-request, no regulatory copy.
    accommodation_score : labeling / packaging changes, spec negotiation.
    tone_score          : permissive vs compliance-oriented language tone.
    """

    supplier_id: str
    flexibility_score: float    # 0-25
    ambiguity_score: float      # 0-25
    accommodation_score: float  # 0-25
    tone_score: float           # 0-25
    positioning_score: float    # 0-100 (capped sum of above)
    positioning_band: str       # "low" | "medium" | "high"
    # Per-dimension keyword evidence for the explanation layer.
    signals: dict[str, list[str]]
    explanation: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Phase 3: Combined score (new in v2)
# ---------------------------------------------------------------------------


@dataclass
class CombinedScore:
    """
    Merges the chemical risk score (Phase 1) with the commercial positioning
    score (Phase 2) into a single analyst-facing record.

    combined_score = risk_score + POSITIONING_WEIGHT * positioning_score
    where POSITIONING_WEIGHT = 0.35 (positioning adds up to 35 extra points).

    This keeps combined_score ≤ 100 when both components are high, and lets
    positioning push a medium-risk supplier into high band when the commercial
    posture is extremely permissive.
    """

    supplier_id: str
    name: str
    location: str | None
    source_query: str
    discovery_depth: int

    risk_score: float
    positioning_score: float
    combined_score: float
    combined_band: str          # "low" | "medium" | "high"

    risk_contributions: dict[str, float]
    positioning_signals: dict[str, list[str]]

    explanations: list[str]     # unified, de-duplicated explanation list
    matched_precursors: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
