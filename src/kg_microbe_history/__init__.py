"""Append-only curation-history records shared across the Mech repos.

Generalized port of monarch-initiative/dismech's ``scripts/new_history.py`` and
its ``history/`` layer. One record per session per target, scaffolded (never
hand-written) into::

    history/<kind-dir>/<slug>/<TIMESTAMP>-<actor>-<shortid>.yaml

The unguessable ``shortid`` plus directory-per-slug layout is the design: two
agents curating the same record concurrently cannot write the same file, so the
layer has no merge-conflict surface. That property is why this is worth porting
ahead of any autonomous-agent workflow — see docs/AUTONOMOUS_LOOPS.md.

CLI::

    python -m kg_microbe_history new --kind record --slug <SLUG> \
        --event EDIT --outcome changed --summary "..." --details "..."
    python -m kg_microbe_history validate <path-or-dir>

Depends only on the standard library plus PyYAML, matching kg_microbe_kgscan, so
it runs in CI without a repo-specific environment.
"""

from .scaffold import KIND_DIRS, build_record, new_history_path, write_record

__all__ = ["KIND_DIRS", "build_record", "new_history_path", "write_record"]
