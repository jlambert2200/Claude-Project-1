"""
Feature engineering.

For each supplier we compute a dict of numeric features grouped into
five families (per the system-design spec):

    A. Product signals
    B. Catalog structure signals
    C. Commercial language signals
    D. Transactional / operational signals
    E. Platform / localization signals

These features are all deliberately *observable* from a public B2B
listing. None of them depend on proprietary data. That keeps the
pipeline auditable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .normalization import normalize_product
from .precursor_registry import BY_NAME
from .schema import NormalizedProduct, Supplier


# ---------------------------------------------------------------------------
# Keyword lexicons
# ---------------------------------------------------------------------------
# These are common flags compliance officers already look for. They are
# not secret and not illegal to advertise — they simply shift the
# prior probability that a listing warrants manual review.

COMMERCIAL_LANGUAGE_KEYWORDS: tuple[str, ...] = (
    "custom synthesis",
    "custom-synthesis",
    "custom made",
    "made to order",
    "research use only",
    "research use",
    "for research",
    "not for human",
    "intermediate",
    "intermediates",
    "bulk supply",
    "oem",
    "contract manufacturing",
)

# Payment / shipping cues that regulators treat as operational red flags.
# We describe WHAT to look for, not HOW to evade anything.
TRANSACTIONAL_KEYWORDS: tuple[str, ...] = (
    "crypto",
    "bitcoin",
    "btc",
    "usdt",
    "western union",
    "moneygram",
    "cash only",
    "wire only",
)

SHIPPING_RED_FLAG_KEYWORDS: tuple[str, ...] = (
    "discreet",
    "discrete packaging",
    "plain package",
    "plain packaging",
    "stealth",
    "relabel",
    "re-label",
    "private label",
    "no label",
    "customs guarantee",
    "guaranteed delivery",
    "100% delivery",
    "bypass customs",  # explicit evasion language — strongest flag
)

EXPORT_ORIENTED_KEYWORDS: tuple[str, ...] = (
    "worldwide shipping",
    "global shipping",
    "door to door",
    "ddp",
    "export to",
    "ship worldwide",
    "international express",
)


# Regex for detecting Chinese characters in a block of text.
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_NEGATION_TOKENS: tuple[str, ...] = ("no ", "not ", "never ", "without ", "don't ", "do not ")


def _is_negated(lowered: str, idx: int) -> bool:
    """
    Shallow negation check: look back ~20 characters from the keyword and
    see if any of the common negation tokens sits immediately before it.
    This catches "no cryptocurrency" / "not accepted" without pretending
    to do real NLP.
    """
    window_start = max(0, idx - 20)
    window = lowered[window_start:idx]
    return any(window.endswith(tok) or (tok in window and not window[window.rfind(tok) + len(tok):].strip()) for tok in _NEGATION_TOKENS)


def _keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    """
    Return the list of keywords that appear (substring, case-insensitive),
    skipping matches that sit immediately after a negation token.
    """
    if not text:
        return []
    lowered = text.lower()
    hits: list[str] = []
    for kw in keywords:
        idx = lowered.find(kw)
        if idx == -1:
            continue
        if _is_negated(lowered, idx):
            continue
        hits.append(kw)
    return hits


def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = len(_CJK_RE.findall(text))
    return cjk / max(len(text), 1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_supplier_features(supplier: Supplier) -> tuple[dict[str, float], list[NormalizedProduct], list[dict]]:
    """
    Compute features for a single supplier.

    Returns:
        features          : numeric feature dict (input to scoring)
        normalized        : per-product normalization results (for audit)
        matched_precursors: canonical matches with severity (for explanations)
    """

    normalized: list[NormalizedProduct] = [normalize_product(p) for p in supplier.products]
    n_products = len(normalized)

    # --- A. Product signals -------------------------------------------------
    matched_entries = []
    categories_seen: set[str] = set()
    severities: list[int] = []
    for np in normalized:
        if np.canonical_name:
            entry = BY_NAME[np.canonical_name.lower()]
            matched_entries.append(
                {
                    "raw_name": np.raw_name,
                    "canonical_name": entry.canonical_name,
                    "cas": entry.cas,
                    "category": entry.category,
                    "severity": entry.severity,
                    "match_confidence": np.match_confidence,
                }
            )
            categories_seen.add(entry.category)
            severities.append(entry.severity)

    n_matched = len(matched_entries)
    n_monitored_precursors = sum(1 for e in matched_entries if e["category"] == "monitored_precursor")
    category_diversity = len(categories_seen)
    max_severity = max(severities) if severities else 0

    # Co-occurrence bonus: multiple severity-3 hits at once is itself a signal.
    severity3_count = sum(1 for s in severities if s == 3)
    co_occurrence = 1.0 if severity3_count >= 2 else 0.0

    # --- B. Catalog structure signals --------------------------------------
    n_vague = sum(1 for np in normalized if np.is_vague)
    pct_vague = (n_vague / n_products) if n_products else 0.0
    n_with_cas = sum(1 for np in normalized if np.cas)
    pct_with_cas = (n_with_cas / n_products) if n_products else 0.0

    # --- C. Commercial language signals ------------------------------------
    about_blob = " ".join(
        [supplier.about_text]
        + [p.description or "" for p in supplier.products]
        + [p.name or "" for p in supplier.products]
    )
    commercial_hits = _keyword_hits(about_blob, COMMERCIAL_LANGUAGE_KEYWORDS)

    # --- D. Transactional / operational signals ----------------------------
    txn_blob = " ".join([supplier.payment_terms, supplier.about_text])
    ship_blob = " ".join([supplier.shipping_terms, supplier.about_text])
    payment_hits = _keyword_hits(txn_blob, TRANSACTIONAL_KEYWORDS)
    shipping_hits = _keyword_hits(ship_blob, SHIPPING_RED_FLAG_KEYWORDS)
    has_explicit_evasion = any("bypass customs" in kw or "no label" in kw for kw in shipping_hits)

    # --- E. Platform / localization signals --------------------------------
    all_text = f"{supplier.name} {supplier.about_text} {about_blob} {supplier.shipping_terms}"
    chinese_ratio = _chinese_ratio(all_text)
    # An "English-forward" catalog from a Chinese-registered supplier is
    # mildly export-oriented. This is not a red flag on its own — it is
    # one of several contextual features.
    export_hits = _keyword_hits(all_text, EXPORT_ORIENTED_KEYWORDS)

    features: dict[str, float] = {
        # A
        "n_matched_chemicals": float(n_matched),
        "n_monitored_precursors": float(n_monitored_precursors),
        "category_diversity": float(category_diversity),
        "max_severity": float(max_severity),
        "precursor_co_occurrence": co_occurrence,
        # B
        "n_products": float(n_products),
        "pct_vague_names": pct_vague,
        "pct_with_cas": pct_with_cas,
        # C
        "commercial_language_hits": float(len(commercial_hits)),
        # D
        "transactional_hits": float(len(payment_hits)),
        "shipping_red_flag_hits": float(len(shipping_hits)),
        "explicit_evasion_language": 1.0 if has_explicit_evasion else 0.0,
        # E
        "chinese_text_ratio": chinese_ratio,
        "export_oriented_hits": float(len(export_hits)),
    }

    # Keyword lists are kept on the side so the explanation layer can quote
    # them back verbatim.
    features["_commercial_keywords"] = commercial_hits  # type: ignore[assignment]
    features["_transactional_keywords"] = payment_hits  # type: ignore[assignment]
    features["_shipping_keywords"] = shipping_hits      # type: ignore[assignment]
    features["_export_keywords"] = export_hits          # type: ignore[assignment]

    return features, normalized, matched_entries
