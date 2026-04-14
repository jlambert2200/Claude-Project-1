"""
Command-line entry point.

Usage:
    python -m chemical_risk.cli examples/sample_suppliers.json
    python -m chemical_risk.cli examples/sample_suppliers.json --out out/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import analyze_suppliers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Chemical supplier behavioral-risk screening prototype (compliance use only).",
    )
    parser.add_argument("input", help="Path to JSON file of supplier listings.")
    parser.add_argument("--out", default=None, help="Output directory for JSON report and optional plots.")
    parser.add_argument("--threshold", type=float, default=0.3, help="Jaccard threshold for similarity graph.")
    parser.add_argument("--plots", action="store_true", help="Render histogram and graph PNGs (requires matplotlib + networkx).")
    args = parser.parse_args(argv)

    result = analyze_suppliers(args.input, graph_threshold=args.threshold)

    # Console summary -------------------------------------------------------
    print(f"Analyzed {len(result.scores)} suppliers\n")
    for s in sorted(result.scores, key=lambda x: x.risk_score, reverse=True):
        print(f"[{s.risk_band.upper():6}] {s.risk_score:5.1f}  {s.supplier_id}  {s.name}")
        for line in s.explanations[:6]:
            print(f"         - {line}")
        print()

    if result.graph.clusters:
        print("Similarity clusters:")
        for c in result.graph.clusters:
            print(f"  {c}")
        print()

    # Outputs ---------------------------------------------------------------
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(result.to_json(), indent=2), encoding="utf-8"
        )
        result.dataframe.to_csv(out_dir / "scores.csv", index=False)
        print(f"Wrote report.json and scores.csv to {out_dir}")

        if args.plots:
            try:
                from .visualize import plot_risk_histogram, plot_similarity_graph

                plot_risk_histogram(result, out_dir / "risk_histogram.png")
                plot_similarity_graph(result, out_dir / "similarity_graph.png")
                print(f"Wrote plots to {out_dir}")
            except ImportError as e:  # pragma: no cover
                print(f"[plots] skipped — missing dependency: {e}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
