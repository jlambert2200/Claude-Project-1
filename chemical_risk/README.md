# chemical_risk

A prototype pipeline that flags **behavioral risk signals** in chemical
supplier listings (Chinese B2B marketplaces such as 1688 / Alibaba-style
catalogs). It is intended for **compliance, policy research, and due-diligence**
use only. The system does not produce synthesis information, does not rank
chemicals by "usefulness for misuse," and does not suggest sourcing.

## What it does

Given a set of supplier listings (JSON or HTML-like), the pipeline:

1. **Ingests** raw listings (`ingestion.py`).
2. **Normalizes** product names into canonical chemicals via CAS, synonyms,
   and fuzzy matching (`normalization.py`).
3. **Matches** against a small INCB-style registry of monitored chemicals
   (`precursor_registry.py`).
4. **Computes** 14 numeric features across 5 categories (`features.py`):
   product signals, catalog structure, commercial language, transactional
   cues, and localization.
5. **Scores** each supplier with a transparent weighted-sum model
   (`scoring.py`) and emits human-readable explanations for every score.
6. **Builds** a supplier similarity graph via Jaccard on product sets
   (`network.py`) and reports connected-component clusters.
7. **Outputs** a pandas DataFrame, a JSON report, and optional plots
   (`visualize.py`).

## Quick start

```bash
pip install pandas             # required
pip install matplotlib networkx # optional, for --plots

python -m chemical_risk.cli examples/sample_suppliers.json --out out/ --plots
```

Or programmatically:

```python
from chemical_risk import analyze_suppliers

result = analyze_suppliers("examples/sample_suppliers.json")
print(result.dataframe[["supplier_id", "name", "risk_score", "risk_band"]])

for s in result.scores:
    print(s.name, s.risk_band, s.risk_score)
    for line in s.explanations:
        print("  -", line)
```

## Feature / weight reference

| Family | Feature | Weight | Intuition |
| ------ | ------- | -----: | --------- |
| A | `n_monitored_precursors`     |  +8  | Number of INCB-style precursor-class matches |
| A | `category_diversity`         |  +2  | Breadth across monitored categories |
| A | `precursor_co_occurrence`    | +10  | ≥2 severity-3 hits in one catalog |
| A | `max_severity`               |  +2  | Highest severity match |
| B | `pct_vague_names`            | +20  | Share of catalog using placeholder names |
| C | `commercial_language_hits`   |  +3  | "custom synthesis" / "research use" phrasing |
| D | `transactional_hits`         |  +5  | Crypto / wire-only / Western Union cues |
| D | `shipping_red_flag_hits`     |  +6  | "discreet", "relabel", "plain package" |
| D | `explicit_evasion_language`  | +15  | Language about bypassing customs |
| E | `export_oriented_hits`       |  +1  | Heavy export/DDP framing |
| - | `pct_with_cas`               |  −5  | **Anti-signal**: disclosing CAS is good practice |

Bands: `low` < 30 ≤ `medium` < 60 ≤ `high`.

## Limitations (important)

- The registry here is **illustrative**, not authoritative. Production use
  must ingest current INCB Red List + jurisdictional watch lists.
- Weights are set by inspection, not learned. This is a feature for
  auditability, not a bug — but it does mean the absolute score is only
  meaningful relative to other suppliers in the same batch.
- Keyword-based NLP is shallow. Adversarial suppliers can rephrase. Treat
  the output as triage, not a verdict.
- A high score means "worth a human analyst's attention," not "guilty."
