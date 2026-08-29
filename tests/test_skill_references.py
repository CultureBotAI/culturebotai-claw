"""Every reference in every skill points at something that exists.

Phase 4 item 4 of the standardization plan (#132). Skills are prose, so a path
that was renamed, a script that moved to another repository, or a sibling skill
that was deleted goes unnoticed until a reader follows the reference and lands
nowhere. Three such references were live when this was written:

  - `kg-microbe/mappings/unified_chemical_mappings.tsv.gz`, cited by two
    skills, replaced by an SSSOM product months earlier;
  - `kg-microbe/kg_microbe/transform_utils/metatraits/mappings/`, moved to
    `kg-microbe/mappings/canonical/`.

The tests below are mostly about what the checker must NOT claim. A checker
that reports every unresolvable path as broken is noise, and noise is how a
gate stops being read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_microbe_skills import (
    check,
    extract_references,
    format_report,
    skill_files,
)
from kg_microbe_skills.references import reference_root

ROOT = Path(__file__).resolve().parents[1]


def _skill(tmp_path: Path, name: str, body: str, frontmatter: str = "") -> Path:
    directory = tmp_path / ".claude" / "skills" / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(f"---\nname: {name}\n{frontmatter}---\n" + body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Extraction: what is and is not a reference
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "origin/main",  # a git ref
        "refs/heads/main",
        "www.ebi.ac.uk/chebi",  # a bare URL
        "https://example.org/a/b",
        "owner/repository",  # a shape, not a name
        "data/ingredients/unmapped/UNMAPPED_NNNN.yaml",
        "workspace/shards/sssom_review/shard_N.tsv",
        "{package_path}/schema/history.yaml",
        "scripts/aggregate_*",  # a glob
        "--require-sources",
        "some words here",
    ],
)
def test_things_that_are_not_repository_paths_are_not_references(tmp_path, token):
    path = _skill(tmp_path, "s", f"See `{token}` for details.\n")
    assert [r.text for r in extract_references(path) if r.kind == "path"] == []


def test_a_repository_path_is_a_reference(tmp_path):
    path = _skill(tmp_path, "s", "Read `src/kg_microbe_fleet/fleet.yaml` first.\n")
    references = extract_references(path)
    assert [(r.kind, r.text) for r in references] == [
        ("path", "src/kg_microbe_fleet/fleet.yaml")
    ]
    assert references[0].line == 4


def test_a_backticked_slash_name_is_a_command_reference(tmp_path):
    path = _skill(tmp_path, "s", "Run `/curate` afterwards.\n")
    assert [(r.kind, r.text) for r in extract_references(path)] == [
        ("command", "/curate")
    ]


def test_an_unbackticked_slash_is_not_a_command_reference(tmp_path):
    """`/tmp`, `/api/search` and `/opt` all appear in these skills as prose."""
    path = _skill(tmp_path, "s", "Write to /tmp and call /api/search.\n")
    assert extract_references(path) == []


# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------


def test_a_path_that_exists_in_claw_is_ok(tmp_path):
    (tmp_path / "conf").mkdir()
    (tmp_path / "conf" / "a.yaml").write_text("{}", encoding="utf-8")
    _skill(tmp_path, "s", "Read `conf/a.yaml`.\n")

    findings = check(tmp_path)

    assert [f.verdict for f in findings] == ["ok"]


def test_a_workspace_path_is_an_output_not_a_missing_file(tmp_path):
    """Skills name the artifacts they write. workspace/ is gitignored runtime
    state, so asserting it exists would fail on every clean checkout."""
    _skill(tmp_path, "s", "Writes `workspace/reports/thing.tsv`.\n")

    findings = check(tmp_path)

    assert [f.verdict for f in findings] == ["output"]


def test_an_unprefixed_path_found_only_downstream_is_ambiguous(tmp_path):
    other = tmp_path / "OtherMech"
    (other / "mappings").mkdir(parents=True)
    (other / "mappings" / "x.tsv").write_text("", encoding="utf-8")
    _skill(tmp_path, "s", "Read `mappings/x.tsv`.\n")

    finding = check(tmp_path, {"OtherMech": other})[0]

    assert finding.verdict == "ambiguous"
    assert "OtherMech" in finding.detail


def test_a_path_absent_everywhere_is_missing(tmp_path):
    other = tmp_path / "OtherMech"
    other.mkdir()
    _skill(tmp_path, "s", "Read `mappings/gone.tsv`.\n")

    assert check(tmp_path, {"OtherMech": other})[0].verdict == "missing"


def test_a_path_absent_from_claw_with_nothing_to_check_against_is_unverifiable(
    tmp_path,
):
    """The #161 rule: a partial answer must say it is partial. With no
    downstream checkout, `mappings/gone.tsv` cannot be called broken."""
    _skill(tmp_path, "s", "Read `mappings/gone.tsv`.\n")

    assert check(tmp_path)[0].verdict == "unverifiable"


def test_a_prefixed_path_is_judged_against_that_repository(tmp_path):
    other = tmp_path / "OtherMech"
    (other / "data").mkdir(parents=True)
    _skill(tmp_path, "s", "Read `OtherMech/data/gone.tsv`.\n")

    finding = check(tmp_path, {"OtherMech": other})[0]

    assert finding.verdict == "missing"
    assert finding.detail.startswith("not in OtherMech")


def test_a_repeated_prefix_is_a_layout_not_a_typo(tmp_path):
    """CommunityMech's checkout sits at CommunityMech/CommunityMech, so a path
    written from the shared parent carries the name twice and both are real."""
    root = tmp_path / "CommunityMech" / "CommunityMech"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "x.csv").write_text("", encoding="utf-8")
    _skill(tmp_path, "s", "Read `CommunityMech/CommunityMech/reports/x.csv`.\n")

    assert check(tmp_path, {"CommunityMech": root})[0].verdict == "ok"


def test_an_unknown_repository_prefix_is_unverifiable_not_missing(tmp_path):
    _skill(tmp_path, "s", "Read `CultureBotHT/data/x.csv`.\n")

    finding = check(tmp_path, {}, repositories={"CultureMech"})[0]

    assert finding.verdict == "unverifiable"
    assert "CultureBotHT" in finding.detail


# --------------------------------------------------------------------------
# reference-root
# --------------------------------------------------------------------------


def test_a_declared_root_resolves_bare_paths(tmp_path):
    kgm = tmp_path / "kg-microbe"
    (kgm / "mappings").mkdir(parents=True)
    (kgm / "mappings" / "x.tsv").write_text("", encoding="utf-8")
    _skill(
        tmp_path, "s", "Read `mappings/x.tsv`.\n", frontmatter="reference-root: kg-microbe\n"
    )

    assert check(tmp_path, {"kg-microbe": kgm})[0].verdict == "ok"


def test_a_declared_root_does_not_stop_a_skill_citing_claw(tmp_path):
    """Every skill that declares one also cites claw's own files; claw is tried
    first, so the declaration only decides what claw does not answer."""
    kgm = tmp_path / "kg-microbe"
    kgm.mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "sync.py").write_text("", encoding="utf-8")
    _skill(
        tmp_path,
        "s",
        "Run `scripts/sync.py`.\n",
        frontmatter="reference-root: kg-microbe\n",
    )

    assert check(tmp_path, {"kg-microbe": kgm})[0].verdict == "ok"


def test_a_per_mech_declaration_is_satisfied_by_any_mech(tmp_path):
    """`scripts/.vendored_canon_ref` is one file in every Mech. Naming a single
    Mech would state something the skill does not mean."""
    one, two = tmp_path / "A", tmp_path / "B"
    (one / "scripts").mkdir(parents=True)
    (one / "scripts" / "pin").write_text("", encoding="utf-8")
    two.mkdir()
    _skill(tmp_path, "s", "Read `scripts/pin`.\n", frontmatter="reference-root: mech\n")

    assert check(tmp_path, {"A": one, "B": two})[0].verdict == "ok"


def test_a_per_mech_declaration_present_in_no_mech_is_missing(tmp_path):
    one = tmp_path / "A"
    one.mkdir()
    _skill(tmp_path, "s", "Read `scripts/pin`.\n", frontmatter="reference-root: mech\n")

    assert check(tmp_path, {"A": one})[0].verdict == "missing"


def test_an_undeclarable_reference_root_is_unverifiable(tmp_path):
    _skill(tmp_path, "s", "Read `x/y.tsv`.\n", frontmatter="reference-root: nowhere\n")

    finding = check(tmp_path, {"A": tmp_path / "A"}, repositories={"A"})[0]

    assert finding.verdict == "unverifiable"
    assert "nowhere" in finding.detail


def test_reference_root_is_absent_when_not_declared(tmp_path):
    path = _skill(tmp_path, "s", "body\n")
    assert reference_root(path) is None


# --------------------------------------------------------------------------
# Command references
# --------------------------------------------------------------------------


def test_a_command_reference_must_name_a_real_skill_or_command(tmp_path):
    _skill(tmp_path, "caller", "Run `/callee` then `/ghost`.\n")
    _skill(tmp_path, "callee", "body\n")

    verdicts = {f.reference.text: f.verdict for f in check(tmp_path)}

    assert verdicts == {"/callee": "ok", "/ghost": "missing"}


# --------------------------------------------------------------------------
# The repository's own skills
# --------------------------------------------------------------------------


def test_there_are_skills_to_check():
    """Guards everything below: an empty list would pass vacuously."""
    assert len(skill_files(ROOT)) >= 20


def test_no_skill_reference_is_broken_within_claw():
    """The offline half of the gate: references claw can resolve by itself.

    Downstream repositories are not checked out in CI, so this asserts only
    what one checkout can know -- which is exactly the distinction the
    unverifiable verdict exists to preserve.
    """
    findings = check(ROOT)
    broken = [f for f in findings if f.verdict in ("missing", "ambiguous")]

    assert not broken, format_report(findings)


def test_the_report_lists_problems_and_only_counts_the_rest(tmp_path):
    _skill(tmp_path, "s", "Read `mappings/gone.tsv` and write `workspace/o.tsv`.\n")

    report = format_report(check(tmp_path, {"A": tmp_path}))

    assert "1 missing" in report and "1 output" in report
    assert "mappings/gone.tsv" in report
    assert "workspace/o.tsv" not in report


# --------------------------------------------------------------------------
# The CLI finds the checkout it is meant to check
# --------------------------------------------------------------------------


def test_the_claw_root_is_found_from_the_working_directory(tmp_path, monkeypatch):
    """Deriving it from `__file__` works only while the package runs from its
    source tree. Installed into site-packages -- which is what the CI step
    does -- `parents[2]` lands in the virtualenv and every skill vanishes at
    once, reported as a clean run over zero references."""
    from kg_microbe_skills.__main__ import find_claw_root

    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert find_claw_root() == tmp_path.resolve()


def test_no_checkout_is_a_refusal_not_an_empty_pass(tmp_path, monkeypatch):
    from kg_microbe_skills.__main__ import find_claw_root

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="no .claude/skills directory"):
        find_claw_root(tmp_path)


def test_a_fenced_code_block_is_out_of_scope_and_stays_that_way(tmp_path):
    """Backticked text only. Fenced blocks carry shell variables, ratios and
    slash-separated word lists that these rules would misread as paths; the
    cost is that a moved file cited in a command example is not caught (#202).
    """
    _skill(
        tmp_path,
        "s",
        "```bash\npython3 scripts/definitely_gone.py --flag\n```\n",
    )

    assert check(tmp_path) == []


# --------------------------------------------------------------------------
# #203: the same reference must get the same verdict on every machine
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repository(root: Path, tracked: dict[str, str], ignore: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    if ignore:
        (root / ".gitignore").write_text(ignore, encoding="utf-8")
        tracked = {**tracked, ".gitignore": ignore}
    for relative, content in tracked.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _git(root, "add", "--", relative)
    if tracked:
        _git(root, "commit", "-qm", "seed")
    return root


def test_an_untracked_file_is_missing_even_though_it_is_right_there(tmp_path):
    """The #203 failure. `data/kgm` existed on one laptop and in no clone, so
    the checker passed locally and failed in CI on the same commit."""
    mech = _repository(tmp_path / "OtherMech", {"README.md": "x"})
    (mech / "data" / "kgm").mkdir(parents=True)
    (mech / "data" / "kgm" / "local.owl").write_text("x", encoding="utf-8")
    _skill(tmp_path, "s", "Left `OtherMech/data/kgm` alone.\n")

    finding = check(tmp_path, {"OtherMech": mech})[0]

    assert finding.verdict == "missing", "present locally is not present for a reader"
    assert "git neither tracks it nor declares it generated" in finding.detail


def test_a_gitignored_artifact_is_an_output_not_a_failure(tmp_path):
    """CommunityMech ignores `reports/*.csv`. A skill naming an artifact the
    repository itself declares generated is describing output, which is the
    workspace/ rule generalized instead of special-cased for claw."""
    mech = _repository(
        tmp_path / "OtherMech", {"README.md": "x"}, ignore="reports/*.csv\n"
    )
    _skill(tmp_path, "s", "Reads `OtherMech/reports/ingredient_mapping.csv`.\n")

    finding = check(tmp_path, {"OtherMech": mech})[0]

    assert finding.verdict == "output"
    assert "generated" in finding.detail


def test_a_tracked_file_is_ok_when_it_is_not_even_checked_out(tmp_path):
    """git answers for a path the working tree does not have, which is what
    makes the verdict the same in a sparse or partial clone."""
    mech = _repository(tmp_path / "OtherMech", {"mappings/x.tsv": "a"})
    (mech / "mappings" / "x.tsv").unlink()
    _skill(tmp_path, "s", "Read `OtherMech/mappings/x.tsv`.\n")

    assert check(tmp_path, {"OtherMech": mech})[0].verdict == "ok"


def test_a_directory_counts_as_tracked_when_it_holds_tracked_files(tmp_path):
    mech = _repository(tmp_path / "OtherMech", {"mappings/canonical/x.tsv": "a"})
    _skill(tmp_path, "s", "See `OtherMech/mappings/canonical`.\n")

    assert check(tmp_path, {"OtherMech": mech})[0].verdict == "ok"


def test_a_directory_that_is_not_a_checkout_falls_back_to_the_filesystem(tmp_path):
    """Tests and ad-hoc callers hand in plain directories; refusing them would
    make the library unusable outside a clone."""
    plain = tmp_path / "Plain"
    (plain / "data").mkdir(parents=True)
    (plain / "data" / "x.tsv").write_text("", encoding="utf-8")
    _skill(tmp_path, "s", "Read `Plain/data/x.tsv`.\n")

    assert check(tmp_path, {"Plain": plain})[0].verdict == "ok"
