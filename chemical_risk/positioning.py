"""
Commercial Positioning Analyzer (Phase 2).

This module answers a different question than the chemical-risk scorer:

    "How does this supplier *present itself* to uncertain or flexible buyers?"

A supplier can score low on chemical risk (no monitored precursors listed)
yet still signal extreme willingness to accommodate ambiguous demand via
its marketing copy. Conversely, a legitimate industrial supplier may list
monitored chemicals but present a strongly compliance-oriented posture.

Both dimensions together give analysts a richer picture.

SCORING MODEL
-------------
Four sub-dimensions, each capped at 25 points, sum to a positioning_score
in [0, 100]:

    A. Flexibility (0-25)
       Signals: custom synthesis, made-to-order, small batch, trial orders,
       flexible MOQ, toll manufacturing, bespoke.

    B. Ambiguity tolerance (0-25)
       Signals: inquiry-only descriptions, vague product names (reused from
       feature engineering), absence of regulatory/compliance copy, "details
       on request".

    C. Buyer accommodation (0-25)
       Signals: labeling changes, packaging modification, spec negotiation,
       "special requests", OEM re-branding.

    D. Language tone (0-25)
       Permissive tone is scored up; compliance-oriented tone is scored down.
       Permissive: "no questions", "any destination", "flexible arrangement".
       Compliance: "end-use certificate", "license required", "KYC", "REACH".

All keyword lists are observable from public B2B listing text; none
encode synthesis knowledge.
"""

from __future__ import annotations

from collections.abc import Iterable

from .features import _keyword_hits, _is_negated   # reuse negation-aware helper
from .schema import PositioningResult, Supplier


# ---------------------------------------------------------------------------
# Lexicons – grouped by sub-dimension
# ---------------------------------------------------------------------------

# A. Flexibility signals
FLEXIBILITY_KEYWORDS: tuple[tuple[str, float], ...] = (
    ("custom synthesis",         3.0),
    ("custom-synthesis",         3.0),
    ("made to order",            3.0),
    ("make to order",            3.0),
    ("tailored solution",        2.5),
    ("bespoke",                  2.5),
    ("toll manufacturing",       2.0),
    ("small batch",              2.0),
    ("trial order",              2.0),
    ("trial orders",             2.0),
    ("sample order",             1.5),
    ("flexible MOQ",             2.0),
    ("minimum order negotiable", 2.5),
    ("no minimum",               2.5),
    ("low MOQ",                  2.0),
    ("contract manufacturing",   1.5),
    ("OEM manufacturing",        1.5),
    ("custom made",              2.0),
    ("custom order",             2.0),
)

# B. Ambiguity tolerance signals
AMBIGUITY_KEYWORDS: tuple[tuple[str, float], ...] = (
    ("details on request",       3.0),
    ("details upon request",     3.0),
    ("inquire for details",      3.0),
    ("ask for details",          3.0),
    ("contact for details",      2.5),
    ("information on request",   2.5),
    ("specifications on request",2.5),
    ("not listed",               1.5),
    ("various products",         1.0),
    ("wide range of products",   1.0),
    ("not for public listing",   3.0),
    ("undisclosed",              3.0),
    ("confidential listing",     3.0),
    ("special product",          2.0),
    ("special chemicals",        2.0),
    ("for research",             1.5),
    ("research chemicals",       2.0),
    ("research use only",        2.0),
    ("lab use only",             2.0),
    ("not for human use",        2.0),
)

# C. Buyer accommodation signals
ACCOMMODATION_KEYWORDS: tuple[tuple[str, float], ...] = (
    ("special request",          3.0),
    ("special requests",         3.0),
    ("special requirements",     2.5),
    ("accommodate",              2.0),
    ("adjust label",             3.0),
    ("adjust labeling",          3.0),
    ("custom label",             2.5),
    ("custom labeling",          2.5),
    ("custom packaging",         2.0),
    ("modify packaging",         2.0),
    ("relabel",                  3.0),
    ("re-label",                 3.0),
    ("white label",              2.0),
    ("private label",            2.0),
    ("negotiate specification",  2.5),
    ("flexible specification",   2.5),
    ("any specification",        3.0),
    ("buyer's spec",             2.5),
    ("meet your requirement",    2.0),
    ("meet customer requirements",2.0),
)

# D-up. Permissive tone (scored up)
PERMISSIVE_TONE_KEYWORDS: tuple[tuple[str, float], ...] = (
    ("no questions asked",       5.0),
    ("no questions",             3.0),
    ("any destination",          3.0),
    ("any country",              3.0),
    ("flexible arrangement",     3.0),
    ("discreet",                 3.0),
    ("stealth",                  3.0),
    ("anonymous",                4.0),
    ("no documentation",         4.0),
    ("no paperwork",             4.0),
    ("guaranteed delivery",      2.0),
    ("100% delivery",            2.0),
    ("bypass",                   4.0),
    ("no restriction",           3.0),
)

# D-down. Compliance-oriented tone (scored down — good signals)
COMPLIANCE_TONE_KEYWORDS: tuple[tuple[str, float], ...] = (
    ("end-use certificate",      4.0),
    ("end use certificate",      4.0),
    ("license required",         4.0),
    ("regulated",                2.0),
    ("regulatory",               2.0),
    ("REACH",                    2.0),
    ("KYC",                      3.0),
    ("know your customer",       3.0),
    ("documentation required",   3.0),
    ("export permit",            3.0),
    ("import permit",            3.0),
    ("MSDS",                     1.5),
    ("SDS",                      1.5),
    ("certificate of analysis",  1.5),
    ("CoA",                      1.5),
    ("CITES",                    2.0),
)

# Cap for each sub-dimension
_DIM_CAP = 25.0

# Combined cap for the full score
_TOTAL_CAP = 100.0

# How many compliance keywords offset a point of tone risk
_COMPLIANCE_OFFSET_RATIO = 1.0  # 1 compliance point cancels 1 permissive point


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _score_dimension(
    text: str,
    weighted_keywords: tuple[tuple[str, float], ...],
) -> tuple[float, list[str]]:
    """
    Return (raw_score, matched_keyword_list) for a single dimension.
    Uses the negation-aware keyword match from features.py.
    """
    if not text:
        return 0.0, []
    lowered = text.lower()
    total = 0.0
    hits: list[str] = []
    for kw, weight in weighted_keywords:
        idx = lowered.find(kw)
        if idx == -1:
            continue
        if _is_negated(lowered, idx):
            continue
        total += weight
        hits.append(kw)
    return total, hits


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_positioning(supplier: Supplier, pct_vague: float = 0.0) -> PositioningResult:
    """
    Compute positioning sub-scores and explanations for a single supplier.

    `pct_vague` is the vague-name fraction already computed by
    `features.build_supplier_features`. Pass it through to boost the
    ambiguity dimension when the catalog itself is opaque, without re-doing
    the normalization work.
    """

    # Aggregate all free-text we can observe from the listing.
    all_text = " ".join(
        filter(None, [
            supplier.about_text,
            supplier.payment_terms,
            supplier.shipping_terms,
            " ".join(p.name or "" for p in supplier.products),
            " ".join(p.description or "" for p in supplier.products),
        ])
    )

    # --- A. Flexibility -------------------------------------------------------
    flex_raw, flex_hits = _score_dimension(all_text, FLEXIBILITY_KEYWORDS)
    flex_score = min(_DIM_CAP, flex_raw)

    # --- B. Ambiguity tolerance -----------------------------------------------
    amb_raw, amb_hits = _score_dimension(all_text, AMBIGUITY_KEYWORDS)
    # Catalog vagueness (product name-level) adds up to 10 bonus points.
    catalog_ambiguity_bonus = pct_vague * 10.0
    amb_score = min(_DIM_CAP, amb_raw + catalog_ambiguity_bonus)

    # --- C. Buyer accommodation -----------------------------------------------
    acc_raw, acc_hits = _score_dimension(all_text, ACCOMMODATION_KEYWORDS)
    acc_score = min(_DIM_CAP, acc_raw)

    # --- D. Language tone (permissive up, compliance down) --------------------
    perm_raw, perm_hits = _score_dimension(all_text, PERMISSIVE_TONE_KEYWORDS)
    comp_raw, comp_hits = _score_dimension(all_text, COMPLIANCE_TONE_KEYWORDS)
    tone_raw = perm_raw - _COMPLIANCE_OFFSET_RATIO * comp_raw
    tone_score = min(_DIM_CAP, max(0.0, tone_raw))

    # --- Total ----------------------------------------------------------------
    total = flex_score + amb_score + acc_score + tone_score
    positioning_score = min(_TOTAL_CAP, total)

    band = "high" if positioning_score >= 60 else ("medium" if positioning_score >= 30 else "low")

    # --- Explanations ---------------------------------------------------------
    explanation: list[str] = []
    if flex_score > 0:
        explanation.append(
            f"Flexibility signals ({flex_score:.1f}/25): {', '.join(flex_hits[:4])}"
        )
    if amb_score > 0:
        parts = amb_hits[:4]
        if catalog_ambiguity_bonus > 0:
            parts.append(f"catalog is {pct_vague:.0%} vague product names")
        explanation.append(f"Ambiguity tolerance ({amb_score:.1f}/25): {', '.join(parts)}")
    if acc_score > 0:
        explanation.append(
            f"Buyer accommodation ({acc_score:.1f}/25): {', '.join(acc_hits[:4])}"
        )
    if tone_score > 0:
        explanation.append(
            f"Permissive tone ({tone_score:.1f}/25): {', '.join(perm_hits[:4])}"
        )
    if comp_raw > 0:
        explanation.append(
            f"Compliance language offsets tone by -{comp_raw:.1f} pts: {', '.join(comp_hits[:3])}"
        )
    if not explanation:
        explanation.append("No significant commercial positioning signals detected.")

    signals: dict[str, list[str]] = {
        "flexibility": flex_hits,
        "ambiguity": amb_hits,
        "accommodation": acc_hits,
        "permissive_tone": perm_hits,
        "compliance_tone": comp_hits,
    }

    return PositioningResult(
        supplier_id=supplier.supplier_id,
        flexibility_score=round(flex_score, 2),
        ambiguity_score=round(amb_score, 2),
        accommodation_score=round(acc_score, 2),
        tone_score=round(tone_score, 2),
        positioning_score=round(positioning_score, 2),
        positioning_band=band,
        signals=signals,
        explanation=explanation,
    )
