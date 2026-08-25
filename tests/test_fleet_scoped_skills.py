"""General fleet skills resolve scope and paths from the packaged manifest."""

from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]
GENERAL_FLEET_SKILLS = {
    "boss",
    "cross-mech-sync",
    "fleet-pr-review",
    "fleet-pr-status",
    "schema-gap-analysis",
}


def _skill(name: str) -> str:
    return (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text(
        encoding="utf-8"
    )


def test_general_fleet_skill_catalogue_covers_every_manifest_consumer():
    discovered = {
        path.parent.name
        for path in (ROOT / ".claude" / "skills").glob("*/SKILL.md")
        if any(
            marker in path.read_text(encoding="utf-8")
            for marker in (
                "kg_microbe_fleet",
                "canonical fleet manifest",
                "manifest-defined Mech fleet",
            )
        )
    }

    assert discovered == GENERAL_FLEET_SKILLS


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
