"""Captured owner references for unified comparisons, never source identity approval."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from kg_microbe_utils.sssom_artifacts import capture_beforeimages, checked_path
from kg_microbe_utils.stable_mim import identity_snapshot, load_owner_record


class OwnerInputs:
    """Keep native identity validation separate from the legacy mapping resolver.

    A wholly pre-ID corpus keeps blank references. Any ID field or ledger makes
    the complete corpus a native stable-ID input, requiring a caller-selected
    contract digest. The digest is executable-input qualification, not science.
    """

    def __init__(
        self, root: Path, paths: Iterable[Path], contract_sha256: str | None = None,
    ) -> None:
        self.root = checked_path(root)
        self.paths = tuple(checked_path(path) for path in paths)
        mint = self.root / 'data/ids/mim_id_registry.tsv'
        lifecycle = self.root / 'data/ids/mim_id_lifecycle.tsv'
        self.captured = capture_beforeimages([*self.paths, mint, lifecycle])
        self.records: dict[Path, Any] = {}
        for path in self.paths:
            raw = self.captured[path]
            if raw is None:
                raise ValueError(f'MIM owner disappeared: {path}')
            # Reject duplicate keys even before deciding whether IDs are absent;
            # malformed input cannot establish a wholly pre-ID legacy corpus.
            self.records[path] = load_owner_record(raw)
        self.subjects: dict[Path, str] = {}
        self.native_prefix: str | None = None
        stable = (
            contract_sha256 is not None
            or self.captured[mint] is not None
            or self.captured[lifecycle] is not None
            or any(isinstance(value, dict) and 'mim_id' in value
                   for value in self.records.values())
        )
        if not stable:
            return
        if not contract_sha256:
            raise ValueError('Current MIM IDs require --mim-stable-id-contract-sha256')
        source_path = self.root / 'src/mediaingredientmech/stable_ids.py'
        self.captured.update(capture_beforeimages([source_path]))
        source = self.captured[source_path]
        if source is None or self.captured[mint] is None or self.captured[lifecycle] is None:
            raise ValueError('Current MIM owner references require native source and both ledgers')
        if any(not isinstance(value, dict) for value in self.records.values()):
            raise ValueError('Every current MIM owner must be a YAML mapping')
        self.subjects, _, self.native_prefix = identity_snapshot(
            self.root, self.records, self.captured[mint], self.captured[lifecycle],
            source, source_path, contract_sha256,
        )
        self.check(self.paths)

    def check(self, paths: Iterable[Path]) -> None:
        """Recheck the complete original inventory, bytes and absence observations."""
        if tuple(checked_path(path) for path in paths) != self.paths:
            raise ValueError('MIM owner inventory changed during unified comparison')
        if capture_beforeimages(self.captured) != self.captured:
            raise ValueError('MIM owner/native identity inputs changed during unified comparison')
