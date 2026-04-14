"""
Smoke tests for the chemical supplier risk pipeline.

These are not exhaustive — they assert the pipeline runs end-to-end on the
example dataset and produces the kind of ordering a compliance analyst
would expect (benign supplier < export chem trader < "custom synthesis"
storefront with evasion language).
"""

from __future__ import annotations

import json
from pathlib import Path

from chemical_risk.normalization import extract_cas, is_vague_name, normalize_product
from chemical_risk.pipeline import analyze_suppliers
from chemical_risk.schema import Product


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample_suppliers.json"


def test_extract_cas():
    assert extract_cas("Acetone, CAS 67-64-1, 99%") == "67-64-1"
    assert extract_cas("no numbers here") is None


def test_is_vague_name():
    assert is_vague_name("Pharmaceutical Intermediate")
    assert is_vague_name("Research Compound A")
    assert not is_vague_name("Acetone")


def test_normalize_product_by_cas():
    p = Product(name="something unclear", cas="67-64-1")
    out = normalize_product(p)
    assert out.canonical_name == "acetone"
    assert out.match_confidence == 1.0


def test_normalize_product_by_synonym():
    p = Product(name="MEK")
    out = normalize_product(p)
    assert out.canonical_name == "methyl ethyl ketone"


def test_normalize_product_fuzzy():
    p = Product(name="acetic anhydrid")  # typo
    out = normalize_product(p)
    assert out.canonical_name == "acetic anhydride"
    assert out.match_confidence >= 0.8


def test_pipeline_runs_and_orders_suppliers():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    result = analyze_suppliers(data)

    by_id = {s.supplier_id: s for s in result.scores}

    # Clearly benign supplier: low band
    assert by_id["s-001"].risk_band == "low"
    assert by_id["s-005"].risk_band == "low"

    # Obvious high-risk storefront with evasion language: high band
    assert by_id["s-006"].risk_band == "high"
    assert by_id["s-003"].risk_band == "high"

    # Ordering sanity: s-006 and s-003 should outrank s-001/s-005
    benign = max(by_id["s-001"].risk_score, by_id["s-005"].risk_score)
    risky = min(by_id["s-006"].risk_score, by_id["s-003"].risk_score)
    assert risky > benign


def test_pipeline_explanations_exist():
    result = analyze_suppliers(json.loads(SAMPLE.read_text(encoding="utf-8")))
    for s in result.scores:
        # Either the supplier is a clean "low" (no red flags needed) or we
        # have something to say about it.
        if s.risk_band != "low":
            assert s.explanations, f"missing explanations for {s.supplier_id}"


def test_graph_has_edges_when_overlap_exists():
    result = analyze_suppliers(json.loads(SAMPLE.read_text(encoding="utf-8")))
    # s-002 and s-005 both list acetone / ethanol / etc.
    ids = {(e.source, e.target) for e in result.graph.edges}
    ids |= {(b, a) for (a, b) in ids}
    assert any("s-002" in pair for pair in ids) or any("s-005" in pair for pair in ids)
