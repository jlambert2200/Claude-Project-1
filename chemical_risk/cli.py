"""
Command-line entry point.

Two sub-commands:

  score   – score a static JSON file of suppliers (original behaviour)
  discover – run the iterative discovery agent from seed queries

Usage:
    # Score a known file
    python -m chemical_risk.cli score examples/sample_suppliers.json

    # Run the discovery agent (3 iterations, mock mode)
    python -m chemical_risk.cli discover \\
        "chemical intermediates supplier china" \\
        "custom synthesis fine chemicals" \\
        --iterations 3 --out out/ --plots

    # Same, persist to SQLite
    python -m chemical_risk.cli discover \\
        "research chemicals bulk" \\
        --db chemical_risk.db --out out/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# score sub-command
# ---------------------------------------------------------------------------


def _cmd_score(args: argparse.Namespace) -> int:
    from .pipeline import analyze_suppliers

    result = analyze_suppliers(args.input, graph_threshold=args.threshold)

    print(f"Analyzed {len(result.combined_scores)} suppliers\n")
    for cs in sorted(result.combined_scores, key=lambda x: x.combined_score, reverse=True):
        print(
            f"[{cs.combined_band.upper():6}] combined={cs.combined_score:5.1f}  "
            f"risk={cs.risk_score:5.1f}  pos={cs.positioning_score:5.1f}  "
            f"{cs.supplier_id}  {cs.name}"
        )
        for line in cs.explanations[:6]:
            print(f"         - {line}")
        print()

    if result.graph.clusters:
        print("Similarity clusters:")
        for c in result.graph.clusters:
            print(f"  {c}")
        print()

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(result.to_json(), indent=2), encoding="utf-8"
        )
        result.dataframe.to_csv(out_dir / "scores.csv", index=False)
        print(f"Wrote report.json and scores.csv to {out_dir}")

        if args.plots:
            _write_plots(result, out_dir)

    return 0


# ---------------------------------------------------------------------------
# discover sub-command
# ---------------------------------------------------------------------------


def _cmd_discover(args: argparse.Namespace) -> int:
    from .agent import run_discovery_cycle

    queries = args.queries
    print(f"Starting discovery agent with {len(queries)} seed queries, "
          f"{args.iterations} iteration(s).")

    report = run_discovery_cycle(
        seed_queries=queries,
        iterations=args.iterations,
        risk_threshold=args.risk_threshold,
        positioning_threshold=args.pos_threshold,
        max_new_per_iter=args.max_new,
        db_path=args.db or ":memory:",
        verbose=True,
    )

    report.print_summary()

    top = report.top_suppliers(n=10, min_band="low")
    print(f"\nAll discovered suppliers ranked by combined score:")
    for cs in sorted(top, key=lambda x: x.combined_score, reverse=True):
        print(
            f"  [{cs.combined_band.upper():6}] {cs.combined_score:5.1f} "
            f"(risk={cs.risk_score:.1f}, pos={cs.positioning_score:.1f})  {cs.name}"
        )

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Full report
        full = {
            "seed_queries": report.seed_queries,
            "iterations_run": report.iterations_run,
            "store_summary": report.store_summary,
            "suppliers": [cs.as_dict() for cs in report.all_combined_scores],
            "iteration_logs": [
                {
                    "iteration": log.iteration,
                    "queries_used": log.queries_used,
                    "suppliers_found": log.suppliers_found,
                    "suppliers_new": log.suppliers_new,
                    "high_band": log.high_band,
                    "medium_band": log.medium_band,
                    "new_queries_generated": log.new_queries_generated,
                    "top_findings": log.top_findings,
                }
                for log in report.iteration_logs
            ],
        }
        (out_dir / "discovery_report.json").write_text(
            json.dumps(full, indent=2), encoding="utf-8"
        )
        print(f"\nWrote discovery_report.json to {out_dir}")

        if args.plots and report.all_combined_scores:
            # Build a minimal AnalysisResult-compatible object for visualize.
            from .pipeline import analyze_suppliers as _ap
            from .ingestion import load_suppliers_from_dicts

            sups = load_suppliers_from_dicts(
                [Supplier_dict_from_cs(cs) for cs in report.all_combined_scores]
            )
            # Re-run pipeline in batch for graph + dataframe
            from .pipeline import analyze_suppliers as ap
            ar = ap(sups)
            _write_plots(ar, out_dir)

    return 0


def Supplier_dict_from_cs(cs):
    return {
        "supplier_id": cs.supplier_id,
        "name": cs.name,
        "location": cs.location,
        "products": [],
        "payment_terms": "",
        "shipping_terms": "",
        "about_text": "",
        "source_query": cs.source_query,
        "discovery_depth": cs.discovery_depth,
    }


# ---------------------------------------------------------------------------
# Plotting helper (shared)
# ---------------------------------------------------------------------------


def _write_plots(result, out_dir: Path) -> None:
    try:
        from .visualize import plot_risk_histogram, plot_similarity_graph

        plot_risk_histogram(result, out_dir / "risk_histogram.png")
        plot_similarity_graph(result, out_dir / "similarity_graph.png")
        print(f"Wrote plots to {out_dir}")
    except ImportError as e:
        print(f"[plots] skipped — missing dependency: {e}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chemical supplier risk screening (compliance use only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subs = parser.add_subparsers(dest="command")

    # score
    sp = subs.add_parser("score", help="Score a static JSON file of suppliers.")
    sp.add_argument("input", help="Path to JSON file.")
    sp.add_argument("--out", default=None)
    sp.add_argument("--threshold", type=float, default=0.3)
    sp.add_argument("--plots", action="store_true")

    # discover
    dp = subs.add_parser("discover", help="Run iterative discovery agent.")
    dp.add_argument("queries", nargs="+", help="Seed search queries.")
    dp.add_argument("--iterations", type=int, default=3)
    dp.add_argument("--risk-threshold", type=float, default=30.0, dest="risk_threshold")
    dp.add_argument("--pos-threshold", type=float, default=30.0, dest="pos_threshold")
    dp.add_argument("--max-new", type=int, default=8, dest="max_new")
    dp.add_argument("--db", default=None, help="SQLite path (default: in-memory).")
    dp.add_argument("--out", default=None)
    dp.add_argument("--plots", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "score":
        return _cmd_score(args)
    if args.command == "discover":
        return _cmd_discover(args)

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
