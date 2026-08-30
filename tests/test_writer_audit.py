"""The shared writer audit, technique by technique (#132 Phase 7, #260).

Each positive case is a shape taken from a real script in the fleet, and each
negative case is a false positive one of the four existing copies actually
produces. The negatives carry as much weight as the positives: the loose rule
two Mechs use is wrong precisely by counting things that read YAML and write
something else.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_writers import Evidence, WriterProfile, as_tsv, audit, writes_yaml
from kg_microbe_writers.__main__ import profile_for

PROFILE = WriterProfile(
    search_dirs=("scripts",),
    exclude=("scripts/audit_writers.py",),
    save_helpers=("save_yaml", "write_validated_thing"),
    validators=(r"validate_thing\(",),
    curation_markers=("record_curation",),
)


def reasons(source: str, profile: WriterProfile = PROFILE) -> tuple[str, ...]:
    return writes_yaml(source, profile).reasons()


# -- the five techniques ----------------------------------------------------


def test_a_yaml_dump_is_a_write():
    assert reasons("yaml.safe_dump(doc, handle)") == ("yaml-dump",)
    assert reasons("yaml.dump(doc)") == ("yaml-dump",)


def test_a_dump_written_to_a_path_is_one_write_not_two():
    assert reasons('path.write_text(yaml.safe_dump(doc))') == ("yaml-dump",)


def test_the_mechs_own_save_helper_is_a_write():
    """MediaIngredientMech's scripts route through save_yaml(), so a rule that
    only knows yaml.dump reports 19 writers where its own audit reports 88."""
    assert reasons("from x import save_yaml\nsave_yaml(doc, MAPPED)") == ("save-helper",)
    assert reasons("write_validated_thing(record, path)") == ("save-helper",)


def test_a_helper_this_mech_does_not_declare_is_not_a_write():
    assert reasons("write_validated_other(record, path)") == ()


def test_an_in_place_edit_of_globbed_yaml_is_a_write():
    """CultureMech's retype_solution_records.py: iterate *.yaml, read the text,
    change it, write it back. No yaml.dump anywhere."""
    source = (
        'for path in sorted(root.rglob("*.yaml")):\n'
        "    text = path.read_text()\n"
        "    new = text.replace(a, b)\n"
        "    path.write_text(new)\n"
    )
    assert reasons(source) == ("in-place-edit",)


def test_a_write_to_a_path_built_from_a_yaml_name_is_a_write():
    """CultureMech's import_jcm_grmd.py serialises YAML with its own
    dump_record() and writes it to a name it assembled -- which techniques 1
    to 4 all miss. The path is a hop away from the filename."""
    source = (
        'fname = f"JCM_{n}.yaml"\n'
        "out_path = out_dir / fname\n"
        "yaml_text = dump_record(rec)\n"
        "out_path.write_text(yaml_text)\n"
    )
    assert reasons(source) == ("in-place-edit",)


# -- what must NOT count ----------------------------------------------------


def test_reading_yaml_and_writing_json_is_not_a_write():
    """audit_mediadive_ids.py, which CultureMech's audit reports as a writer."""
    source = (
        'for path in sorted(NORMALIZED.rglob("*.yaml")):\n'
        "    doc = yaml.safe_load(path.read_text())\n"
        "cache.write_text(json.dumps(payload))\n"
    )
    assert reasons(source) == ()


def test_a_yaml_mention_in_a_docstring_is_not_a_write():
    """_edison_capture.py is vendored byte-identical into every Mech, and two
    of the four audits call it a YAML writer. Its only yaml.safe_dump is in a
    docstring that says the *caller* writes the YAML."""
    source = (
        '"""Writes {stem}-meta.yaml.\n\n'
        "The caller still owns writing the meta yaml so that the format stays\n"
        'in one place (yaml.safe_dump knobs may vary).\n"""\n'
        "target.write_text(body)\n"
    )
    assert reasons(source) == ()


def test_globbing_yaml_without_writing_it_back_is_not_a_write():
    source = (
        'for path in sorted(root.rglob("*.yaml")):\n'
        "    doc = yaml.safe_load(path.read_text())\n"
        'report.write_text("\\n".join(lines))\n'
    )
    assert reasons(source) == ()


def test_a_json_write_to_a_yaml_derived_path_is_not_a_write():
    source = 'p = base / "x.yaml"\nq = p.with_suffix(".json")\nq.write_text(json.dumps(d))\n'
    assert reasons(source) == ()


def test_rewriting_a_globbed_yaml_path_as_json_is_not_a_write():
    """The same variable is read and written, so the in-place branch fires --
    but what goes back is JSON. Reading a YAML and writing JSON over it is a
    conversion, not a YAML write."""
    source = (
        'for path in sorted(root.rglob("*.yaml")):\n'
        "    text = path.read_text()\n"
        "    path.write_text(json.dumps(convert(text)))\n"
    )
    assert reasons(source) == ()


def test_a_write_to_a_path_with_no_yaml_anywhere_is_not_a_write():
    """Only assignments that mention a `.yaml` name seed the path set. Treating
    every assigned name as a YAML path would make any `write_text` a write."""
    source = 'out = base / "report.txt"\nout.write_text(body)\n'
    assert reasons(source) == ()


def test_a_reused_variable_name_in_another_function_is_not_an_in_place_edit():
    """CommunityMech's growth_conditions_sweep.py reads a community YAML through
    `path` in one function and writes INDEX.md through a different `path` in
    another, ninety lines apart. Matching names across the whole file read that
    as an in-place YAML edit; scoping to the function is what makes the name
    mean something. This was a false positive the first version of this module
    added to a Mech whose own audit was already right."""
    source = (
        'def collect():\n'
        '    for p in COMMUNITIES.glob("*.yaml"):\n'
        "        text = path.read_text()\n"
        "\n"
        "def index():\n"
        '    path = OUT_DIR / "INDEX.md"\n'
        '    path.write_text("\\n".join(lines))\n'
    )
    assert reasons(source) == ()


def test_a_path_carrying_another_extension_is_that_file(tmp_path: Path):
    """A name assigned from an expression that introduces a different extension
    is that file, whatever it was derived from -- otherwise the taint spreads
    from a YAML *input* to an unrelated writer."""
    assert reasons('def f():\n    p = OUT / "INDEX.md"\n    p.write_text(body)\n') == ()
    assert reasons('def f():\n    p = OUT / "x.json"\n    p.write_text(body)\n') == ()


def test_a_yaml_path_converted_to_another_extension_is_no_longer_yaml():
    """The transitive half of the same rule. `src` holds a .yaml, so it seeds
    the set -- but `out` is derived from it *by changing the extension*, and
    what gets written is a .md. Following the derivation without re-checking
    the extension is how a YAML input taints an unrelated writer."""
    source = (
        "def f():\n"
        '    src = ROOT / "x.yaml"\n'
        '    out = src.with_suffix(".md")\n'
        "    out.write_text(body)\n"
    )
    assert reasons(source) == ()


def test_a_module_level_yaml_path_still_reaches_a_function(tmp_path: Path):
    """Scoping must not lose the common case of a constant defined at module
    level and written inside a function."""
    source = 'TARGET = ROOT / "records.yaml"\n\ndef save(doc):\n    TARGET.write_text(dump(doc))\n'
    assert reasons(source) == ("in-place-edit",)


# -- the declared columns ---------------------------------------------------


def _repo(tmp_path: Path, files: dict[str, str], justfile: str = "") -> Path:
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    if justfile:
        (tmp_path / "justfile").write_text(justfile)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def test_a_writer_reports_what_it_declares(tmp_path: Path):
    root = _repo(
        tmp_path,
        {
            "scripts/w.py": (
                "yaml.safe_dump(doc)\n"
                "parser.add_argument('--dry-run')\n"
                "record_curation(event)\n"
                "validate_thing(doc)\n"
            )
        },
        justfile="curate:\n    python scripts/w.py\n",
    )
    (row,) = audit(root, PROFILE)
    assert row.path == "scripts/w.py"
    assert row.appends_curation_history
    assert row.has_write_safeguard
    assert row.validates_before_write
    assert row.wired_into_just


def test_a_bare_writer_declares_nothing(tmp_path: Path):
    root = _repo(tmp_path, {"scripts/w.py": "yaml.safe_dump(doc)\n"})
    (row,) = audit(root, PROFILE)
    assert not row.appends_curation_history
    assert not row.has_write_safeguard
    assert not row.validates_before_write
    assert not row.wired_into_just


@pytest.mark.parametrize(
    "flag", ["--dry-run", "--dry_run", "dry_run =", "--apply", "args.apply", "--write"]
)
def test_both_safeguard_conventions_count(tmp_path: Path, flag: str):
    """Opt-out and opt-in both mean someone thought about it. Opt-in is
    strictly safer, since the default is then not to write."""
    root = _repo(tmp_path, {"scripts/w.py": f"yaml.safe_dump(d)\n{flag}\n"})
    assert audit(root, PROFILE)[0].has_write_safeguard


def test_a_non_writer_is_not_listed_at_all(tmp_path: Path):
    root = _repo(tmp_path, {"scripts/r.py": "doc = yaml.safe_load(p.read_text())\n"})
    assert audit(root, PROFILE) == []


def test_the_excluded_path_is_not_judged(tmp_path: Path):
    """The audit tool's own regexes contain the literal `yaml.safe_dump`, so
    any rule that reads source as text calls it a writer. All four copies
    exclude it."""
    root = _repo(
        tmp_path,
        {
            # Text that the rule genuinely matches, so the exclusion is what
            # keeps it out rather than an accident of escaping.
            "scripts/audit_writers.py": "yaml.safe_dump(doc)\n",
            "scripts/w.py": "yaml.safe_dump(doc)\n",
        },
    )
    assert [row.path for row in audit(root, PROFILE)] == ["scripts/w.py"]


def test_only_tracked_files_are_audited(tmp_path: Path):
    """From git, not a filesystem walk: caches and scratch files are not the
    repository (#203)."""
    root = _repo(tmp_path, {"scripts/w.py": "yaml.safe_dump(doc)\n"})
    (root / "scripts" / "untracked.py").write_text("yaml.safe_dump(doc)\n")
    assert [row.path for row in audit(root, PROFILE)] == ["scripts/w.py"]


# -- the TSV ----------------------------------------------------------------


def test_target_kind_is_omitted_for_a_mech_that_does_not_classify(tmp_path: Path):
    """Two Mechs classify a writer's output and two do not. A Mech that
    declares no kinds emits no column, rather than a column of "unknown"."""
    root = _repo(tmp_path, {"scripts/w.py": "yaml.safe_dump(doc)\n"})
    rows = audit(root, PROFILE)
    assert rows[0].target_kind == ""
    header = as_tsv(rows, target_kind=False).splitlines()[0]
    assert "target_kind" not in header
    assert as_tsv(rows).splitlines()[0].split("\t")[2] == "target_kind"


def test_a_classifying_mech_labels_each_writer(tmp_path: Path):
    profile = WriterProfile(
        search_dirs=("scripts",),
        target_kinds={"recipe": (r"RECIPES",), "report": (r"REPORTS",)},
    )
    root = _repo(
        tmp_path,
        {
            "scripts/a.py": "yaml.safe_dump(d)\nRECIPES\n",
            "scripts/b.py": "yaml.safe_dump(d)\nRECIPES\nREPORTS\n",
            "scripts/c.py": "yaml.safe_dump(d)\n",
        },
    )
    kinds = {row.path: row.target_kind for row in audit(root, profile)}
    assert kinds == {
        "scripts/a.py": "recipe",
        "scripts/b.py": "mixed",
        "scripts/c.py": "unknown",
    }


def test_evidence_says_why_a_row_is_there():
    """The four copies disagreed and nobody could see why. A row that says how
    it was detected can be argued with; a bare yes cannot."""
    assert Evidence().reasons() == ()
    assert not Evidence()
    assert Evidence(dumps=True, in_place=True).reasons() == ("yaml-dump", "in-place-edit")


# -- against the four real corpora ------------------------------------------

MANIFEST = load_fleet_manifest()
CLAW_ROOT = Path(__file__).resolve().parents[1]
ENABLED = sorted(
    name
    for name, mech in MANIFEST.mechs.items()
    if (c := mech.capabilities.get("writer_audit")) is not None and c.is_enabled
)


def test_every_mech_decides_about_the_writer_audit():
    for name, mech in MANIFEST.mechs.items():
        capability = mech.capabilities.get("writer_audit")
        assert capability is not None, f"{name} does not declare writer_audit"
        if not capability.is_enabled:
            assert capability.reason.strip(), f"{name} declines without a reason"


def test_the_enabled_set_is_the_four_that_carry_a_copy():
    """ProteinTraitsMech's file shares the name and nothing else, and
    CellStructureMech has none. Naming the set keeps the corpus expectations
    below meaningful."""
    assert ENABLED == [
        "communitymech",
        "culturemech",
        "mediaingredientmech",
        "traitmech",
    ]


@pytest.mark.parametrize("mech", ENABLED)
def test_the_shared_audit_beats_the_copy_it_replaces(mech):
    """The claim this consolidation rests on: strictly more accurate than every
    existing copy. Not row-for-row equivalence -- each copy is wrong in a
    different direction, so agreeing with all four is impossible.

    CommunityMech and TraitMech already detect what they detect correctly, so
    the shared version must drop nothing from them. CultureMech and
    MediaIngredientMech carry false positives from the loose heuristic, so it
    drops some of theirs and gains the helper writers they miss.
    """
    try:
        root = resolve_mech_root(mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a {mech} checkout: {exc}")
    script = root / "scripts" / "audit_writers.py"
    if not script.is_file():
        pytest.skip(f"{mech} has no audit_writers.py here")

    settings = MANIFEST.mechs[mech].capabilities["writer_audit"].settings
    mine = {row.path for row in audit(root, profile_for(settings))}

    result = subprocess.run(
        [sys.executable, "scripts/audit_writers.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"{mech}'s own audit did not run here")
    theirs = {
        line.split("\t")[0]
        for line in result.stdout.splitlines()
        if "\t" in line and not line.startswith("path")
    }
    theirs.discard("scripts/audit_writers.py")

    if mech in {"communitymech", "traitmech"}:
        assert not (theirs - mine), (
            f"{mech}'s copy is already accurate, so the shared audit must not "
            f"lose any of its rows; it dropped {sorted(theirs - mine)}"
        )
    if mech == "communitymech":
        # The strictest case available: its copy detects exactly the techniques
        # this one does, so the two must agree row for row. A disagreement here
        # is a defect in the shared rule, not a difference of opinion -- it is
        # how the false positive on growth_conditions_sweep.py was found.
        assert mine == theirs, (
            f"communitymech should agree exactly; "
            f"added {sorted(mine - theirs)}, dropped {sorted(theirs - mine)}"
        )
    assert mine, f"{mech}: the shared audit found no writers at all"


# -- error paths and the CLI ------------------------------------------------


def test_a_directory_that_is_not_a_repository_yields_nothing(tmp_path: Path):
    """`git ls-files` fails outside a repository. Returning nothing is right --
    there is no repository to have scripts in -- but it must not raise."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "w.py").write_text("yaml.safe_dump(d)\n")
    assert audit(tmp_path, PROFILE) == []


def test_an_unreadable_file_is_skipped_not_fatal(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path, {"scripts/a.py": "yaml.safe_dump(d)\n", "scripts/b.py": "yaml.safe_dump(d)\n"})
    original = Path.read_text

    def explode(self, *args, **kwargs):
        if self.name == "a.py":
            raise OSError("unreadable")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", explode)
    assert [row.path for row in audit(root, PROFILE)] == ["scripts/b.py"]


def test_the_cli_reports_a_mech_that_declines_and_succeeds(capsys):
    from kg_microbe_writers.__main__ import main

    assert main(["audit", "--mech", "proteintraitsmech"]) == 0
    assert "declares no writer audit" in capsys.readouterr().out


def test_the_cli_fails_closed_without_a_checkout(capsys, monkeypatch):
    from kg_microbe_writers import __main__ as cli

    monkeypatch.setattr(
        cli, "resolve_mech_root",
        lambda *a, **k: (_ for _ in ()).throw(MechRootError("no checkout")),
    )
    assert cli.main(["audit", "--mech", "traitmech"]) == 2
    assert "no checkout" in capsys.readouterr().err


def test_the_cli_emits_the_tsv_and_a_count(capsys, tmp_path, monkeypatch):
    from kg_microbe_writers import __main__ as cli

    root = _repo(tmp_path, {"scripts/w.py": "yaml.safe_dump(doc)\n"})
    monkeypatch.setattr(cli, "resolve_mech_root", lambda *a, **k: root)
    assert cli.main(["audit", "--mech", "traitmech"]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[0].startswith("path\twrites_yaml")
    assert "target_kind" not in captured.out
    assert "traitmech: 1 writers" in captured.err


def test_the_cli_can_show_why_each_row_is_there(capsys, tmp_path, monkeypatch):
    from kg_microbe_writers import __main__ as cli

    root = _repo(tmp_path, {"scripts/w.py": "yaml.safe_dump(doc)\n"})
    monkeypatch.setattr(cli, "resolve_mech_root", lambda *a, **k: root)
    assert cli.main(["audit", "--mech", "traitmech", "--why"]) == 0
    assert "scripts/w.py: yaml-dump" in capsys.readouterr().err


def test_the_profile_is_built_from_the_manifest_settings():
    settings = MANIFEST.mechs["traitmech"].capabilities["writer_audit"].settings
    profile = profile_for(settings)
    assert profile.search_dirs == ("scripts", "src/traitmech")
    assert profile.save_helpers == ("write_validated_trait",)
    assert "scripts/audit_writers.py" in profile.exclude
