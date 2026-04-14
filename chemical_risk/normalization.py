"""
Chemical Normalization Module.

Given a raw product line item from a B2B listing, we try to answer:

    1. Does this line contain a CAS Registry Number?
    2. Does the product name match a canonical chemical in our registry
       (exact, synonym, or fuzzy)?
    3. How generic / "vague" is the listing (e.g. just "intermediate")?

We deliberately use only the standard library (re, difflib) so the
prototype has no extra dependencies for string matching.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .precursor_registry import BY_CAS, BY_NAME, REGISTRY, RegistryEntry
from .schema import NormalizedProduct, Product


# ---------------------------------------------------------------------------
# CAS extraction
# ---------------------------------------------------------------------------
# CAS numbers look like NNNNNNN-NN-N (2-7 digits, 2 digits, 1 digit).
_CAS_RE = re.compile(r"\b(\d{2,7}-\d{2}-\d)\b")


def extract_cas(text: str) -> str | None:
    """Return the first CAS number found in text, or None."""
    if not text:
        return None
    m = _CAS_RE.search(text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Vague-name detection
# ---------------------------------------------------------------------------
# A listing is "vague" if its name is a generic placeholder that could mean
# almost anything. This is a known compliance red flag — it hides what is
# actually being sold.

_VAGUE_TOKENS: tuple[str, ...] = (
    "intermediate",
    "intermediates",
    "research compound",
    "research chemical",
    "custom compound",
    "specialty compound",
    "new product",
    "fine chemical",
    "api intermediate",
    "pharmaceutical intermediate",
    "organic intermediate",
)


def is_vague_name(name: str) -> bool:
    lowered = (name or "").lower().strip()
    if not lowered:
        return True
    # If the entire name IS just a vague token (or close to it), flag it.
    for token in _VAGUE_TOKENS:
        if token == lowered or lowered.startswith(token + " ") or lowered.endswith(" " + token):
            return True
        # "Pharmaceutical Intermediate 99%" style
        if token in lowered and len(lowered.split()) <= 4:
            return True
    return False


# ---------------------------------------------------------------------------
# Fuzzy matching against the registry
# ---------------------------------------------------------------------------

# Minimum similarity for a fuzzy match to count. Tuned loosely — the
# prototype prefers false positives (surfaced for review) over silent misses.
_FUZZY_THRESHOLD = 0.82


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _best_fuzzy_match(name: str) -> tuple[RegistryEntry | None, float]:
    """Return the best (entry, score) across all canonical names + synonyms."""
    best: tuple[RegistryEntry | None, float] = (None, 0.0)
    if not name:
        return best
    for entry in REGISTRY:
        candidates = (entry.canonical_name,) + entry.synonyms
        for cand in candidates:
            score = _similarity(name, cand)
            if score > best[1]:
                best = (entry, score)
    return best


def normalize_product(product: Product) -> NormalizedProduct:
    """
    Resolve a raw Product to a NormalizedProduct.

    Matching priority:
      1. CAS number on the product (authoritative).
      2. CAS number found in the description text.
      3. Exact / synonym name match (case-insensitive).
      4. Fuzzy name match above threshold.
    """
    raw_name = product.name or ""
    combined_text = f"{raw_name} {product.description or ''}"

    # 1 & 2: CAS-based match
    cas = (product.cas or "").strip() or extract_cas(combined_text)
    if cas and cas in BY_CAS:
        entry = BY_CAS[cas]
        return NormalizedProduct(
            raw_name=raw_name,
            canonical_name=entry.canonical_name,
            cas=entry.cas,
            match_confidence=1.0,
            is_vague=is_vague_name(raw_name),
        )

    # 3: exact or synonym match
    lowered = raw_name.lower().strip()
    if lowered in BY_NAME:
        entry = BY_NAME[lowered]
        return NormalizedProduct(
            raw_name=raw_name,
            canonical_name=entry.canonical_name,
            cas=entry.cas,
            match_confidence=1.0,
            is_vague=False,
        )

    # 4: fuzzy match
    entry, score = _best_fuzzy_match(raw_name)
    if entry is not None and score >= _FUZZY_THRESHOLD:
        return NormalizedProduct(
            raw_name=raw_name,
            canonical_name=entry.canonical_name,
            cas=entry.cas,
            match_confidence=round(score, 3),
            is_vague=False,
        )

    # No match — but still record whether the listing is a vague placeholder.
    return NormalizedProduct(
        raw_name=raw_name,
        canonical_name=None,
        cas=cas,
        match_confidence=0.0,
        is_vague=is_vague_name(raw_name),
    )
