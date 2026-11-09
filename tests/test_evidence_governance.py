"""Evidence runners and workflows cannot drift from declared adoption (#687)."""
from dataclasses import replace

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_governance import (
    GovernanceError,
    _validate_fleet_alignment,
    load_governance_manifest,
)


def test_evidence_artifacts_apply_exactly_to_enabled_mechs():
    fleet = load_fleet_manifest()
    governance = load_governance_manifest()
    expected = set(fleet.with_capability("evidence_reference_validation"))
    for name in ("evidence_validator_runner", "evidence_validation_workflow"):
        artifact = next(a for a in governance.artifacts if a.artifact_id == name)
        assert set(artifact.consumers) == expected


@pytest.mark.parametrize("name", ["evidence_validator_runner", "evidence_validation_workflow"])
@pytest.mark.parametrize("change", ["missing", "broadened"])
def test_missing_or_unadopted_evidence_artifacts_are_rejected(name, change):
    governance = load_governance_manifest()
    artifacts = tuple(
        replace(a, consumers=tuple(governance.consumers)) if a.artifact_id == name else a
        for a in governance.artifacts if change != "missing" or a.artifact_id != name
    )
    with pytest.raises(GovernanceError, match="evidence capability"):
        _validate_fleet_alignment(replace(governance, artifacts=artifacts), load_fleet_manifest())
