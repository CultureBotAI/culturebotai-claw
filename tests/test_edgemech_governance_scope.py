"""Edge ledger admission does not assert native record/skill adoption (#959)."""

from kg_microbe_governance import load_governance_manifest

NATIVE_ADOPTION = {
    "skill_frontmatter_contract", "curation_timestamp_contract", "record_review_contract",
}


def test_edge_ledger_keeps_shared_contracts_without_invented_native_record_adoption():
    registry = load_governance_manifest()
    edge = registry.consumer_for("edgemech")
    applicable = {item.artifact_id for item in registry.artifacts_for(edge)}
    assert not applicable & NATIVE_ADOPTION
    assert {
        "shared_mech_schema", "curation_history_schema", "record_review_schema",
        "record_review_helper", "record_review_guide", "vendored_checker",
        "id_label_empty_adapter_contract", "id_label_unknown_prefix_contract",
    } <= applicable
    # This scope change must not remove an existing native consumer's contracts.
    for key, consumer in registry.consumers.items():
        if key != "edgemech":
            assert NATIVE_ADOPTION <= {item.artifact_id for item in registry.artifacts_for(consumer)}
