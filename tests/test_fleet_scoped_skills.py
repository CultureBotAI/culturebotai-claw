"""General fleet skills resolve scope and paths from the packaged manifest."""

from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_skills.catalogue import load_catalogue

ROOT = Path(__file__).resolve().parents[1]
# Was a hardcoded set of five names here -- invisible to anything else, and
# already stale: `cross-repo-sync` and `unmapped-inventory` are fleet-scoped
# too and were never added. It now comes from the packaged catalogue, which is
# checked against .claude/skills in both directions (#132 Phase 4, #131).
GENERAL_FLEET_SKILLS = {
    name for name, entry in load_catalogue().items() if entry.scope == "fleet"
}


def _skill(name: str) -> str:
    return (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text(
        encoding="utf-8"
    )


# A skill that *runs* the manifest resolves fleet scope from it. Naming the
# manifest in prose does not: a repo-scoped skill may legitimately cite
# `src/kg_microbe_fleet/fleet.yaml` as a source of truth without enumerating
# the fleet. The previous substring net could not tell those apart, so a
# citation-only skill tripped it and the failure pointed at registering a
# capability the skill does not have (#158).
MANIFEST_EXECUTION_MARKERS = (
    "python -m kg_microbe_fleet",
    "from kg_microbe_fleet",
    "load_fleet_manifest",
)


def _skill_paths() -> list[Path]:
    return sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))


def _frontmatter(path: Path) -> dict:
    """Parse a skill's YAML frontmatter, naming the file when it cannot.

    Parsed with the real YAML loader rather than by hand: a block-style
    `tags:` list reads as no tags under a single-line parser, which drops the
    skill out of the declared set and reports the wrong reason (#160).
    """
    parts = path.read_text(encoding="utf-8").split("---")
    assert len(parts) >= 3, f"{path} has no YAML frontmatter block"
    loaded = yaml.safe_load(parts[1])
    assert isinstance(loaded, dict), f"{path} frontmatter is not a YAML mapping"
    return loaded


def _tags(path: Path) -> set[str]:
    return {str(tag) for tag in _frontmatter(path).get("tags") or ()}


def test_general_fleet_skill_catalogue_matches_the_declared_fleet_tag():
    """The catalogue is what skills declare, not what their prose mentions."""
    declared = {path.parent.name for path in _skill_paths() if "fleet" in _tags(path)}

    assert declared == GENERAL_FLEET_SKILLS


def test_every_skill_that_runs_the_manifest_is_in_the_catalogue():
    """A forgotten `fleet` tag must still be caught.

    Subset, not equality: a registered skill may resolve scope through a script
    rather than an inline call (`fleet-pr-status` does), so the catalogue may be
    larger than this set -- but nothing may execute the manifest from outside it.
    """
    executing = {
        path.parent.name
        for path in _skill_paths()
        if any(
            marker in path.read_text(encoding="utf-8")
            for marker in MANIFEST_EXECUTION_MARKERS
        )
    }

    assert executing <= GENERAL_FLEET_SKILLS, (
        f"skills run the fleet manifest but are not in GENERAL_FLEET_SKILLS: "
        f"{sorted(executing - GENERAL_FLEET_SKILLS)}. Add the `fleet` tag and "
        f"register them, or stop resolving fleet scope from the manifest."
    )


def test_citing_the_manifest_in_prose_does_not_join_the_catalogue():
    """#158: the guard must leave a repo-scoped skill free to name the manifest."""
    citation_only = [
        path.parent.name
        for path in _skill_paths()
        if "kg_microbe_fleet" in path.read_text(encoding="utf-8")
        and not any(
            marker in path.read_text(encoding="utf-8")
            for marker in MANIFEST_EXECUTION_MARKERS
        )
        and "fleet" not in _tags(path)
    ]

    for name in citation_only:
        assert name not in GENERAL_FLEET_SKILLS, (
            f"{name} only cites the manifest; it should not be registered as a "
            f"fleet-scope-resolving skill"
        )


def test_cross_mech_sync_queries_applicable_manifest_repositories():
    text = _skill("cross-mech-sync")

    assert "python -m kg_microbe_fleet list --capability <CAPABILITY> --format tsv" in text
    assert "for entry in" not in text
    assert "/Users/" not in text


def test_cross_mech_sync_fails_closed_and_uses_owned_locks():
    text = _skill("cross-mech-sync")

    assert "requires_internet: true" in text
    assert text.index('TASK_SLUG="${TASK_SLUG:-}"') < text.index(
        "set -euo pipefail"
    )
    assert "set -euo pipefail" in text
    assert "python -m kg_microbe_fleet targets" in text
    assert 'cat-file -e "origin/main:$f"' in text
    assert 'if not acquired:' in text
    assert 'timeout=task_limit + 300' in text
    assert 'finally:' in text
    assert 'manager.release_lock(resource)' in text
    assert 'mktemp -d "${TMPDIR:-/tmp}/cross-mech-${TARGET_KEY}.XXXXXX"' in text
    assert 'gh pr create -R "$TARGET_GITHUB"' in text
    assert 'gh pr merge "$PR_NUMBER" -R "$TARGET_GITHUB"' in text
    assert '--match-head-commit "$local_head"' in text
    assert 'bash "$OPERATION_SCRIPT" "$WT" "$BRANCH"' in text
    assert 'run_with_repo_lock "$TARGET_KEY" 3600' not in text
    assert "no owner-token bypass" in text
    assert 'worktree add -b "$BRANCH" "$WT" origin/main' in text
    assert "refs/heads/main:refs/remotes/origin/main" in text
    ground_truth = text.split(
        "### C. Establish ground truth under short metadata locks", 1
    )[1].split("### D.", 1)[0]
    assert 'run_with_repo_lock "$key" 300' in ground_truth
    assert 'git -C "$repo_root" fetch origin' in ground_truth
    assert 'git -C "$repo_root" fetch origin -q' not in text
    assert "merge-base --is-ancestor origin/main HEAD" in text
    assert 'update-ref -d "refs/heads/$BRANCH" "$local_head"' in text
    assert 'test "$pr_base" = "main"' in text
    assert 'test "$pr_branch" = "$BRANCH"' in text
    assert 'test "$pr_head" = "$local_head"' in text
    assert 'test "$pr_head_repo" = "$TARGET_GITHUB"' in text
    assert "git -C \"$REPO\" branch -d" not in text
    assert 'PR_BODY_FILE="$SYNC_DIR/pr-body.md"' in text
    assert 'test -s "$PR_BODY_FILE"' in text
    assert 'rm -- "$OPERATION_SCRIPT" "$PR_BODY_FILE"' in text
    assert "worktree remove --force" not in text
    assert "-R <slug>" not in text


def test_cross_mech_sync_uses_claw_authoritative_governance_rail():
    text = _skill("cross-mech-sync")

    assert "src/kg_microbe_governance/vendored_artifacts.json" in text
    assert "scripts/.vendored_canon_ref" in text
    assert "kg-microbe-governance sync" in text
    assert "kg-microbe-governance check" in text
    assert "kg-microbe-governance fleet-audit" in text
    assert "consumer majority is evidence of" in text
    assert "never authority" in text
    assert "just verify-validator-pin" not in text
    assert "VENDORED_IDLABEL_FILES" not in text
    assert ".validate_id_label_correspondence.sha256" not in text
    assert "just refresh-validator-pin" not in text


def test_schema_gap_analysis_queries_schema_profiles_from_manifest():
    text = _skill("schema-gap-analysis")

    assert "python -m kg_microbe_fleet list --capability schema_sync --format json" in text
    assert "| **CultureMech**" not in text
    assert "schema_paths" in text and "record_globs" in text


def test_schema_gap_analysis_is_offline_and_analysis_only():
    text = _skill("schema-gap-analysis")

    assert "requires_internet: false" in text
    assert "analysis-only" in text
    assert "Write a remediation plan; do not apply it in this analysis" in text
    assert "ensurepip" not in text
    assert "pip install" not in text
    assert "table above" not in text
    assert "per-Mech table" not in text


def test_boss_resolves_roots_and_worktrees_portably():
    text = _skill("boss")

    assert "python -m kg_microbe_fleet targets" in text
    assert "--capability coordination_hooks" in text
    assert "FLEET_WORKTREE_ROOT" in text
    assert "/Users/" not in text
    assert "~/worktrees" not in text


def test_boss_uses_safe_prompt_delivery_and_bounded_owned_lock():
    text = _skill("boss")

    assert "requires_internet: true" in text
    assert text.index('SLUG="${SLUG:-}"') < text.index("set -euo pipefail")
    assert "--dangerously-skip-permissions" not in text
    assert "tmux load-buffer" in text
    assert "tmux paste-buffer" in text
    assert 'paste_prompt_file "$SESSION" "$PROMPT_FILE"' in text
    assert 'acquired = manager.acquire_lock(' in text
    assert 'if not acquired:' in text
    assert 'timeout=task_limit + 300' in text
    assert 'finally:' in text
    assert 'manager.release_lock(resource)' in text
    assert 'subprocess.Popen(command)' in text
    assert 'tmux send-keys -t "$SESSION" -l -- "claude"' in text
    assert 'run_locked_command "claude"' not in text
    assert "It must release before Claude starts" in text
    assert 'run_locked_command "create-$SLUG"' in text
    assert 'run_locked_command "remove-$SLUG"' in text
    assert 'worktree add -b "$BRANCH" "$WORKTREE" origin/main' in text
    assert "refs/heads/main:refs/remotes/origin/main" in text
    assert text.index('run_locked_command "fetch-main-$SLUG"') < text.index(
        'worktree add -b "$BRANCH" "$WORKTREE" origin/main'
    )
    assert "no lease across the Agent call" in text
    assert "merge-base --is-ancestor origin/main HEAD" in text
    assert 'update-ref -d "refs/heads/$BRANCH" "$local_head"' in text
    assert "git -C \"$REPO\" branch -d" not in text
    assert 'rm -- "${PROMPT_FILES[@]}" "$LOCK_RUNNER"' in text


def test_squash_cleanup_verifies_merged_head_then_deletes_ref_with_cas():
    for skill_name in ("boss", "cross-mech-sync"):
        text = _skill(skill_name)
        state_guard = 'test "$merged_state" = "MERGED"'
        head_guard = 'test "$merged_head" = "$local_head"'
        cas_delete = 'update-ref -d "refs/heads/$BRANCH" "$local_head"'

        assert state_guard in text
        assert head_guard in text
        assert cas_delete in text
        assert 'test "$merged_base" = "main"' in text
        assert 'test "$merged_branch" = "$BRANCH"' in text
        assert 'test "$merged_head_repo" = "$TARGET_GITHUB"' in text
        assert text.index(state_guard) < text.index(cas_delete)
        assert text.index(head_guard) < text.index(cas_delete)
        assert 'branch -d "$BRANCH"' not in text


def test_fleet_pr_status_skill_declares_manifest_membership():
    text = _skill("fleet-pr-status")

    assert "comes from the canonical fleet manifest" in text
    assert "PREFERRED_ORDER" not in text
    assert "--repo-limit" not in text


def test_fleet_pr_review_uses_only_declared_repository_identities():
    text = _skill("fleet-pr-review")
    manifest = load_fleet_manifest()

    assert 'CLAW_REPOSITORY="CultureBotAI/culturebotai-claw"' in text
    assert "python -m kg_microbe_fleet list --format tsv" in text
    assert "python -m kg_microbe_fleet targets" in text
    assert "--capability testing" in text
    assert 'done < "$REPOSITORIES"' in text
    assert text.count("CultureBotAI/culturebotai-claw") == 1
    assert "gh repo list" not in text
    assert 'test("(?i)mech$' not in text
    assert "HabitatMech" not in text
    assert "| Repo | Role |" not in text
    assert all(mech.github not in text for mech in manifest.mechs.values())
    assert all(mech.display_name not in text for mech in manifest.mechs.values())


# A `fleet` skill that resolves scope through a script rather than an inline
# call. The claim is still checkable -- the script it names must itself read
# the manifest -- so this is a redirection, not an exemption.
RESOLVES_THROUGH_A_SCRIPT = {"fleet-pr-status": "scripts/fleet_pr_status.py"}


@pytest.mark.parametrize("name", sorted(GENERAL_FLEET_SKILLS))
def test_a_fleet_skill_actually_resolves_the_fleet_from_the_manifest(name):
    """The reverse of the subset check above.

    Without this, `fleet` is self-asserted: a skill could carry the tag, sit in
    the catalogue as fleet-scoped, and enumerate its repositories in prose --
    which is exactly the drift #214 found in `unmapped-inventory`. Removing
    that fix while leaving the tag in place passed everything until this test
    existed.
    """
    source = _skill(name)
    if any(marker in source for marker in MANIFEST_EXECUTION_MARKERS):
        return

    script = RESOLVES_THROUGH_A_SCRIPT.get(name)
    assert script, (
        f"{name} is tagged `fleet` but never resolves the manifest; either it "
        f"does and should say how, or the tag and its catalogue scope are wrong"
    )
    assert script in source, f"{name} does not name {script}"
    text = (ROOT / script).read_text(encoding="utf-8")
    assert any(marker in text for marker in MANIFEST_EXECUTION_MARKERS), (
        f"{script} is named as {name}'s way of reaching the manifest but does "
        f"not read it"
    )


@pytest.mark.parametrize("name", sorted(RESOLVES_THROUGH_A_SCRIPT))
def test_a_redirected_skill_still_needs_the_redirection(name):
    """If it grew an inline call, the redirection is dead and should go."""
    assert name in GENERAL_FLEET_SKILLS, f"{name} is no longer fleet-scoped"
    assert not any(marker in _skill(name) for marker in MANIFEST_EXECUTION_MARKERS), (
        f"{name} now reads the manifest directly -- remove it from "
        f"RESOLVES_THROUGH_A_SCRIPT"
    )
