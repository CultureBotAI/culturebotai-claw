"""#236. A capability `reason` is prose about another repository, and prose rots.

One reason named a `.github/workflows/generate-pages.yaml` that TraitMech does
not have; the sentence had been copied from the three Mechs that do. Nothing
noticed, because nothing checked -- and a reason is the *only* explanation a
reader gets for why a Mech opted out of a capability.

Rather than parse the English, each reason declares which paths it asserts about
and in which direction. These tests hold that declaration to both directions:

  - every path a reason mentions must be declared, so a new unchecked claim
    cannot be added by writing a sentence; and
  - every declared path must be mentioned, so the declaration cannot drift into
    a list of things the reason no longer says.

`absent` carries as much weight as `present`: over half these reasons exist to
say a Mech has *no* download.yaml, and a check that only confirmed existence
would have nothing to say about them.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kg_microbe_fleet import (
    FleetManifestError,
    ReasonClaims,
    load_fleet_manifest,
    parse_fleet_manifest,
)
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root

MANIFEST = load_fleet_manifest()
CLAW_ROOT = Path(__file__).resolve().parents[1]

# A path-like token: a name carrying an extension we would expect to resolve.
# `.html` is deliberately absent -- several reasons say "missing .html files"
# as a description of a class of file, not as a path.
# Two shapes, because a reason names two kinds of thing. A file is recognised by
# its extension. A directory is recognised by its trailing slash -- "under
# pages/" is a claim about a path, "per-source scripts" is a plural noun, and the
# slash is the only thing that tells them apart without guessing. Requiring the
# slash also tells an author how to make a claim checkable (#246).
#
# `.html` is deliberately absent from the extension list: several reasons say
# "missing .html files" as a description of a class of file, not as a path.
_PATH_TOKEN = re.compile(
    r"(?<![\w/.])\.?[\w][\w./-]*"
    r"(?:\.(?:py|ya?ml|json|tsv|toml|cfg|sh)\b|/(?=[\s,;.)\]]|$))"
)

CLAW_PREFIX = "claw:"


def _declared(claims: ReasonClaims) -> tuple[str, ...]:
    return (*claims.present, *claims.absent)


def _reasons():
    for mech_name, mech in MANIFEST.mechs.items():
        for cap_name, capability in mech.capabilities.items():
            reason = (capability.reason or "").strip()
            if reason:
                yield mech_name, cap_name, " ".join(reason.split()), capability


_ALL = list(_reasons())
_IDS = [f"{m}.{c}" for m, c, _, _ in _ALL]


@pytest.mark.parametrize(("mech", "cap", "reason", "capability"), _ALL, ids=_IDS)
def test_every_path_a_reason_names_is_declared(mech, cap, reason, capability):
    """Forward direction: prose cannot make an unchecked claim."""
    declared = {Path(p.removeprefix(CLAW_PREFIX)).name for p in _declared(capability.reason_claims)}
    undeclared = {
        token for token in _PATH_TOKEN.findall(reason) if Path(token).name not in declared
    }
    assert not undeclared, (
        f"{mech}.{cap}'s reason names {sorted(undeclared)}, which it does not "
        f"declare in reason_claims, so nothing verifies the claim"
    )


@pytest.mark.parametrize(("mech", "cap", "reason", "capability"), _ALL, ids=_IDS)
def test_every_declared_path_is_one_the_reason_names(mech, cap, reason, capability):
    """Reverse direction: the declaration cannot outlive the sentence it checks."""
    orphans = [
        path
        for path in _declared(capability.reason_claims)
        if Path(path.removeprefix(CLAW_PREFIX)).name not in reason
    ]
    assert not orphans, (
        f"{mech}.{cap} declares {orphans}, which its reason no longer mentions; "
        f"either the reason was rewritten or the declaration is stale"
    )


def test_the_reasons_that_make_checkable_claims_are_the_ones_declared():
    """A ledger, so the count can only go up deliberately. The rest are
    judgements about scope ("trait records are not an environment inventory
    input") with nothing to resolve."""
    declared = sorted(
        f"{m}.{c}" for m, c, _, cap in _ALL if cap.reason_claims
    )
    assert declared == [
        "antibioticmech.deep_research",
        "antibioticmech.page_budgets",
        "antibioticmech.writer_audit",
        "cellstructuremech.deep_research",
        "cellstructuremech.page_budgets",
        "cellstructuremech.source_catalogue",
        "cellstructuremech.unmapped_inventory_input",
        "cellstructuremech.writer_audit",
        "communitymech.page_budgets",
        "communitymech.source_catalogue",
        "communitymech.source_queue",
        "culturemech.kgx_export",
        "culturemech.page_budgets",
        "culturemech.source_catalogue",
        "culturemech.source_queue",
        "mediaingredientmech.page_budgets",
        "mediaingredientmech.source_catalogue",
        "mediaingredientmech.source_queue",
        "proteintraitsmech.source_queue",
        "proteintraitsmech.unmapped_inventory_input",
        "proteintraitsmech.writer_audit",
        "traitmech.page_budgets",
        "traitmech.source_queue",
        "traitmech.unmapped_inventory_input",
    ]


def _tracked_on_main(root: Path, relative: str) -> bool | None:
    """Whether `origin/main` of the repository at `root` tracks `relative`.

    None when that cannot be answered -- no git, no `origin/main`.

    Deliberately not `(root / relative).exists()`. A capability reason describes
    the repository, and a local checkout is on whatever branch its owner is
    working on. Asking the filesystem asked "is this file here right now",
    which is a different question with a different answer: CellStructureMech's
    `vendored-governance` branch carries two files its main does not, and every
    claim about their absence failed for anyone who happened to have that branch
    checked out while passing in CI, which has no checkout at all. Reading from
    `origin/main` is the #203 move -- ask git, not the working tree.
    """
    probe = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"origin/main:{relative}"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return True
    # Distinguish "main does not have it" from "there is no main to ask".
    has_main = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "origin/main"],
        capture_output=True,
    )
    return False if has_main.returncode == 0 else None


@pytest.mark.parametrize(("mech", "cap", "reason", "capability"), _ALL, ids=_IDS)
def test_a_declared_claim_holds_against_the_repository(mech, cap, reason, capability):
    """The point of the whole exercise: `present` must be tracked and `absent`
    must not be, on the branch the repository actually publishes."""
    claims = capability.reason_claims
    if not claims:
        pytest.skip(f"{mech}.{cap} makes no checkable claim")

    def tracked(path: str) -> tuple[bool | None, str, str]:
        if path.startswith(CLAW_PREFIX):
            # claw is the repository under review, so its working tree is the
            # state that matters -- a claim about a file this branch adds should
            # hold before that branch merges.
            relative = path.removeprefix(CLAW_PREFIX)
            return (CLAW_ROOT / relative).exists(), relative, "claw"
        try:
            root = resolve_mech_root(mech, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            pytest.skip(f"needs a {mech} checkout: {exc}")
        return _tracked_on_main(root, path), path, f"{root.name} origin/main"

    for path in claims.present:
        found, relative, where = tracked(path)
        if found is None:
            pytest.skip(f"{where} cannot be read")
        assert found, (
            f"{mech}.{cap}'s reason asserts {relative} exists in {where}, "
            f"and it does not"
        )
    for path in claims.absent:
        found, relative, where = tracked(path)
        if found is None:
            pytest.skip(f"{where} cannot be read")
        assert not found, (
            f"{mech}.{cap}'s reason asserts {relative} does NOT exist in "
            f"{where}, and it does"
        )


def test_the_claw_prefixed_claims_are_checked_even_with_no_mech_checkout():
    """`claw:` paths live in this repository, so they never skip. All three
    unmapped_inventory_input reasons name a claw script; if that check could
    skip, the only always-runnable case would be the one that never runs."""
    checked = 0
    for mech, cap, _, capability in _ALL:
        for path in capability.reason_claims.present:
            if path.startswith(CLAW_PREFIX):
                assert (CLAW_ROOT / path.removeprefix(CLAW_PREFIX)).exists(), (
                    f"{mech}.{cap} names a claw path that does not exist"
                )
                checked += 1
    assert checked == 3


# -- what the loader rejects ------------------------------------------------


MANIFEST_PATH = CLAW_ROOT / "src/kg_microbe_fleet/fleet.yaml"


def _parse(text: str):
    return parse_fleet_manifest(yaml.safe_load(text), MANIFEST_PATH)


def _manifest_with(claims_block: str) -> str:
    text = MANIFEST_PATH.read_text()
    anchor = """      source_catalogue:
        status: disabled
        reason: >-
          Has no download.yaml; its inputs arrive through per-source scripts
          rather than a declared catalogue. Adopting one would apply here;
          it has not been written.
        reason_claims:
          absent:
            - download.yaml
"""
    assert anchor in text
    replacement = anchor[: anchor.index("        reason_claims:")] + claims_block
    return text.replace(anchor, replacement, 1)


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ("        reason_claims:\n          maybe:\n            - x.yaml\n", "unknown keys"),
        ("        reason_claims:\n          present:\n            - /etc/passwd\n", "inside the"),
        # The prefixed forms: the scope must be split off before containment is
        # judged, or "claw:/etc/passwd" passes a startswith("/") check and the
        # consumer resolves an absolute path out of the repository.
        ("        reason_claims:\n          present:\n            - claw:/etc/passwd\n", "inside the"),
        ("        reason_claims:\n          present:\n            - claw:../escape.yaml\n", "inside the"),
        ("        reason_claims:\n          present:\n            - notascope:x.yaml\n", "unknown scope"),
        ("        reason_claims:\n          present:\n            - ../escape.yaml\n", "inside the"),
        (
            "        reason_claims:\n          present:\n            - a.yaml\n"
            "          absent:\n            - a.yaml\n",
            "both present and absent",
        ),
        (
            "        reason_claims:\n          present:\n            - a.yaml\n            - a.yaml\n",
            "repeats",
        ),
        ("        reason_claims:\n          present: notalist\n", "must be a list"),
    ],
    ids=[
        "unknown-key",
        "absolute",
        "scoped-absolute",
        "scoped-parent-escape",
        "unknown-scope",
        "parent-escape",
        "contradiction",
        "duplicate",
        "not-a-list",
    ],
)
def test_the_loader_rejects_an_unusable_declaration(block, message):
    with pytest.raises(FleetManifestError, match=message):
        _parse(_manifest_with(block))


def test_claims_without_a_reason_are_rejected():
    """A declaration with nothing to check is a mistake, not an empty success."""
    text = MANIFEST_PATH.read_text()
    anchor = """      vendored_sync:
        status: enabled
"""
    assert anchor in text
    broken = text.replace(
        anchor,
        anchor + "        reason_claims:\n          present:\n            - justfile\n",
        1,
    )
    with pytest.raises(FleetManifestError, match="nothing to check"):
        _parse(broken)


# -- reading the repository rather than the working tree ---------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@x",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@x",
        },
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A checkout with an `origin/main` and a feature branch that adds a file.

    This is the shape that broke: CellStructureMech's `vendored-governance`
    branch carries `scripts/validate_id_label_correspondence.py`, its main does
    not, and a claim that main lacks the file failed for anyone with that branch
    checked out while passing in CI, which has no checkout at all.
    """
    upstream = tmp_path / "upstream.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-b", "main", str(upstream))
    _git(tmp_path, "clone", str(upstream), str(work))
    (work / "on-main.txt").write_text("")
    _git(work, "add", "on-main.txt")
    _git(work, "commit", "-m", "main")
    _git(work, "push", "-u", "origin", "main")
    _git(work, "checkout", "-b", "feature")
    (work / "only-on-branch.txt").write_text("")
    _git(work, "add", "only-on-branch.txt")
    _git(work, "commit", "-m", "branch")
    return work


def test_a_file_tracked_on_main_is_found(repository: Path):
    assert _tracked_on_main(repository, "on-main.txt") is True


def test_a_file_only_on_the_checked_out_branch_is_not_on_main(repository: Path):
    """The whole point. It is right there in the working tree, and the answer is
    still False, because the reason describes the repository rather than
    whichever branch its owner is working on."""
    assert (repository / "only-on-branch.txt").exists()
    assert _tracked_on_main(repository, "only-on-branch.txt") is False


def test_a_file_in_neither_is_absent(repository: Path):
    assert _tracked_on_main(repository, "nowhere.txt") is False


def test_a_repository_with_no_origin_main_cannot_answer(tmp_path: Path):
    """Distinguished from "absent": a checkout with no origin/main has not said
    the file is missing, it has said nothing. Conflating the two would report
    every `present` claim as broken against such a checkout."""
    solo = tmp_path / "solo"
    solo.mkdir()
    _git(tmp_path, "init", "-b", "main", str(solo))
    (solo / "here.txt").write_text("")
    _git(solo, "add", "here.txt")
    _git(solo, "commit", "-m", "only local")
    assert _tracked_on_main(solo, "here.txt") is None


def test_a_directory_that_is_not_a_repository_cannot_answer(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "here.txt").write_text("")
    assert _tracked_on_main(plain, "here.txt") is None


def _stub(present: tuple[str, ...] = (), absent: tuple[str, ...] = ()):
    return SimpleNamespace(reason_claims=ReasonClaims(present=present, absent=absent))


def test_the_check_itself_reads_main_not_the_working_tree(repository: Path, monkeypatch):
    """`_tracked_on_main` being right is not enough -- the assertion has to use
    it. This drives the real check against a checkout whose branch carries a
    file its main does not, which is the situation that broke."""
    monkeypatch.setattr(
        "kg_microbe_fleet.roots.resolve_mech_root", lambda *a, **k: repository
    )
    monkeypatch.setitem(
        test_a_declared_claim_holds_against_the_repository.__globals__,
        "resolve_mech_root",
        lambda *a, **k: repository,
    )
    # main does not track it, so asserting its absence must hold even though the
    # file is sitting in the working tree.
    assert (repository / "only-on-branch.txt").exists()
    test_a_declared_claim_holds_against_the_repository(
        "traitmech", "x", "only-on-branch.txt", _stub(absent=("only-on-branch.txt",))
    )
    # ...and asserting its presence must not.
    with pytest.raises(AssertionError, match="and it does not"):
        test_a_declared_claim_holds_against_the_repository(
            "traitmech", "x", "only-on-branch.txt", _stub(present=("only-on-branch.txt",))
        )


def test_an_unreadable_repository_skips_rather_than_passing(tmp_path: Path, monkeypatch):
    """A checkout that cannot answer must not be read as agreement. Returning
    instead of skipping would turn every claim about such a repository into a
    silent pass -- the #216 shape, where the guard reports success precisely
    when it has learned nothing."""
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setitem(
        test_a_declared_claim_holds_against_the_repository.__globals__,
        "resolve_mech_root",
        lambda *a, **k: plain,
    )
    with pytest.raises(pytest.skip.Exception):
        test_a_declared_claim_holds_against_the_repository(
            "traitmech", "x", "anything.txt", _stub(present=("anything.txt",))
        )
    with pytest.raises(pytest.skip.Exception):
        test_a_declared_claim_holds_against_the_repository(
            "traitmech", "x", "anything.txt", _stub(absent=("anything.txt",))
        )


# -- what the token scanner can see (#246) ----------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("built through .github/workflows/generate-pages.yaml", [".github/workflows/generate-pages.yaml"]),
        ("has no download.yaml", ["download.yaml"]),
        ("through scripts/seed.py, which", ["scripts/seed.py"]),
        # The gap #246 was filed for: a directory carries no extension.
        ("written by hand under research/ with", ["research/"]),
        ("serves 490 pages under pages/, straight from main", ["pages/"]),
        ("everything below data/", ["data/"]),
        ("nothing under conf/.", ["conf/"]),
        # ...and the prose that must not be mistaken for one.
        ("arrives through per-source scripts rather than", []),
        ("the repository has not decided", []),
        ("reports missing .html files that the build creates", []),
        ("adopting research would apply here", []),
    ],
    ids=[
        "workflow-path", "bare-file", "script-with-comma",
        "directory", "directory-before-comma", "directory-at-end",
        "directory-before-period",
        "plural-noun", "prose", "extension-as-a-class", "bare-word",
    ],
)
def test_the_scanner_sees_paths_and_not_prose(text, expected):
    """A file is recognised by its extension, a directory by its trailing
    slash. Without the slash there is nothing to separate "under research/"
    from "per-source scripts", and guessing would either miss real claims or
    demand declarations for ordinary English."""
    assert _PATH_TOKEN.findall(text) == expected


def test_a_directory_claim_is_matched_against_its_declaration():
    """`Path("pages/").name` is "pages", which is how a trailing-slash token in
    prose lines up with the declaration that carries no slash."""
    assert Path("pages/").name == "pages"
    assert Path("research/").name == "research"


def test_the_widened_scanner_found_a_real_undeclared_claim():
    """CellStructureMech's deep_research reason says its research is "written by
    hand under research/". True, and undeclared until #246 -- the scanner could
    not see a path without an extension, so the forward guarantee did not reach
    it. This pins the declaration that closed it."""
    claims = (
        MANIFEST.mechs["cellstructuremech"].capabilities["deep_research"].reason_claims
    )
    assert claims.present == ("research",)
