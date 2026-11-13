"""Claw #1189: exact diagnostic proposals cannot approve canonical retirement."""

import csv
import hashlib
import io
import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_mim_owned_name_export import builder, read_rows, sssom_artifacts
from test_mim_owned_name_export import cli as cli
from test_mim_stable_identity import CONTRACT
from test_mim_stable_identity import stable_cli as stable_cli

PRODUCER = builder._STABLE_PRODUCER
FIXTURE = Path(__file__).parent / "resources/registry_retirement1189"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def owner_index(root, records):
    """Use the native alias index, without fabricating a complete mint ledger."""
    native = types.ModuleType("_retirement_fixture_native_ids")
    native.__file__ = str(root / "src/mediaingredientmech/stable_ids.py")
    sys.modules[native.__name__] = native
    exec(compile(CONTRACT, native.__file__, "exec"), native.__dict__)
    index = native.build_record_index(
        {str(p.relative_to(root)): record for p, record in records.items()}
    )
    return {p: record["mim_id"] for p, record in records.items()}, index


def proposal_for(root, owner, canonical, row_position):
    """Make explicitly synthetic author intent against exact fixture beforeimages."""
    evidence = root / "historical-evidence.txt"
    evidence.write_text("Synthetic evidence: obsolete generated row, not scientific approval.\n")
    rows = read_rows(canonical.read_bytes())
    proposal = {
        "schema_version": 1,
        "capability": "stable-registry-retirement-proposal-v1",
        "scope": "diagnostic_candidate_only",
        "author": "synthetic-test-author",
        "scientific_approval": False,
        "canonical": {
            "path": str(canonical.relative_to(root)),
            "sha256": sha(canonical.read_bytes()),
        },
        "evidence_inputs": {evidence.name: sha(evidence.read_bytes())},
        "entries": [
            {
                "row_position": row_position,
                "row": rows[row_position - 1],
                "owner": {
                    "path": str(owner.relative_to(root)),
                    "sha256": sha(owner.read_bytes()),
                    "mim_id": yaml.safe_load(owner.read_bytes())["mim_id"],
                },
                "reason": "Synthetic exact-row proposal; independent publication reviews still required.",
                "evidence": [evidence.name],
            }
        ],
    }
    return proposal


def evidence(root, proposal, owner, canonical):
    path = root / "retirement.json"
    raw = encode(proposal)
    captured = {
        path: raw,
        owner: owner.read_bytes(),
        canonical: canonical.read_bytes(),
        **{root / name: (root / name).read_bytes() for name in proposal["evidence_inputs"]},
    }
    return PRODUCER.registry_retirement_evidence(root, path, raw, sha(raw), captured)


@pytest.fixture
def stock(tmp_path):
    origin = json.loads((FIXTURE / "ORIGIN.json").read_bytes())
    raw = (FIXTURE / "Sodium_Nitrate_070_M_Stock.yaml").read_bytes()
    table = (FIXTURE / "canonical-stock-rows.tsv").read_bytes()
    assert sha(raw) == origin["owner"]["sha256"]
    assert sha(table) == origin["canonical"]["extracted_sha256"]
    owner = tmp_path / origin["owner"]["path"]
    owner.parent.mkdir(parents=True)
    owner.write_bytes(raw)
    canonical = tmp_path / "mappings/ingredient_mappings.sssom.tsv"
    canonical.parent.mkdir()
    canonical.write_bytes(table)
    record = yaml.safe_load(raw)
    records = {owner: record}
    # Compatibility-unit fixture uses the actual native owner index. It does
    # not pretend this one-owner extraction is the full sequential registry.
    subjects, index = owner_index(tmp_path, records)
    rows = read_rows(table)
    position = next(
        i
        for i, row in enumerate(rows, 1)
        if row["object_id"] == "kgmicrobe.compound:sodium_nitrate_070_m_stock"
    )
    proposal = proposal_for(tmp_path, owner, canonical, position)
    return tmp_path, owner, canonical, records, subjects, index, proposal


def test_1189_real_stock_default_conflict_and_explicit_diagnostic_proposal(stock):
    root, owner, canonical, records, subjects, index, proposal = stock
    before = canonical.read_bytes()
    with pytest.raises(ValueError, match="Competing registry namespaces"):
        PRODUCER.compatibility_registry_objects(records, subjects, index, before)
    bound = evidence(root, proposal, owner, canonical)
    objects = PRODUCER.compatibility_registry_objects(
        records, subjects, index, before, retirement=bound, root=root
    )
    assert objects == {"MIM:0002332": ("kgmicrobe.ingredient:sodium_nitrate_~28070_m_stock~29",)}
    rows = builder._row_from_yaml(
        owner,
        {},
        {},
        {},
        {"CHEBI:63005": "sodium nitrate"},
        record=records[owner],
        owners={},
        stable_subject="MIM:0002332",
        registry_objects=objects["MIM:0002332"],
    )
    assert {(r["predicate_id"], r["object_id"]) for r in rows} == {
        ("skos:exactMatch", "kgmicrobe.ingredient:sodium_nitrate_~28070_m_stock~29"),
        ("skos:broadMatch", "CHEBI:63005"),
    }
    assert (
        bound["content"]["entries"][0]["row"]["comment"] == proposal["entries"][0]["row"]["comment"]
    )
    assert bound["scientific_approval_added"] is False
    assert canonical.read_bytes() == before
    assert all(not row["validation_method"] for row in rows)


@pytest.mark.parametrize(
    "change",
    [
        "row",
        "position",
        "owner",
        "mim_id",
        "owner_hash",
        "canonical_hash",
        "evidence_hash",
        "reason",
        "empty_evidence",
        "approval",
        "duplicate",
        "unknown",
        "nonregistry",
        "curated_primary",
        "unused_position",
        "path",
        "canonical_pin_conflict",
    ],
)
def test_1189_invalid_or_rehashed_proposals_cannot_exclude_rows(stock, change):
    root, owner, canonical, records, subjects, index, proposal = stock
    entry = proposal["entries"][0]
    if change == "row":
        entry["row"]["comment"] += " changed"
    elif change == "position":
        entry["row_position"] = 0
    elif change == "owner":
        entry["owner"]["path"] = "other.yaml"
    elif change == "mim_id":
        entry["owner"]["mim_id"] = "MIM:0000001"
    elif change == "owner_hash":
        entry["owner"]["sha256"] = "0" * 64
    elif change == "canonical_hash":
        proposal["canonical"]["sha256"] = "0" * 64
    elif change == "evidence_hash":
        proposal["evidence_inputs"]["historical-evidence.txt"] = "0" * 64
    elif change == "reason":
        entry["reason"] = ""
    elif change == "empty_evidence":
        entry["evidence"] = []
    elif change == "approval":
        proposal["scientific_approval"] = True
    elif change == "duplicate":
        proposal["entries"].append(deepcopy(entry))
    elif change in {"unknown", "nonregistry", "curated_primary"}:
        rows = read_rows(canonical.read_bytes())
        if change == "unknown":
            rows[entry["row_position"] - 1]["subject_id"] = "MIM:Unowned"
        else:
            entry["row_position"] = next(
                i
                for i, r in enumerate(rows, 1)
                if r["object_id"].startswith(
                    "CHEBI:" if change == "nonregistry" else "kgmicrobe.ingredient:"
                )
            )
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
        canonical.write_text(buf.getvalue())
        proposal["canonical"]["sha256"] = sha(canonical.read_bytes())
        entry["row"] = rows[entry["row_position"] - 1]
    elif change == "unused_position":
        entry["row_position"] = 99
    elif change == "path":
        entry["owner"]["path"] = "../escape.yaml"
    elif change == "canonical_pin_conflict":
        proposal["evidence_inputs"]["mappings/ingredient_mappings.sssom.tsv"] = "0" * 64
    before = canonical.read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        bound = evidence(root, proposal, owner, canonical)
        PRODUCER.compatibility_registry_objects(
            records, subjects, index, before, retirement=bound, root=root
        )
    assert canonical.read_bytes() == before


def test_1189_proposal_cannot_hide_ambiguous_subject_or_another_conflict(stock):
    root, owner, canonical, records, subjects, index, proposal = stock
    other = deepcopy(records[owner])
    other["mim_id"] = "MIM:0000001"
    otherpath = root / "data/ingredients/mapped/Other.yaml"
    both = {**records, otherpath: other}
    both_subjects, ambiguous = owner_index(root, both)
    original = canonical.read_bytes()
    legacy = original.replace(b"MIM:0002332", b"MIM:Sodium_Nitrate_070_M_Stock")
    canonical.write_bytes(legacy)
    legacy_proposal = deepcopy(proposal)
    legacy_proposal["canonical"]["sha256"] = sha(legacy)
    legacy_proposal["entries"][0]["row"] = read_rows(legacy)[
        proposal["entries"][0]["row_position"] - 1
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        PRODUCER.compatibility_registry_objects(
            both,
            both_subjects,
            ambiguous,
            canonical.read_bytes(),
            retirement=evidence(root, legacy_proposal, owner, canonical),
            root=root,
        )
    canonical.write_bytes(original)
    rows = read_rows(canonical.read_bytes())
    extra = dict(rows[proposal["entries"][0]["row_position"] - 1])
    extra["object_id"] += "_unreviewed"
    rows.append(extra)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    canonical.write_text(buf.getvalue())
    proposal["canonical"]["sha256"] = sha(canonical.read_bytes())
    with pytest.raises(ValueError, match="Competing"):
        PRODUCER.compatibility_registry_objects(
            records,
            subjects,
            index,
            canonical.read_bytes(),
            retirement=evidence(root, proposal, owner, canonical),
            root=root,
        )


def test_1189_same_namespace_escaped_and_mixed_case_aliases_remain(stock):
    root, owner, canonical, records, subjects, index, proposal = stock
    rows = read_rows(canonical.read_bytes())
    extra = dict(rows[proposal["entries"][0]["row_position"] - 1])
    extra["object_id"] = "kgmicrobe.ingredient:Mixed_Legacy_~28Stock~29"
    rows.append(extra)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    canonical.write_text(buf.getvalue())
    proposal["canonical"]["sha256"] = sha(canonical.read_bytes())
    objects = PRODUCER.compatibility_registry_objects(
        records,
        subjects,
        index,
        canonical.read_bytes(),
        retirement=evidence(root, proposal, owner, canonical),
        root=root,
    )
    assert objects["MIM:0002332"] == (
        "kgmicrobe.ingredient:Mixed_Legacy_~28Stock~29",
        "kgmicrobe.ingredient:sodium_nitrate_~28070_m_stock~29",
    )


def cli_proposal(stable_cli, monkeypatch):
    root = stable_cli["root"]
    owner = stable_cli["records"] / "Subject.yaml"
    record = yaml.safe_load(owner.read_bytes())
    record["identifier"] = "kgmicrobe.ingredient:Curated_~28Stock~29"
    owner.write_text(yaml.safe_dump(record))
    old = stable_cli["canonical"]
    canonical = old.with_name("ingredient_mappings.sssom.tsv")
    old.rename(canonical)
    stable_cli["canonical"] = canonical
    monkeypatch.setattr(builder, "MIM_PUBLISHED_SSSOM", canonical)
    rows = read_rows(canonical.read_bytes())
    rows[0].update(
        subject_id=record["mim_id"],
        predicate_id="skos:exactMatch",
        object_id="kgmicrobe.compound:obsolete",
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    canonical.write_text(buf.getvalue())
    path = root / "retirement.json"
    proposal = proposal_for(root, owner, canonical, 1)
    path.write_bytes(encode(proposal))
    return path, proposal


def test_1189_native_cli_retains_full_proposal_closure_without_canonical_change(
    stable_cli, monkeypatch
):
    path, proposal = cli_proposal(stable_cli, monkeypatch)
    before = stable_cli["canonical"].read_bytes()
    with pytest.raises(ValueError, match="Competing"):
        stable_cli["run"]()
    output, sidecar, manifest = stable_cli["run"](
        "--registry-retirement-proposal",
        str(path),
        "--registry-retirement-proposal-sha256",
        sha(path.read_bytes()),
    )
    observed = json.loads(manifest.read_bytes())
    assert observed["registry_retirement_proposal"]["content"] == proposal
    assert observed["registry_retirement_proposal"]["scientific_approval_added"] is False
    pins = {r["path"]: r["sha256"] for r in observed["source_inputs"]}
    assert pins[str(path)] == sha(path.read_bytes())
    assert (
        pins[str(stable_cli["root"] / "historical-evidence.txt")]
        == proposal["evidence_inputs"]["historical-evidence.txt"]
    )
    assert stable_cli["canonical"].read_bytes() == before
    assert not any(
        row["object_id"] == "kgmicrobe.compound:obsolete" for row in read_rows(output.read_bytes())
    )
    assert sidecar.is_file()


@pytest.mark.parametrize("kind", ["proposal", "evidence"])
def test_1189_late_proposal_or_evidence_drift_preserves_all_beforeimages(
    stable_cli, monkeypatch, kind
):
    path, proposal = cli_proposal(stable_cli, monkeypatch)
    flags = (
        "--registry-retirement-proposal",
        str(path),
        "--registry-retirement-proposal-sha256",
        sha(path.read_bytes()),
    )
    outputs = stable_cli["run"](*flags)
    before = [p.read_bytes() for p in outputs]
    native = sssom_artifacts.ValidatedWriteTransaction

    class Drift(native):
        def commit(self, **kwargs):
            target = path if kind == "proposal" else stable_cli["root"] / "historical-evidence.txt"
            target.write_bytes(target.read_bytes() + b" ")
            return super().commit(**kwargs)

    monkeypatch.setattr(sssom_artifacts, "ValidatedWriteTransaction", Drift)
    with pytest.raises(Exception, match="changed during generation"):
        stable_cli["run"](*flags)
    assert [p.read_bytes() for p in outputs] == before


@pytest.mark.parametrize("input_kind", ["proposal", "evidence"])
@pytest.mark.parametrize("artifact", ["sssom", "sidecar", "manifest"])
def test_1189_every_artifact_refuses_proposal_or_evidence_overlap(
    stable_cli, monkeypatch, input_kind, artifact
):
    path, proposal = cli_proposal(stable_cli, monkeypatch)
    target = path if input_kind == "proposal" else stable_cli["root"] / "historical-evidence.txt"
    before = target.read_bytes()
    flags = [
        "--registry-retirement-proposal",
        str(path),
        "--registry-retirement-proposal-sha256",
        sha(path.read_bytes()),
    ]
    destinations = {
        "sssom": target.parent / "fresh-candidate.tsv",
        "sidecar": target.parent / "fresh-suppressions.tsv",
        "manifest": target.parent / "fresh-generation.json",
    }
    destinations[artifact] = target
    for name, flag in [
        ("sssom", "--output"),
        ("sidecar", "--suppressed-aliases-output"),
        ("manifest", "--generation-manifest-output"),
    ]:
        flags.extend([flag, str(destinations[name])])
    with pytest.raises(ValueError, match="protected|overlap|input"):
        stable_cli["run"](*flags)
    assert target.read_bytes() == before
    assert all(not p.exists() for p in destinations.values() if p != target)
    assert not stable_cli["output"].exists()


def test_1189_proposal_changed_between_enumeration_and_snapshot_refuses(stable_cli, monkeypatch):
    path, proposal = cli_proposal(stable_cli, monkeypatch)
    digest = sha(path.read_bytes())
    original = builder.capture_beforeimages
    changed = []

    def capture(paths):
        paths = tuple(paths)
        if path in paths and len(paths) > 1 and not changed:
            path.write_bytes(path.read_bytes() + b" ")
            changed.append(True)
        return original(paths)

    monkeypatch.setattr(builder, "capture_beforeimages", capture)
    canonical = stable_cli["canonical"].read_bytes()
    with pytest.raises(ValueError, match="capture is incomplete"):
        stable_cli["run"](
            "--registry-retirement-proposal",
            str(path),
            "--registry-retirement-proposal-sha256",
            digest,
        )
    assert changed == [True]
    assert stable_cli["canonical"].read_bytes() == canonical
    assert not stable_cli["output"].exists()


@pytest.mark.parametrize("kind", ["missing_digest", "wrong_digest", "legacy"])
def test_1189_retirement_options_are_explicit_and_stable_only(stable_cli, monkeypatch, kind):
    path, proposal = cli_proposal(stable_cli, monkeypatch)
    flags = ["--registry-retirement-proposal", str(path)]
    if kind != "missing_digest":
        flags += [
            "--registry-retirement-proposal-sha256",
            "0" * 64 if kind == "wrong_digest" else sha(path.read_bytes()),
        ]
    if kind == "legacy":
        flags += ["--identity-mode", "legacy", "--mim-stable-id-contract-sha256", ""]
    with pytest.raises((ValueError, SystemExit)):
        stable_cli["run"](*flags)
    assert not stable_cli["output"].exists()


@pytest.mark.parametrize("legacy_subject", [False, True])
def test_1190_selected_numeric_registry_identity_is_refused(stock, legacy_subject):
    """Exact proposal rehashing cannot hide a numeric registry identity."""
    root, owner, canonical, records, subjects, index, proposal = stock
    owner_before = owner.read_bytes()
    rows = read_rows(canonical.read_bytes())
    entry = proposal["entries"][0]
    row = rows[entry["row_position"] - 1]
    row["object_id"] = "kgmicrobe.compound:0002332"
    if legacy_subject:
        row["subject_id"] = "MIM:Sodium_Nitrate_070_M_Stock"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    canonical.write_text(buf.getvalue())
    proposal["canonical"]["sha256"] = sha(canonical.read_bytes())
    entry["row"] = dict(row)
    before = canonical.read_bytes()
    with pytest.raises(ValueError, match="Competing registry namespaces|Numeric MIM suffix"):
        PRODUCER.compatibility_registry_objects(records, subjects, index, before)
    bound = evidence(root, proposal, owner, canonical)
    with pytest.raises(ValueError, match="Numeric MIM suffix is not a registry identity"):
        PRODUCER.compatibility_registry_objects(
            records, subjects, index, before, retirement=bound, root=root
        )
    assert canonical.read_bytes() == before
    assert owner.read_bytes() == owner_before
