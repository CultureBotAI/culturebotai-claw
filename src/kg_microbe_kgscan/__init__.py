"""kg_microbe_kgscan — literature knowledge-gap scanner for the Mech repos.

Generalized port of DisMech's scripts/knowledge_gap_scan.py + literature_scan.py.
For each record (config-driven glob), queries Europe PMC (free) for recent
literature whose abstracts carry "knowledge-gap" signal language about the
record's topic, scores it, and proposes a `Discussion(kind=KNOWLEDGE_GAP)` —
emitting a triage packet by default, or (with --apply) appending the Discussion
to the record YAML. See scan.py.
"""
