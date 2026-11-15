"""Native review contracts for diagnostic invalid-CAS dispositions (#1193)."""

import csv
import hashlib
import io
import json
import subprocess
import types
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_mim_owned_name_export import builder, read_rows, sssom_artifacts
from test_mim_owned_name_export import cli as cli
from test_mim_stable_identity import stable_cli as stable_cli
from test_registry_retirement_proposal import owner_index

P = builder._STABLE_PRODUCER
FIXTURE = Path(__file__).parent / "resources/cas_dispositions1193"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()


def table(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream, fieldnames=builder.COLUMNS, delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def put(root, name, raw):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def native_fixture(root):
    origin = json.loads((FIXTURE / "ORIGIN.json").read_bytes())
    for item in origin["native"]:
        raw = (FIXTURE / item["file"]).read_bytes()
        assert sha(raw) == item["sha256"]
        put(root, item["path"], raw)
    native = types.ModuleType("captured_review_fixture")
    native.__file__ = str(root / "scripts/record_review.py")
    exec(
        compile(
            (root / "scripts/record_review.py").read_bytes(), native.__file__, "exec"
        ),
        native.__dict__,
    )
    for args in (
        ("init",),
        ("config", "user.name", "Synthetic fixture"),
        ("config", "user.email", "fixture@example.invalid"),
        (
            "remote",
            "add",
            "origin",
            "https://github.com/CultureBotAI/MediaIngredientMech.git",
        ),
        ("add", "."),
        ("commit", "-m", "Synthetic source baseline"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    return native, head


def bundle(root, owners, rows, actions, mutate_report=None):
    """Use genuine native inspect/validate/save on explicitly synthetic reviews."""
    canonical = put(root, "mappings/ingredient_mappings.sssom.tsv", table(rows))
    evidence = put(
        root,
        "evidence.txt",
        b"Synthetic evidence for a diagnostic-only test, not campaign science.\n",
    )
    endpoint = put(root, "source-endpoint.json", b'{"synthetic_only":true}\n')
    native, head = native_fixture(root)
    entries = []
    for i, (owner, row, action) in enumerate(
        zip(owners, rows, actions, strict=True), 1
    ):
        entries.append(
            {
                "entry_id": f"case{i}",
                "row_position": i,
                "row": row,
                "invalid_tokens": P._cas_invalid_tokens(row),
                "owner": {
                    "path": str(owner.relative_to(root)),
                    "sha256": sha(owner.read_bytes()),
                    "mim_id": yaml.safe_load(owner.read_bytes())["mim_id"],
                },
                "action": action,
                "reason": "Synthetic diagnostic disposition; no release approval.",
                "hold": (
                    {
                        "issue": "https://github.com/CultureBotAI/MediaIngredientMech/issues/753",
                        "reason": "Unresolved identity remains withheld.",
                    }
                    if action == P.CAS_HOLD
                    else None
                ),
                "evidence": ["evidence.txt"],
            }
        )
    claims = {
        "schema_version": 1,
        "capability": P.CAS_DISPOSITION,
        "scope": "diagnostic_candidate_only",
        "scientific_approval": False,
        "author": "synthetic-fixture",
        "head": head,
        "canonical": {
            "path": str(canonical.relative_to(root)),
            "sha256": sha(canonical.read_bytes()),
        },
        "source_correction": {
            "path": endpoint.name,
            "sha256": sha(endpoint.read_bytes()),
        },
        "evidence_inputs": {evidence.name: sha(evidence.read_bytes())},
        "entries": entries,
    }
    claim_path = put(root, "claims.json", encoded(claims))
    core = {
        "claims.json",
        canonical.relative_to(root).as_posix(),
        "source-endpoint.json",
        "evidence.txt",
        "scripts/record_review.py",
        "schema/record_review.yaml",
        "MAPPING_SEMANTICS.md",
        *(str(owner.relative_to(root)) for owner in owners),
    }
    targets = [
        {
            "target_id": entry["entry_id"],
            "path": "claims.json",
            "selector": entry["entry_id"],
            "label": entry["entry_id"],
            "kind": "snapshot_row",
            "owner_paths": [
                {
                    "repository": "CultureBotAI/MediaIngredientMech",
                    "path": entry["owner"]["path"],
                    "role": "Synthetic fixture owner",
                }
            ],
            "semantic_digest": {
                "algorithm": "sha256-canonical-json-v1",
                "sha256": P._cas_digest(entry),
                "description": "Complete diagnostic CAS disposition",
            },
        }
        for entry in entries
    ]
    refs, pins, reports = [], {}, []
    for role in ("primary", "skeptic"):
        extra = put(
            root, role + "-context.txt", (role + " separate context\n").encode()
        )
        source = native.inspect_source(root, targets, sorted(core | {extra.name}))[
            "source"
        ]
        report = {
            "schema_version": "1.0.0",
            "review_id": "20260101T000000Z-cas-" + role,
            "kind": "batch",
            "repository": "CultureBotAI/MediaIngredientMech",
            "title": "Synthetic CAS test",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:00Z",
            "reviewer": {
                "identity": "synthetic-" + role,
                "kind": "agent",
                "independence": "independent",
                "independence_basis": "Separate explicitly synthetic reviewer.",
            },
            "skill": "synthetic-fixture",
            "completion": "completed",
            "verdict": "pass_with_limitations",
            "scientific_review": True,
            "summary": "Synthetic scope; no actual chemical approval.",
            "source": source,
            "targets": deepcopy(targets),
            "scope": {
                "description": "Diagnostic contract",
                "selection": "Explicit synthetic cases",
                "coverage": "full",
                "population_size": len(entries),
                "reviewed_target_ids": [e["entry_id"] for e in entries],
            },
            "checks": [
                {
                    "check_id": e["entry_id"],
                    "name": "Diagnostic scope",
                    "required": True,
                    "status": "passed",
                    "summary": "Synthetic action assessed.",
                    "target_ids": [e["entry_id"]],
                    "evidence_ids": ["source"],
                }
                for e in entries
            ],
            "evidence": [
                {
                    "evidence_id": "source",
                    "kind": "record_content",
                    "reference": "evidence.txt",
                    "accessed_at": "2026-01-01T00:00:00Z",
                    "support": "supports",
                    "summary": "Synthetic content.",
                    "snapshot_sha256": sha(evidence.read_bytes()),
                }
            ],
            "assessments": [
                {
                    "assessment_id": e["entry_id"],
                    "area": "identity",
                    "topic": "Diagnostic action",
                    "outcome": "supported",
                    "summary": "Synthetic diagnostic scope only.",
                    "target_ids": [e["entry_id"]],
                    "evidence_ids": ["source"],
                    "dimensions": [
                        {"name": "cas_disposition", "value": e["action"]},
                        {
                            "name": "diagnostic_scope",
                            "value": "diagnostic_candidate_only",
                        },
                        {
                            "name": "hold_disposition",
                            "value": (
                                "WITHHOLD"
                                if e["action"] == P.CAS_HOLD
                                else "RETIRED_WITH_HISTORY"
                            ),
                        },
                    ],
                }
                for e in entries
            ],
            "findings": [],
            "actions": [],
            "limitations": ["Synthetic fixture, no campaign authority."],
        }
        for assessment in report["assessments"]:
            for dimension in assessment["dimensions"]:
                dimension.update(
                    definition="Explicit synthetic diagnostic scope.",
                    evidence_ids=["source"],
                )
        if mutate_report:
            mutate_report(role, report)
        # Actual native writer validates and checks current source; no mocked pass.
        path = native.save_review(root, report)
        assert native.read_review(root, str(path.relative_to(root))) == report
        refs.append(
            {"path": str(path.relative_to(root)), "sha256": sha(path.read_bytes())}
        )
        pins.update({i["path"]: i["sha256"] for i in source["inputs"]})
        pins[str(path.with_name("review.md").relative_to(root))] = sha(
            path.with_name("review.md").read_bytes()
        )
        reports.append(report)
    request = {
        "schema_version": 1,
        "capability": P.CAS_DISPOSITION,
        "claims": {"path": claim_path.name, "sha256": sha(claim_path.read_bytes())},
        "reviews": refs,
        "review_inputs": pins,
    }
    path = put(root, "request.json", encoded(request))
    return {
        "root": root,
        "path": path,
        "head": head,
        "claims": claims,
        "request": request,
        "native": native,
        "reports": reports,
        "owners": owners,
        "canonical": canonical,
    }


def proof(case):
    raw = case["path"].read_bytes()
    paths, _ = P.cas_disposition_inputs(case["root"], case["path"], raw, sha(raw))
    snapshot = {p: p.read_bytes() for p in paths}
    return P.cas_disposition_evidence(
        case["root"], case["path"], raw, sha(raw), snapshot, case["head"]
    )


@pytest.fixture
def actual_cases(tmp_path):
    origin = json.loads((FIXTURE / "ORIGIN.json").read_bytes())
    owners, rows = [], []
    for item in origin["owners"]:
        if not item["row"]["object_id"].startswith("cas:"):
            continue
        raw = (FIXTURE / item["file"]).read_bytes()
        assert sha(raw) == item["sha256"]
        owners.append(put(tmp_path, item["path"], raw))
        rows.append(item["row"])
    return tmp_path, owners, rows


def candidate(case, bound):
    records = {p: yaml.safe_load(p.read_bytes()) for p in case["owners"]}
    subjects, index = owner_index(case["root"], records)
    objects = P.compatibility_registry_objects(
        records,
        subjects,
        index,
        case["canonical"].read_bytes(),
        root=case["root"],
        cas_dispositions=bound,
    )
    rows = []
    for path, record in records.items():
        rows.extend(
            builder._row_from_yaml(
                path,
                {},
                {},
                {},
                {},
                record=record,
                owners={},
                stable_subject=subjects[path],
                registry_objects=objects[subjects[path]],
            )
        )
    return rows


def test_real_three_rows_default_refuses_and_genuine_native_held_contract(actual_cases):
    root, owners, rows = actual_cases
    case = bundle(root, owners, rows, [P.CAS_HOLD] * 3)
    before = {p: p.read_bytes() for p in [*owners, case["canonical"]]}
    with pytest.raises(ValueError, match="Invalid canonical CAS check digit"):
        candidate(case, None)
    bound = proof(case)
    result = P.finalize_cas_dispositions(bound, candidate(case, bound))
    assert len(result["held_rows"]) == 3 and result["retired_entries"] == []
    assert [item["historical_row"] for item in result["held_rows"]] == rows
    assert all(
        item["mandatory_disposition"] == "WITHHOLD" for item in result["held_rows"]
    )
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_native_corrected_source_retirement_is_distinct_from_held_methyl(actual_cases):
    root, owners, rows = actual_cases
    actions = []
    for path, row in zip(owners, rows, strict=True):
        if "Methyl-2" in path.name:
            actions.append(P.CAS_HOLD)
        else:
            record = yaml.safe_load(path.read_bytes())
            # Synthetic afterimage ONLY: no replacement identity is guessed.
            record["identifier"] = (
                "UNMAPPED_9000" if len(actions) == 0 else "UNMAPPED_9001"
            )
            record["mapping_status"] = "UNMAPPED"
            record.pop("ontology_mapping", None)
            record.pop("chemical_properties", None)
            record["legacy_identifiers"] = [
                x for x in record.get("legacy_identifiers", []) if x != row["object_id"]
            ]
            path.write_text(yaml.safe_dump(record))
            actions.append(P.CAS_RETIRE)
    case = bundle(root, owners, rows, actions)
    bound = proof(case)
    result = P.finalize_cas_dispositions(bound, candidate(case, bound))
    assert len(result["held_rows"]) == 1 and len(result["retired_entries"]) == 2
    assert result["held_rows"][0]["candidate_row"]["subject_id"] == "MIM:0001639"


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-head",
        "markdown",
        "source-drift",
        "omitted-source",
        "wrong-action",
        "same-reviewer",
        "missing-core",
        "wrong-digest",
        "wrong-scope",
    ],
)
def test_native_review_and_source_controls(actual_cases, mutation):
    root, owners, rows = actual_cases

    def mutate(role, report):
        if role != "skeptic":
            return
        if mutation == "same-reviewer":
            report["reviewer"]["identity"] = "synthetic-primary"
        if mutation == "wrong-action":
            report["assessments"][0]["dimensions"][0]["value"] = P.CAS_RETIRE
        if mutation == "wrong-digest":
            report["targets"][0]["semantic_digest"]["sha256"] = "0" * 64
        if mutation == "missing-core":
            report["source"]["inputs"] = [
                i
                for i in report["source"]["inputs"]
                if i["path"] != "MAPPING_SEMANTICS.md"
            ]
        if mutation == "wrong-scope":
            report["assessments"][0]["dimensions"][1]["value"] = "release"

    case = bundle(root, owners, rows, [P.CAS_HOLD] * 3, mutate)
    if mutation == "wrong-head":
        case["head"] = "0" * 40
    if mutation == "source-drift":
        (root / "skeptic-context.txt").write_text("changed")
    if mutation == "markdown":
        (root / case["request"]["reviews"][1]["path"]).with_name(
            "review.md"
        ).write_text("forged")
    if mutation == "omitted-source":
        del case["request"]["review_inputs"]["skeptic-context.txt"]
        case["path"].write_bytes(encoded(case["request"]))
    with pytest.raises(ValueError):
        proof(case)


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "malformed",
        "active-retired",
        "different-row",
        "wrong-owner",
        "missing-position",
    ],
)
def test_compatibility_exact_selection_controls(actual_cases, change):
    root, owners, rows = actual_cases
    case = bundle(root, owners, rows, [P.CAS_HOLD] * 3)
    bound = proof(case)
    entry = bound["content"]["entries"][0]
    if change in {"valid", "malformed"}:
        entry["row"]["object_id"] = (
            "cas:138-86-3" if change == "valid" else "cas:garbage"
        )
        changed = deepcopy(rows)
        changed[0] = entry["row"]
        case["canonical"].write_bytes(table(changed))
        bound["content"]["canonical"]["sha256"] = sha(case["canonical"].read_bytes())
    elif change == "active-retired":
        entry["action"] = P.CAS_RETIRE
    elif change == "different-row":
        entry["row"]["comment"] += " altered"
    elif change == "wrong-owner":
        entry["owner"]["mim_id"] = "MIM:0000001"
    elif change == "missing-position":
        entry["row_position"] = 999
    with pytest.raises(ValueError):
        candidate(case, bound)


@pytest.mark.parametrize(
    "where", ["extra-row", "other", "retired", "duplicate", "approval"]
)
def test_finalization_never_leaks_unscoped_invalid_assertions(actual_cases, where):
    root, owners, rows = actual_cases
    case = bundle(root, owners, rows, [P.CAS_HOLD] * 3)
    bound = proof(case)
    final = candidate(case, bound)
    if where == "extra-row":
        final.append({**final[0], "subject_id": "MIM:0000001"})
    if where == "other":
        final[0]["other"] += "|CAS:000-00-0"
    if where == "retired":
        bound["content"]["entries"][0]["action"] = P.CAS_RETIRE
    if where == "duplicate":
        final.append(deepcopy(final[0]))
    if where == "approval":
        final[0]["validation_method"] = "approved"
    with pytest.raises(ValueError):
        P.finalize_cas_dispositions(bound, final)


def test_default_finalization_and_writer_bytes_unchanged(tmp_path):
    rows = [
        {
            "subject_id": "MIM:1",
            "object_id": "cas:invalid",
            "mapping_date": "2026-01-01",
        }
    ]
    assert P.finalize_cas_dispositions(None, rows) is None
    first, second = tmp_path / "a.tsv", tmp_path / "b.tsv"
    builder._write_sssom(rows, first)
    builder._write_sssom(rows, second, cas_dispositions=None)
    assert first.read_bytes() == second.read_bytes()


@pytest.fixture
def disposition_cli(stable_cli, monkeypatch):
    root = stable_cli["root"]
    owner = stable_cli["records"] / "Subject.yaml"
    record = yaml.safe_load(owner.read_bytes())
    record.update(
        identifier="cas:138-86-7",
        chemical_properties={"cas_rn": "138-86-7"},
        ontology_mapping={
            "ontology_id": "cas:138-86-7",
            "ontology_label": "Synthetic held owner",
            "mapping_quality": "EXACT_MATCH",
        },
    )
    owner.write_text(yaml.safe_dump(record))
    row = dict.fromkeys(builder.COLUMNS, "")
    row.update(
        subject_id=record["mim_id"],
        subject_label="Synthetic held owner",
        predicate_id="skos:exactMatch",
        object_id="cas:138-86-7",
        object_label="Synthetic held owner",
        mapping_date="2026-01-01",
        other="CAS:138-86-7",
        validation_method="historical-stamp",
    )
    case = bundle(root, [owner], [row], [P.CAS_HOLD])
    monkeypatch.setattr(builder, "MIM_PUBLISHED_SSSOM", case["canonical"])
    case["cli"] = stable_cli

    def run(*flags, **kwargs):
        return stable_cli["run"](
            "--cas-dispositions",
            str(case["path"]),
            "--cas-dispositions-sha256",
            sha(case["path"].read_bytes()),
            *flags,
            **kwargs,
        )

    case["run"] = run
    return case


def test_real_cli_three_artifacts_bind_native_review_closure_and_forced_hold(
    disposition_cli,
):
    case = disposition_cli
    canonical_before = case["canonical"].read_bytes()
    output, sidecar, manifest = case["run"]()
    product = json.loads(manifest.read_bytes())
    metadata = yaml.safe_load(
        "\n".join(
            line[2:]
            for line in output.read_text().splitlines()
            if line.startswith("# ")
        )
    )
    assert metadata["cas_disposition_capability"] == P.CAS_DISPOSITION
    assert metadata["cas_disposition_request"] == {
        "path": "request.json",
        "sha256": sha(case["path"].read_bytes()),
    }
    bound = product["cas_dispositions"]
    assert bound["held_rows"][0]["candidate_row"] == read_rows(output.read_bytes())[0]
    assert (
        bound["held_rows"][0]["historical_row"]["validation_method"]
        == "historical-stamp"
    )
    assert not read_rows(output.read_bytes())[0]["validation_method"]
    assert bound["held_rows"][0]["mandatory_disposition"] == "WITHHOLD"
    captured = {p["path"]: p["sha256"] for p in product["source_inputs"]}
    assert all(
        captured[str(case["root"] / name)] == digest
        for name, digest in case["request"]["review_inputs"].items()
    )
    assert case["canonical"].read_bytes() == canonical_before and sidecar.exists()


@pytest.mark.parametrize("source", ["request.json", "evidence.txt"])
@pytest.mark.parametrize("artifact", ["sssom", "suppressed", "manifest"])
def test_all_artifacts_refuse_proposal_or_evidence_alias(
    disposition_cli, source, artifact
):
    case = disposition_cli
    path = case["root"] / source
    before = path.read_bytes()
    flags = {
        "suppressed": "--suppressed-aliases-output",
        "manifest": "--generation-manifest-output",
    }
    with pytest.raises(ValueError):
        if artifact == "sssom":
            case["run"]("--output", str(path))
        else:
            case["run"](flags[artifact], str(path))
    assert path.read_bytes() == before and not case["cli"]["output"].exists()


def test_discovery_to_capture_drift_refuses_without_any_artifact(
    disposition_cli, monkeypatch
):
    case = disposition_cli
    discover = P.cas_disposition_inputs

    def altered(*args):
        result = discover(*args)
        case["path"].write_bytes(case["path"].read_bytes() + b"\n")
        return result

    monkeypatch.setattr(P, "cas_disposition_inputs", altered)
    with pytest.raises(ValueError, match="captured input changed"):
        case["run"]()
    assert not case["cli"]["output"].exists()


@pytest.mark.parametrize(
    "source", ["request.json", "evidence.txt", "skeptic-context.txt"]
)
def test_late_disposition_input_drift_preserves_previous_products(
    disposition_cli, monkeypatch, source
):
    case = disposition_cli
    products = case["run"]()
    before = [p.read_bytes() for p in products]
    transaction = sssom_artifacts.ValidatedWriteTransaction

    class Drift(transaction):
        def commit(self, **kwargs):
            path = case["root"] / source
            path.write_bytes(path.read_bytes() + b"\nchanged")
            return super().commit(**kwargs)

    monkeypatch.setattr(sssom_artifacts, "ValidatedWriteTransaction", Drift)
    with pytest.raises(Exception, match="changed during generation"):
        case["run"]()
    assert [p.read_bytes() for p in products] == before


@pytest.mark.parametrize(
    "flags",
    [
        ["--cas-dispositions", "missing"],
        ["--cas-dispositions-sha256", "0" * 64],
        [
            "--identity-mode",
            "legacy",
            "--cas-dispositions",
            "missing",
            "--cas-dispositions-sha256",
            "0" * 64,
        ],
    ],
)
def test_partial_or_legacy_options_refuse_before_inputs(stable_cli, flags):
    with pytest.raises(SystemExit) as raised:
        stable_cli["run"](*flags)
    assert raised.value.code == 2 and not stable_cli["output"].exists()


@pytest.fixture
def annotation_cases(tmp_path):
    origin = json.loads((FIXTURE / "ORIGIN.json").read_bytes())
    owners, rows = [], []
    for item in origin["owners"]:
        if item["row"]["object_id"].startswith("cas:"):
            continue
        raw = (FIXTURE / item["file"]).read_bytes()
        assert sha(raw) == item["sha256"]
        owners.append(put(tmp_path, item["path"], raw))
        rows.append(item["row"])
    assert len(rows) == 4
    return tmp_path, owners, rows


def test_four_actual_annotation_rows_are_wholly_held_never_scrubbed(annotation_cases):
    root, owners, rows = annotation_cases
    case = bundle(root, owners, rows, [P.CAS_HOLD] * 4)
    bound = proof(case)
    generated = candidate(case, bound)
    result = P.finalize_cas_dispositions(bound, generated)
    assert len(result["held_rows"]) == 4 and result["retired_entries"] == []
    assert {r["candidate_row"]["object_id"] for r in result["held_rows"]} == {
        "NCIT:C217928",
        "CHEBI:6109",
        "CHEBI:17158",
        "CHEBI:16995",
    }
    for entry, item in zip(
        bound["content"]["entries"], result["held_rows"], strict=True
    ):
        assert (
            item["invalid_tokens"]
            == entry["invalid_tokens"]
            == P._cas_invalid_tokens(item["historical_row"])
        )
        assert item["mandatory_disposition"] == "WITHHOLD"
        assert item["historical_row"] == entry["row"]
        assert item["candidate_row"] == generated[item["candidate_position"] - 1]
        assert item["candidate_row"] != item["historical_row"]
        assert any(
            item["candidate_row"][key] != item["historical_row"][key]
            for key in (
                "source",
                "mapping_date",
                "mapping_justification",
                "validation_method",
            )
        )


@pytest.mark.parametrize(
    "alter",
    [
        "retire-valid-object",
        "scrub-annotation",
        "unlisted-annotation",
        "extra-invalid",
        "wrong-field",
    ],
)
def test_annotation_hold_does_not_retire_valid_object_or_bypass_scope(
    annotation_cases, alter
):
    root, owners, rows = annotation_cases
    case = bundle(root, owners, rows, [P.CAS_HOLD] * 4)
    bound = proof(case)
    if alter == "retire-valid-object":
        bound["content"]["entries"][0]["action"] = P.CAS_RETIRE
        with pytest.raises(ValueError, match="only invalid CAS objects"):
            candidate(case, bound)
        return
    final = candidate(case, bound)
    if alter == "scrub-annotation":
        final[0]["other"] = ""
    if alter == "unlisted-annotation":
        bound["content"]["entries"].pop(0)
    if alter == "extra-invalid":
        final[0]["other"] += "|CAS:138-86-7"
    if alter == "wrong-field":
        bound["content"]["entries"][0]["invalid_tokens"][0]["field"] = "object_id"
    with pytest.raises(ValueError):
        P.finalize_cas_dispositions(bound, final)


@pytest.mark.parametrize(
    "change", ["missing", "duplicated", "valid", "wrong-field", "extra-key"]
)
def test_closed_exact_invalid_token_selection(actual_cases, change):
    root, owners, rows = actual_cases
    case = bundle(root, owners, rows, [P.CAS_HOLD] * 3)
    entry = case["claims"]["entries"][0]
    if change == "missing":
        entry["invalid_tokens"].pop()
    if change == "duplicated":
        entry["invalid_tokens"].append(entry["invalid_tokens"][0])
    if change == "valid":
        entry["invalid_tokens"][0]["token"] = "cas:138-86-3"
    if change == "wrong-field":
        entry["invalid_tokens"][0]["field"] = "comment"
    if change == "extra-key":
        entry["invalid_tokens"][0]["approval"] = True
    claims = put(root, "claims.json", encoded(case["claims"]))
    case["request"]["claims"]["sha256"] = sha(claims.read_bytes())
    case["path"].write_bytes(encoded(case["request"]))
    with pytest.raises(ValueError, match="invalid token selection"):
        proof(case)


def test_duplicate_occurrence_is_not_a_unique_claim_selection(actual_cases):
    root, owners, rows = actual_cases
    rows[0]["other"] += "|" + rows[0]["other"]
    case = bundle(root, owners, rows, [P.CAS_HOLD] * 3)
    with pytest.raises(ValueError, match="invalid token selection"):
        proof(case)
