"""
Tests for the chemical supplier risk pipeline (Phase 1 + Phase 2).
"""

from __future__ import annotations

import json
from pathlib import Path

from chemical_risk.normalization import extract_cas, is_vague_name, normalize_product
from chemical_risk.pipeline import analyze_suppliers, score_one
from chemical_risk.schema import Product, Supplier

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

    by_id = {s.supplier_id: s for s in result.combined_scores}

    assert by_id["s-001"].combined_band == "low"
    assert by_id["s-005"].combined_band == "low"
    assert by_id["s-006"].combined_band == "high"
    assert by_id["s-003"].combined_band == "high"

    benign = max(by_id["s-001"].combined_score, by_id["s-005"].combined_score)
    risky = min(by_id["s-006"].combined_score, by_id["s-003"].combined_score)
    assert risky > benign


def test_pipeline_explanations_exist():
    result = analyze_suppliers(json.loads(SAMPLE.read_text(encoding="utf-8")))
    for s in result.combined_scores:
        if s.combined_band != "low":
            assert s.explanations, f"missing explanations for {s.supplier_id}"


def test_graph_has_edges_when_overlap_exists():
    result = analyze_suppliers(json.loads(SAMPLE.read_text(encoding="utf-8")))
    ids = {(e.source, e.target) for e in result.graph.edges}
    ids |= {(b, a) for (a, b) in ids}
    assert any("s-002" in pair for pair in ids) or any("s-005" in pair for pair in ids)


# ---------------------------------------------------------------------------
# Phase 2: positioning tests
# ---------------------------------------------------------------------------

from chemical_risk.positioning import analyze_positioning


def test_positioning_flexible_supplier():
    s = Supplier(
        supplier_id="p-test-1",
        name="Test Flex Supplier",
        about_text="Custom synthesis available. Made to order. Small batch accepted. Tailored solutions. Bespoke manufacturing.",
        payment_terms="T/T",
        shipping_terms="Standard",
        products=[],
    )
    result = analyze_positioning(s)
    assert result.flexibility_score > 10.0
    assert result.positioning_score > 0.0


def test_positioning_evasion_supplier():
    # Supplier triggers multiple dimensions: permissive tone + accommodation + flexibility.
    s = Supplier(
        supplier_id="p-test-2",
        name="Test Evasion Supplier",
        about_text=(
            "No questions asked. Any destination. Stealth packaging. "
            "Flexible arrangement. Anonymous orders. "
            "Relabel and adjust labeling on request. Private label available. "
            "Custom synthesis, made to order."
        ),
        payment_terms="Bitcoin only.",
        shipping_terms="Bypass customs guaranteed delivery. Plain package available.",
        products=[],
    )
    result = analyze_positioning(s)
    assert result.tone_score > 10.0
    assert result.positioning_score >= 30.0
    assert result.positioning_band in ("medium", "high")


def test_positioning_compliance_supplier():
    s = Supplier(
        supplier_id="p-test-3",
        name="Test Compliant Supplier",
        about_text="End-use certificate required. License required. KYC verification mandatory. REACH compliant. Documentation required for all orders.",
        payment_terms="T/T only.",
        shipping_terms="Full customs documentation.",
        products=[],
    )
    result = analyze_positioning(s)
    # Compliance language should suppress tone score
    assert result.tone_score < 5.0
    assert result.positioning_band in ("low", "medium")


def test_combined_score_adds_positioning():
    # A supplier with no chemicals but high positioning signals should
    # move from low risk to at least medium combined score.
    s = Supplier(
        supplier_id="p-test-4",
        name="No Chemicals but Evasive",
        about_text=(
            "Custom synthesis, made to order, no questions asked, "
            "any destination, stealth packaging, 100% delivery guaranteed, "
            "flexible arrangement, anonymous orders accepted."
        ),
        payment_terms="Bitcoin, USDT only.",
        shipping_terms="Discreet, relabel on request.",
        products=[Product(name="general compound", description="details on request")],
    )
    _risk, combined = score_one(s)
    assert combined.positioning_score > 30.0
    assert combined.combined_score > _risk.risk_score  # positioning adds to combined


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------

from chemical_risk.discovery import discover_suppliers, generate_expansion_queries


def test_discovery_returns_suppliers():
    results = discover_suppliers(["chemical intermediates supplier china"])
    assert len(results) > 0
    assert all(hasattr(r, "supplier_id") for r in results)


def test_discovery_deduplication():
    """Same query twice should not return the same supplier twice."""
    r1 = discover_suppliers(["custom synthesis"])
    r2 = discover_suppliers(
        ["custom synthesis"],
        already_seen={s.supplier_id for s in r1},
    )
    overlap = {s.supplier_id for s in r1} & {s.supplier_id for s in r2}
    assert len(overlap) == 0


def test_expansion_queries_generated():
    s = Supplier(
        supplier_id="q-test-1",
        name="Expansion Test",
        about_text="custom synthesis research chemicals",
        payment_terms="USDT",
        shipping_terms="stealth packaging worldwide",
        products=[Product(name="piperonal", cas="120-57-0")],
    )
    qs = generate_expansion_queries(s, combined_score=50.0, canonical_names=["piperonal"])
    assert len(qs) > 0


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------

from chemical_risk.storage import SupplierStore


def test_storage_save_and_retrieve():
    store = SupplierStore(":memory:")
    s = Supplier(supplier_id="st-001", name="Storage Test", about_text="test")
    assert store.save_supplier(s) is True    # new insert
    assert store.save_supplier(s) is False   # duplicate, skip
    assert store.has_supplier("st-001")
    suppliers = store.get_all_suppliers()
    assert any(sup.supplier_id == "st-001" for sup in suppliers)
    store.close()


def test_storage_known_ids():
    store = SupplierStore(":memory:")
    s = Supplier(supplier_id="st-002", name="Known IDs Test")
    store.save_supplier(s)
    assert "st-002" in store.known_ids()
    store.close()


# ---------------------------------------------------------------------------
# Agent loop tests
# ---------------------------------------------------------------------------

from chemical_risk.agent import run_discovery_cycle


def test_agent_loop_runs():
    report = run_discovery_cycle(
        seed_queries=["chemical intermediates supplier china"],
        iterations=2,
        verbose=False,
    )
    assert report.iterations_run >= 1
    assert len(report.all_combined_scores) > 0


def test_agent_loop_finds_high_risk():
    """With adversarial queries the agent should surface high-band suppliers."""
    report = run_discovery_cycle(
        seed_queries=["research chemicals no documentation any destination"],
        iterations=2,
        verbose=False,
    )
    high = [cs for cs in report.all_combined_scores if cs.combined_band == "high"]
    assert len(high) > 0


def test_agent_loop_expansion_queries():
    """Later iterations should use different queries than seed."""
    report = run_discovery_cycle(
        seed_queries=["custom synthesis fine chemicals"],
        iterations=3,
        verbose=False,
    )
    # If any iteration generated expansion queries, they differ from seed.
    for log in report.iteration_logs:
        for q in log.new_queries_generated:
            assert q not in report.seed_queries
