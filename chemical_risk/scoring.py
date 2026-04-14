"""
Transparent risk scoring + explanation layer.

Design choices
--------------
* The score is a **weighted linear sum** of features. No hidden model,
  no learned parameters. A policy researcher can read this file and
  fully reproduce any score by hand.
* Every weighted term records its contribution, so explanations cite
  the exact features that drove the score.
* The score is clipped to [0, 100] and mapped to a 3-band label
  (low / medium / high) for reporting.
"""

from __future__ import annotations

from .schema import Supplier, SupplierScore


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
# Each entry is: (feature_name, weight, human_label).
#
# The weight multiplies the raw feature value. Weights are chosen so that
# a "clearly concerning" supplier lands around 60-80, and a "benign"
# supplier lands near 0-20.
#
# All weights are positive — higher feature value = more risk. Features
# whose value can be large (e.g. counts) use smaller weights; boolean
# flags use larger weights.

WEIGHTS: tuple[tuple[str, float, str], ...] = (
    # Product signals (A)
    ("n_monitored_precursors",    8.0,  "Listings match monitored precursor class"),
    ("category_diversity",        2.0,  "Spans multiple monitored chemical categories"),
    ("precursor_co_occurrence",  10.0,  "Multiple monitored precursors appear in one catalog"),
    ("max_severity",              2.0,  "Highest-severity match in catalog"),

    # Catalog structure (B)
    ("pct_vague_names",          20.0,  "Share of catalog using vague / placeholder names"),

    # Commercial language (C)
    ("commercial_language_hits",  3.0,  "Uses 'custom synthesis' / 'research use' style phrasing"),

    # Transactional / operational (D)
    ("transactional_hits",        5.0,  "Payment copy references high-risk rails (crypto, wire-only)"),
    ("shipping_red_flag_hits",    6.0,  "Shipping copy references discreet / relabel practices"),
    ("explicit_evasion_language",15.0,  "Listing contains explicit customs-evasion language"),

    # Platform / localization (E)
    ("export_oriented_hits",      1.0,  "Strong export-oriented framing"),
)

# Transparency "anti-signals": features that REDUCE score (good practice).
# A catalog that almost always discloses CAS numbers is less suspicious than
# one that hides them.
ANTI_WEIGHTS: tuple[tuple[str, float, str], ...] = (
    ("pct_with_cas",              5.0,  "Most products disclose CAS numbers (transparency)"),
)


def _band(score: float) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Scoring + explanation
# ---------------------------------------------------------------------------


def score_supplier(
    supplier: Supplier,
    features: dict,
    matched_precursors: list[dict],
) -> SupplierScore:
    """
    Compute a SupplierScore from a features dict produced by
    `features.build_supplier_features`.

    The explanation bullets are generated at the same time so there is
    a single source of truth for "why this score".
    """

    contributions: dict[str, float] = {}
    explanations: list[str] = []

    # Positive weights
    for feat, w, label in WEIGHTS:
        val = float(features.get(feat, 0.0))
        if val <= 0:
            continue
        contribution = w * val
        contributions[feat] = round(contribution, 2)
        explanations.append(f"{label} (+{contribution:.1f})")

    # Anti-signals (reduce score)
    for feat, w, label in ANTI_WEIGHTS:
        val = float(features.get(feat, 0.0))
        if val <= 0:
            continue
        contribution = -w * val
        contributions[feat] = round(contribution, 2)
        explanations.append(f"{label} ({contribution:.1f})")

    raw_total = sum(contributions.values())
    risk_score = max(0.0, min(100.0, raw_total))

    # Enrich explanations with concrete evidence where we have it --------
    if matched_precursors:
        # Just counts and categories — not which chemical, unless severity 3
        # (which is already publicly regulatory information).
        sev3 = [m for m in matched_precursors if m["severity"] == 3]
        if sev3:
            names = ", ".join(sorted({m["canonical_name"] for m in sev3}))
            explanations.append(f"Monitored precursor-class matches: {names}")
        cats = sorted({m["category"] for m in matched_precursors})
        explanations.append(f"Matched categories: {', '.join(cats)}")

    for tag in ("_commercial_keywords", "_transactional_keywords", "_shipping_keywords"):
        hits = features.get(tag) or []
        if hits:
            pretty = tag.replace("_", " ").strip().replace("keywords", "cues").strip()
            explanations.append(f"Detected {pretty}: {', '.join(hits)}")

    # Numeric feature snapshot stripped of private/underscored side-channels
    public_features = {k: v for k, v in features.items() if not k.startswith("_")}

    return SupplierScore(
        supplier_id=supplier.supplier_id,
        name=supplier.name,
        risk_score=round(risk_score, 2),
        risk_band=_band(risk_score),
        features=public_features,
        contributions=contributions,
        explanations=explanations,
        matched_precursors=matched_precursors,
    )
