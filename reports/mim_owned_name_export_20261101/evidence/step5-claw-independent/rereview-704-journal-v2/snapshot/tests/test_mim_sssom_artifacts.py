"""Boundary tests for the native candidate/sidecar/manifest transaction (#701)."""

import csv
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe_utils import sssom_artifacts as artifacts
from kg_microbe_write import transaction

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = (
    "subject_id", "token_key", "token", "owner_subject_ids", "disposition",
    "input_surfaces", "source_refs", "evidence_refs",
)


def sidecar(*rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return stream.getvalue().encode()


def suppression(token="owned", **changes):
    row = dict(zip(COLUMNS, (
        "MIM:Subject", token.casefold(), token, '["MIM:Owner"]', "SUPPRESS",
        '["yaml"]', '["data/Subject.yaml#/synonyms/0"]', '["https://example.test/decision"]',
    ), strict=True))
    row.update(changes)
    return [row[key] for key in COLUMNS]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path / "workspace"))
    output = tmp_path / "artifacts" / "candidate.sssom.tsv"
    source = tmp_path / "source.yaml"
    source.write_bytes(b"preferred_term: Owned\n")
    paths = artifacts.artifact_paths(output)
    sssom = (
        f'# mapping_set_description: "{artifacts.POLICY_MARKER}"\n'
        'subject_id\tother\nMIM:Subject\tkept\n'
    ).encode()

    def check():
        assert source.read_bytes() == b"preferred_term: Owned\n"

    def publish(*, aliases=None, text=None, before=None, inputs=None, **kwargs):
        return artifacts.publish_candidate_artifacts(
            output, sssom if text is None else text,
            sidecar(suppression()) if aliases is None else aliases,
            {"producer_revision": "a" * 40, "external_validation": "fixture"},
            kwargs.pop("input_check", check), input_paths=[source] if inputs is None else inputs,
            expected_before=artifacts.capture_beforeimages(paths) if before is None else before,
            claw_root=ROOT, **kwargs,
        )
    return output, paths, source, sssom, publish


def test_complete_set_and_true_noop_have_exact_artifacts_and_native_journal(setup):
    output, paths, source, sssom, publish = setup
    first = publish()
    assert first["status"] == "complete"
    assert output.read_bytes() == sssom
    manifest = json.loads(paths[2].read_bytes())
    assert manifest["policy_version"] == artifacts.POLICY_VERSION
    assert [entry["role"] for entry in manifest["artifacts"]] == ["sssom", "suppressed_aliases"]
    journal = Path(first["journal"])
    assert json.loads(journal.read_text())["status"] == "complete"
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    second = publish()
    assert second["status"] == "unchanged" and second["journal"] is None
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths} == before
    assert len(list(journal.parent.glob("write-*.json"))) == 1
    assert source.read_bytes() == b"preferred_term: Owned\n"


@pytest.mark.parametrize("change", ["empty", "missing_sidecar", "missing_manifest", "stale_manifest"])
def test_equal_tsv_is_not_a_noop_for_changed_or_missing_companions(setup, change):
    output, paths, _, sssom, publish = setup
    publish()
    if change == "missing_sidecar":
        paths[1].unlink()
    elif change == "missing_manifest":
        paths[2].unlink()
    elif change == "stale_manifest":
        paths[2].write_bytes(b"{}\n")
    result = publish(aliases=sidecar() if change == "empty" else None)
    assert result["status"] == "complete"
    assert output.read_bytes() == sssom
    assert paths[1].read_bytes() == (sidecar() if change == "empty" else sidecar(suppression()))
    assert json.loads(paths[2].read_bytes())["policy_version"] == artifacts.POLICY_VERSION


def test_declared_working_copy_stamp_beforeimage_is_allowed_and_not_checked_as_postimage(setup):
    output, _, source, sssom, publish = setup
    publish()
    result = publish(text=sssom.replace(b"kept", b"different"), inputs=[source, output],
                     working_copy_stamp_input=True)
    assert result["status"] == "complete"
    assert b"different" in output.read_bytes()


@pytest.mark.parametrize("kind", ["undeclared_output", "sidecar_input", "unmatched_declaration"])
def test_only_the_explicit_working_copy_input_can_overlap_outputs(setup, kind):
    output, paths, source, _, publish = setup
    inputs = {"undeclared_output": [source, output], "sidecar_input": [source, paths[1]],
              "unmatched_declaration": [source]}[kind]
    with pytest.raises(ValueError, match="alias|undeclared"):
        publish(inputs=inputs, working_copy_stamp_input=kind == "unmatched_declaration")
    assert not output.exists()


@pytest.mark.parametrize("kind", ["output_symlink", "parent_symlink", "hardlink", "same_path"])
def test_output_aliases_are_refused_before_writing(setup, kind, tmp_path):
    output, paths, source, _, publish = setup
    if kind == "parent_symlink":
        target = tmp_path / "elsewhere"
        target.mkdir()
        output.parent.symlink_to(target, target_is_directory=True)
    else:
        output.parent.mkdir()
        if kind == "output_symlink":
            output.symlink_to(source)
        elif kind == "hardlink":
            output.hardlink_to(source)
    with pytest.raises(ValueError, match="Symlink|unaliased|distinct"):
        publish(sidecar_output=output if kind == "same_path" else None)
    assert source.read_bytes() == b"preferred_term: Owned\n"
    assert not paths[2].exists()


@pytest.mark.parametrize("rows", [
    [suppression("kept")], [suppression(), suppression()],
    [suppression(owner_subject_ids='["MIM:Subject"]')],
    [suppression(evidence_refs="[]")], [suppression(disposition="DROP")],
    [suppression(subject_id="MIM:NotEmitted")],
])
def test_invalid_sidecar_never_publishes_a_tsv(setup, rows):
    output, _, _, _, publish = setup
    with pytest.raises(ValueError):
        publish(aliases=sidecar(*rows))
    assert not output.exists()


def test_marker_and_exact_beforeimage_are_required(setup):
    output, paths, _, sssom, publish = setup
    with pytest.raises(ValueError, match="marker"):
        publish(text=sssom.replace(artifacts.POLICY_MARKER.encode(), b"legacy"))
    before = artifacts.capture_beforeimages(paths)
    output.parent.mkdir()
    output.write_bytes(b"concurrent work\n")
    with pytest.raises(ValueError, match="beforeimage changed"):
        publish(before=before)
    assert output.read_bytes() == b"concurrent work\n"
    assert not paths[1].exists()


def test_real_native_precommit_checker_refuses_a_source_change_after_staging(setup, monkeypatch):
    output, _, source, _, publish = setup
    original = transaction.ValidatedWriteTransaction.commit

    def commit(self, **kwargs):
        source.write_bytes(b"changed after staging\n")
        return original(self, **kwargs)

    monkeypatch.setattr(transaction.ValidatedWriteTransaction, "commit", commit)
    with pytest.raises(transaction.ValidationFailed):
        publish()
    assert not output.exists()


def test_native_partial_write_failure_retains_in_progress_recovery_journal(setup, monkeypatch):
    output, paths, _, _, publish = setup
    publish()
    before = {p: p.read_bytes() for p in paths}
    original = transaction._atomic_replace

    def replace(path, text):
        if path == paths[1]:
            raise OSError("injected sidecar write failure")
        return original(path, text)

    monkeypatch.setattr(transaction, "_atomic_replace", replace)
    with pytest.raises(transaction.WriteError, match="journal"):
        publish(aliases=sidecar(), text=before[output].replace(b"kept", b"new"))
    journals = [json.loads(p.read_text()) for p in (output.parent / ".sssom-artifact-journals").glob("*.json")]
    failed = [j for j in journals if j["status"] == "in_progress"]
    assert len(failed) == 1
    assert failed[0]["previous"] == {str(p): b.decode() for p, b in before.items()}
    assert paths[1].read_bytes() == before[paths[1]]
    assert output.read_bytes() != before[output]


@pytest.mark.parametrize("same_tsv", [False, True])
def test_legacy_publisher_refuses_policy_candidate_even_without_manifest(setup, monkeypatch, same_tsv):
    output, _, _, sssom, publish = setup
    publish()
    spec = importlib.util.spec_from_file_location("policy_publish_test", ROOT / "scripts/publish_sssom.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    canonical = output.parent / "canonical.tsv"
    canonical.write_bytes(sssom if same_tsv else b"old canonical bytes\n")
    original = canonical.read_bytes()
    output.with_suffix(output.suffix + ".manifest.json").unlink()
    monkeypatch.setattr(module, "WORKING_COPY", output)
    monkeypatch.setattr(module, "PUBLISHED", canonical)
    monkeypatch.setattr(module, "require_mech_roots", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "argv", ["publish_sssom.py", "--apply"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    assert canonical.read_bytes() == original


@pytest.mark.parametrize("returncode,diagnostic,valid", [
    (0, "Informational extension warning", True),
    (1, "Unexpected validation failure", False),
    (2, "", False),
    (0, "subject_id must be supplied", False),
])
def test_legacy_validator_never_accepts_a_nonzero_exit(monkeypatch, returncode, diagnostic, valid):
    spec = importlib.util.spec_from_file_location("exit_publish_test", ROOT / "scripts/publish_sssom.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess([], returncode, "", diagnostic))
    errors = module._validate(Path("not-read.tsv"))
    assert (errors == []) is valid
    if returncode:
        assert f"exited {returncode}" in errors[0]


@pytest.mark.parametrize("first,second", [
    ("candidate.sssom.tsv", "CANDIDATE.SSSOM.TSV"),
    ("caf\u00e9.sssom.tsv", "cafe\u0301.sssom.tsv"),
])
def test_absent_case_and_unicode_aliases_are_refused_before_any_artifact_write(setup, first, second):
    output, _, source, sssom, _ = setup
    paths = artifacts.artifact_paths(output.with_name(first), output.with_name(second))
    with pytest.raises(ValueError, match="Case/Unicode-equivalent"):
        artifacts.publish_candidate_artifacts(
            paths[0], sssom, sidecar(suppression()), {}, lambda: None,
            input_paths=[source], expected_before=artifacts.capture_beforeimages(paths),
            claw_root=ROOT, sidecar_output=paths[1],
        )
    assert not output.parent.exists(), "Alias refusal must precede artifacts and journal creation"


@pytest.mark.parametrize("phase", ["noop", "precommit", "postwrite"])
def test_callback_output_drift_never_returns_complete_or_unchanged(setup, monkeypatch, phase):
    output, paths, _, sssom, publish = setup
    if phase == "noop":
        publish()
    boundary = {"noop": 1, "precommit": 5, "postwrite": 6}[phase]
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        if calls == boundary:
            paths[1].write_bytes(b"concurrent sidecar edit\n")

    with pytest.raises((ValueError, transaction.ValidationFailed), match="beforeimage|mismatch"):
        publish(input_check=callback)
    assert calls == boundary
    assert paths[1].read_bytes() == b"concurrent sidecar edit\n"
    if phase == "precommit":
        assert not output.exists(), "A late input callback must not erase concurrent output work"
    elif phase == "postwrite":
        assert output.read_bytes() == sssom


@pytest.mark.parametrize("kind", ["output", "sidecar", "manifest", "source"])
def test_symlink_parent_traversal_is_refused_before_lexical_normalization(tmp_path, kind):
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real / "sub", target_is_directory=True)
    supplied = alias / ".." / "candidate.tsv"
    output = tmp_path / "ordinary.tsv"
    with pytest.raises(ValueError, match="Parent traversal"):
        if kind == "source":
            artifacts.capture_beforeimages([supplied])
        else:
            artifacts.artifact_paths(
                supplied if kind == "output" else output,
                supplied if kind == "sidecar" else None,
                supplied if kind == "manifest" else None,
            )
    assert not (tmp_path / "candidate.tsv").exists()
    assert not (real / "candidate.tsv").exists()
    assert not output.exists()


@pytest.mark.parametrize("phase", ["precommit", "postwrite", "journal_bytes"])
def test_last_callback_cannot_redirect_or_change_the_recovery_journal(setup, tmp_path, phase):
    output, paths, _, _, publish = setup
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    journal_dir = output.parent / ".sssom-artifact-journals"
    boundary = 5 if phase == "precommit" else 6
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        if calls == boundary:
            if phase == "journal_bytes":
                journal = next(journal_dir.glob("write-*.json"))
                journal.write_bytes(b"{}\n")
            else:
                if journal_dir.exists():
                    journal_dir.rename(output.parent / "original-journals")
                journal_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises((ValueError, transaction.ValidationFailed), match="Symlink|journal changed"):
        publish(input_check=callback)
    assert calls == boundary
    assert not list(outside.iterdir())
    if phase == "precommit":
        assert not any(p.exists() for p in paths)
