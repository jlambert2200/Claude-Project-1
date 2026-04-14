"""
Optional visualization helpers.

matplotlib / networkx are imported lazily so the rest of the pipeline
can run in environments that don't have them installed.
"""

from __future__ import annotations

from pathlib import Path

from .pipeline import AnalysisResult


def plot_risk_histogram(result: AnalysisResult, out_path: str | Path) -> str:
    """Histogram of risk scores across all suppliers."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scores = [s.risk_score for s in result.scores]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(scores, bins=10, range=(0, 100), edgecolor="black")
    ax.set_xlabel("Risk score")
    ax.set_ylabel("Supplier count")
    ax.set_title("Chemical supplier risk score distribution")
    ax.axvline(30, color="orange", linestyle="--", linewidth=1, label="medium band")
    ax.axvline(60, color="red", linestyle="--", linewidth=1, label="high band")
    ax.legend()
    fig.tight_layout()
    out_path = str(out_path)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_similarity_graph(result: AnalysisResult, out_path: str | Path) -> str:
    """Spring-layout drawing of the similarity graph."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    g = nx.Graph()
    for node in result.graph.nodes:
        g.add_node(node)
    for e in result.graph.edges:
        g.add_edge(e.source, e.target, weight=e.jaccard)

    # Colour nodes by risk band.
    band_colour = {"low": "#4caf50", "medium": "#ff9800", "high": "#f44336"}
    colours = []
    score_by_id = {s.supplier_id: s for s in result.scores}
    for n in g.nodes():
        s = score_by_id.get(n)
        colours.append(band_colour.get(s.risk_band if s else "low", "#cccccc"))

    pos = nx.spring_layout(g, seed=42)
    fig, ax = plt.subplots(figsize=(8, 6))
    nx.draw_networkx_nodes(g, pos, node_color=colours, node_size=500, ax=ax)
    nx.draw_networkx_edges(g, pos, alpha=0.4, ax=ax)
    nx.draw_networkx_labels(g, pos, font_size=7, ax=ax)
    ax.set_title("Supplier similarity graph (Jaccard on product sets)")
    ax.axis("off")
    fig.tight_layout()
    out_path = str(out_path)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
