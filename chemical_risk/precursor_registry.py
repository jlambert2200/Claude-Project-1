"""
Monitored-chemicals registry (INCB-style, compliance-only).

This is a *small, illustrative* reference list inspired by the public
structure of the International Narcotics Control Board (INCB) precursor
tables and similar compliance frameworks. It is a prototype — NOT a
regulatory authoritative source. A real deployment must pull from the
current INCB Red List and from the user's own jurisdictional lists.

What each entry contains (deliberately minimal):
    - canonical_name : the chemical's canonical name
    - cas            : CAS Registry Number
    - category       : a generic compliance-oriented label
                       (one of: "monitored_precursor", "solvent",
                        "oxidizer", "acid", "reagent", "benign")
    - synonyms       : alternate / trade names used in listings
    - severity       : 1 (benign) ... 3 (precursor-class monitored)

What each entry DOES NOT contain:
    - any synthesis pathway
    - any "this substance can be used to make X" mapping
    - any dosage, ratio, or process parameter

The prototype only needs names, IDs, and category — that is enough to
detect *whether a supplier is advertising monitored categories*, which is
the compliance-relevant signal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegistryEntry:
    canonical_name: str
    cas: str
    category: str
    synonyms: tuple[str, ...]
    severity: int  # 1..3


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
# Severity 3 = publicly listed monitored precursor class (INCB-style).
# Severity 2 = broadly controlled solvent/oxidizer/acid on watch lists.
# Severity 1 = benign / ubiquitous industrial chemicals (included so the
#              system can differentiate a chemistry supplier from a
#              "monitored-heavy" one — a normal catalog should have lots
#              of severity 1 entries).

REGISTRY: tuple[RegistryEntry, ...] = (
    # --- Severity 3: INCB-style monitored precursor classes -----------------
    RegistryEntry(
        canonical_name="acetic anhydride",
        cas="108-24-7",
        category="monitored_precursor",
        synonyms=("acetic acid anhydride", "ethanoic anhydride", "Ac2O"),
        severity=3,
    ),
    RegistryEntry(
        canonical_name="potassium permanganate",
        cas="7722-64-7",
        category="monitored_precursor",
        synonyms=("KMnO4", "permanganate of potash"),
        severity=3,
    ),
    RegistryEntry(
        canonical_name="ephedrine",
        cas="299-42-3",
        category="monitored_precursor",
        synonyms=("l-ephedrine", "ephedrine HCl"),
        severity=3,
    ),
    RegistryEntry(
        canonical_name="pseudoephedrine",
        cas="90-82-4",
        category="monitored_precursor",
        synonyms=("d-pseudoephedrine", "pseudoephedrine hydrochloride"),
        severity=3,
    ),
    RegistryEntry(
        canonical_name="safrole",
        cas="94-59-7",
        category="monitored_precursor",
        synonyms=("shikimol", "sassafras oil component"),
        severity=3,
    ),
    RegistryEntry(
        canonical_name="piperonal",
        cas="120-57-0",
        category="monitored_precursor",
        synonyms=("heliotropin", "3,4-methylenedioxybenzaldehyde"),
        severity=3,
    ),
    RegistryEntry(
        canonical_name="phenylacetic acid",
        cas="103-82-2",
        category="monitored_precursor",
        synonyms=("alpha-toluic acid", "benzeneacetic acid", "PAA"),
        severity=3,
    ),
    RegistryEntry(
        canonical_name="norephedrine",
        cas="14838-15-4",
        category="monitored_precursor",
        synonyms=("phenylpropanolamine", "PPA"),
        severity=3,
    ),

    # --- Severity 2: broadly watch-listed solvents / oxidizers / acids ------
    RegistryEntry(
        canonical_name="acetone",
        cas="67-64-1",
        category="solvent",
        synonyms=("propan-2-one", "dimethyl ketone", "2-propanone"),
        severity=2,
    ),
    RegistryEntry(
        canonical_name="toluene",
        cas="108-88-3",
        category="solvent",
        synonyms=("methylbenzene", "toluol"),
        severity=2,
    ),
    RegistryEntry(
        canonical_name="methyl ethyl ketone",
        cas="78-93-3",
        category="solvent",
        synonyms=("MEK", "butanone", "2-butanone"),
        severity=2,
    ),
    RegistryEntry(
        canonical_name="diethyl ether",
        cas="60-29-7",
        category="solvent",
        synonyms=("ether", "ethyl ether"),
        severity=2,
    ),
    RegistryEntry(
        canonical_name="hydrochloric acid",
        cas="7647-01-0",
        category="acid",
        synonyms=("HCl", "muriatic acid"),
        severity=2,
    ),
    RegistryEntry(
        canonical_name="sulfuric acid",
        cas="7664-93-9",
        category="acid",
        synonyms=("H2SO4", "oil of vitriol"),
        severity=2,
    ),

    # --- Severity 1: benign / ubiquitous (used as negative controls) --------
    RegistryEntry(
        canonical_name="sodium chloride",
        cas="7647-14-5",
        category="benign",
        synonyms=("table salt", "NaCl"),
        severity=1,
    ),
    RegistryEntry(
        canonical_name="glucose",
        cas="50-99-7",
        category="benign",
        synonyms=("dextrose", "d-glucose"),
        severity=1,
    ),
    RegistryEntry(
        canonical_name="citric acid",
        cas="77-92-9",
        category="benign",
        synonyms=("2-hydroxypropane-1,2,3-tricarboxylic acid",),
        severity=1,
    ),
    RegistryEntry(
        canonical_name="ethanol",
        cas="64-17-5",
        category="solvent",
        synonyms=("ethyl alcohol", "EtOH"),
        severity=1,
    ),
    RegistryEntry(
        canonical_name="isopropanol",
        cas="67-63-0",
        category="solvent",
        synonyms=("IPA", "2-propanol", "isopropyl alcohol"),
        severity=1,
    ),
)


# Convenience indexes built once -------------------------------------------

BY_CAS: dict[str, RegistryEntry] = {e.cas: e for e in REGISTRY}

# Map every lowercased (canonical + synonym) string to its entry.
BY_NAME: dict[str, RegistryEntry] = {}
for _entry in REGISTRY:
    BY_NAME[_entry.canonical_name.lower()] = _entry
    for _syn in _entry.synonyms:
        BY_NAME[_syn.lower()] = _entry


MONITORED_CATEGORIES: set[str] = {"monitored_precursor", "solvent", "oxidizer", "acid"}


def all_entries() -> tuple[RegistryEntry, ...]:
    return REGISTRY
