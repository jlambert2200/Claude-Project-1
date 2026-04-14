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
        }


# ---------------------------------------------------------------------------
# Enrichment + output
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
    """Final risk-scoring output for one supplier."""

    supplier_id: str
    name: str
    risk_score: float              # 0-100
    risk_band: str                 # "low" | "medium" | "high"
    features: dict[str, float]     # raw feature values
    contributions: dict[str, float]  # feature -> points contributed to score
    explanations: list[str]        # human-readable bullet points
    matched_precursors: list[dict[str, Any]]  # canonical matches (for audit)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
