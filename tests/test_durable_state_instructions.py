"""#938: canonical instructions cannot reintroduce disposable session state.

The checker examines instruction units rather than exempting whole files or
accepting a prohibition anywhere in the document. Its contrast fixtures cover
retained state versus caches, read-only probes and mixed safe/unsafe prose.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from kg_microbe_skills.catalogue import (
    CANONICAL_DIR,
    applicable_mechs,
    canonical_regions,
    canonical_text,
    load_canonical,
    render_adapter,
)

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTION_ROOTS = (
    ".claude/skills", ".claude/commands", "src/kg_microbe_skills/canonical",
    "src/kg_microbe_governance/artifacts/prompts",
    "src/kg_microbe_governance/artifacts/docs", "docs",
)
HISTORICAL_ROOTS = ("docs/archive", "docs/reviews")
TEMP = re.compile(r"/private/tmp(?=/|\b)|/tmp(?=/|\b)|\$\{?TMPDIR\b")
STATE = re.compile(r"\b(?:campaigns?|clones?|worktrees?|handoffs?|reviews?|batches|batch|"
                   r"receipts?|evidence|bundles?|session|state|plans?|reports?)\b", re.I)
WRITE = re.compile(r"\b(?:use|clone|worktree\s+add|mktemp|mkdir|write|save|store|"
                   r"create|put|keep|place)\b|--(?:output|receipt|report)\b", re.I)
PROHIBITION = re.compile(r"\b(?:never|do not|must not)\s+(?:store|use|put|keep|save|place|"
                         r"write|create|in)\b", re.I)
MIXED_DIRECTIVE = re.compile(
    r"(?:[,;]|\b(?:but|and|then)\b)\s*(?:instead\s+|also\s+)?"
    r"(?:use|clone|write|save|store|create|put|keep|place)\b", re.I)


def instruction_paths(root: Path) -> list[Path]:
    # pathlib enumeration includes ignored files; gitignore must not hide a
    # newly added instruction from this regression gate.
    paths = {root / "AGENTS.md", root / "README.md"}
    for relative in INSTRUCTION_ROOTS:
        paths.update((root / relative).rglob("*.md"))
    return sorted(path for path in paths if path.is_file() and not any(
        path.is_relative_to(root / historical) for historical in HISTORICAL_ROOTS))


def units(text: str) -> list[str]:
    """Keep shell lines separate; join wrapped prose, then split sentences."""
    result: list[str] = []
    prose: list[str] = []
    in_fence = False
    shell: list[str] = []

    def flush_prose():
        if prose:
            joined = " ".join(line.strip() for line in prose)
            result.extend(re.split(r"(?<=[.!?;])\s+", joined))
            prose.clear()

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            flush_prose()
            if shell:
                result.append(" ".join(shell))
                shell.clear()
            in_fence = not in_fence
        elif in_fence:
            shell.append(line.strip().removesuffix("\\"))
            if not line.rstrip().endswith("\\"):
                result.append(" ".join(shell))
                shell.clear()
        elif not line.strip():
            flush_prose()
        else:
            prose.append(line)
    flush_prose()
    if shell:
        result.append(" ".join(shell))
    return result


def unsafe_temp_instructions(text: str) -> list[str]:
    findings = []
    for unit in units(text):
        if not TEMP.search(unit):
            continue
        plain = unit.replace("`", "").strip()
        if PROHIBITION.search(plain) and not MIXED_DIRECTIVE.search(plain):
            continue
        # Cache allowances cannot excuse a review bundle merely named cache.
        if (not STATE.search(plain)
                and re.search(r"\b(?:disposable|regenerable|pytest)\b", plain, re.I)
                and re.search(r"\b(?:caches?|fixtures?|tmp_path)\b", plain, re.I)):
            continue
        # A command inspecting the unsafe root is not an instruction to write
        # there. Restrict this exception to the existing read-only inspector.
        if ("scripts/fleet_git_and_temp_hygiene.py" in plain
                and "--tmp-root" in plain and not WRITE.search(plain)):
            continue
        if (not WRITE.search(plain) and re.search(
                r"\b(?:audit(?:s)?|inspect|inventory|scan|sitting|deduplicates|resolves|read-only)\b",
                plain, re.I)):
            continue
        findings.append(unit)
    return findings


def test_session_state_examples_avoid_system_temp():
    findings = [(str(path.relative_to(ROOT)), unit)
                for path in instruction_paths(ROOT)
                for unit in unsafe_temp_instructions(path.read_text())]
    assert not findings, findings


@pytest.mark.parametrize("text", [
    "Create a review campaign under /tmp/reviews.",
    "Keep the handoff in /private/tmp/handoff.json.",
    "Use $TMPDIR for batch clones.",
    '```bash\nSTATE="$(mktemp -d "${TMPDIR:-/tmp}/campaign.XXXXXX")"\n```',
    "```bash\ngit clone origin /tmp/clone\n```",
    "Never use /tmp for session state.\n\nSave review bundles in /tmp/cache.",
    "Never store a handoff in /tmp; create the review clone in /tmp/clone.",
    "Never use /tmp for caches but save the campaign in /tmp/work.",
    "Never use /tmp for caches and keep the handoff in /tmp/handoff.",
    "Audit risky paths, then create a campaign in /tmp/work.",
    "Inspect /tmp and clone the repository there.",
    "Use /tmp for the campaign inventory.",
    "Save review evidence in /tmp/cache as a disposable cache.",
])
def test_new_unsafe_instructions_are_detected(text):
    assert unsafe_temp_instructions(text)


@pytest.mark.parametrize("text", [
    "Never store session state in /tmp, /private/tmp or $TMPDIR.",
    "Use /tmp/cache for disposable caches.",
    "Pytest temporary fixtures may use /private/tmp/pytest.",
    "Inspect files already sitting in /tmp.",
    "This is a bounded inventory, not a scan of all /tmp or every user directory.",
    "```bash\nuv run python scripts/fleet_git_and_temp_hygiene.py --tmp-root /private/tmp\n```",
])
def test_scratch_and_read_only_probes_remain_allowed(text):
    assert not unsafe_temp_instructions(text)


@pytest.mark.parametrize("relative", [
    ".claude/skills/ignored-campaign/SKILL.md", "docs/ignored-campaign.md",
])
def test_ignored_instruction_file_is_still_checked(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text("Keep the campaign in /tmp/campaign.")
    (tmp_path / ".gitignore").write_text(relative + "\n")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True,
                   capture_output=True)
    ignored = subprocess.run(["git", "check-ignore", relative], cwd=tmp_path,
                             capture_output=True, text=True, check=False)
    assert ignored.returncode == 0, ignored.stderr
    assert path in instruction_paths(tmp_path)
    assert unsafe_temp_instructions(path.read_text())


def test_all_rendered_canonical_skills_retain_the_managed_state_policy():
    seen = 0
    for name, skill in load_canonical().items():
        for mech in applicable_mechs(skill):
            rendered = render_adapter(canonical_text(name), mech)
            regions = canonical_regions(rendered)
            policies = [body for body in (regions.values() if regions else [rendered])
                        if "**Durable session state.**" in body]
            assert len(policies) == 1
            policy = policies[0]
            assert "<repo>/.temp/" in policy
            assert "~/agent-work/<repo>/" in policy
            assert "same" in policy and "day" in policy and "whether or not a PR" in policy
            assert "cannot close" in policy and "only" in policy and "locally" in policy
            assert "existing boundaries" in policy
            assert not unsafe_temp_instructions(rendered)
            seen += 1
    assert seen > len(list(CANONICAL_DIR.glob("*.md")))


def test_repo_work_root_is_actually_gitignored():
    result = subprocess.run(["git", "check-ignore", "--stdin"], cwd=ROOT,
                            input=".temp/campaign/state.json\n", text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_native_handoff_preserves_size_and_durability_policy():
    prompt = (ROOT / "src/kg_microbe_governance/artifacts/prompts/backlog-loop-goal.md").read_text()
    assert len(prompt.encode("ascii")) < 4000
    assert "<repo>/.temp/" in prompt and "~/agent-work/<repo>/" in prompt
    assert "same day" in prompt and "block goal closure" in prompt
    assert not unsafe_temp_instructions(prompt)
