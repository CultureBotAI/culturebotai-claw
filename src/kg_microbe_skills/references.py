"""Check that a skill's references point at something that exists.

Phase 4 item 4 of the standardization plan: "a skill-reference checker that
validates every local path, command, and sibling-skill reference".

Skills are prose, so nothing catches a path that was renamed, a script that
moved to another repository, or a sibling skill that was deleted. The reader
finds out by following the reference and landing nowhere.

The hard part is not finding path-shaped text; it is knowing which repository a
reference belongs to. A skill that operates on kg-microbe writes
`scripts/consolidate_chemical_mappings.py`, and that file is real -- in
kg-microbe. Calling it broken would be wrong, and calling it fine would let a
genuinely dead path through. So an unprefixed path that resolves only
downstream is reported as AMBIGUOUS: it exists, and the skill should say where.

Fenced code blocks are read too, but only shell ones, and only through a shell
tokenizer (#202). Reading every fence with the prose rules would have produced
far more noise than findings: 85 path-shaped tokens live in those blocks and
most are not paths at all -- `25842/-2246` is a diff stat, `CHEBI/NCIT` an
ontology list, `HIGH/MEDIUM/LOW` an enum, `$AUDIT_DIR/fleet.tsv` a shell
variable. Restricting to shell fences drops the python, json and text blocks
where the ratios and enums live; `shlex` then separates words from flags and
quoted strings, and the same rules that reject a git ref or a placeholder in
prose apply again.

Existence is decided by git, not by the filesystem. A developer's downstream
checkout carries generated data and local snapshots a fresh clone does not, so
`Path.exists()` gave different verdicts on a laptop and in CI -- four of them,
the day this landed (#203). `git ls-files` and `git check-ignore` answer the
same on both, including for paths absent locally: tracked is OK, ignored is a
generated artifact, and neither means no clone of that repository has it.

The checker refuses to guess when it cannot see. With no downstream checkout
resolvable, a path absent from claw is UNVERIFIABLE, never MISSING -- the
distinction #161 established for the unmapped inventory, for the same reason:
a partial answer reported as a complete one is worse than a partial answer that
says so.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

__all__ = [
    "ANY_MECH",
    "Finding",
    "Reference",
    "reference_root",
    "check",
    "extract_references",
    "format_report",
    "skill_files",
]

# Backticked path- or command-shaped text. Skills use backticks for every
# literal by convention, and prose outside them is not a reference.
_BACKTICK = re.compile(r"`([^`\n]+)`")

# `/name` inside backticks is how a skill cites a sibling skill, a project
# command, or a workflow. Outside backticks the same shape is a URL segment or
# an absolute path (`/tmp`, `/api/search`), which is why this only reads
# backticked text.
_SLASH_REFERENCE = re.compile(r"^/([a-z][a-z0-9-]*)$")

_PATH_SHAPED = re.compile(r"^[\w.@-]+(?:/[\w.@-]+)+/?$")

# Stand-ins for a real name. A skill writes `UNMAPPED_NNNN.yaml` or
# `owner/repository` to describe a shape, not to point at a file.
_PLACEHOLDER = re.compile(
    r"NNNN|XXXX|<[^>]+>|\{[^}]+\}|owner/repository|_N\b|/N\b"
)

# `origin/main` is a git ref and `www.ebi.ac.uk/chebi` is a bare URL. Both are
# path-shaped and neither is a file, so they are rejected before resolution
# rather than reported as missing.
_GIT_REF = re.compile(r"^(origin|upstream|refs)/")
_HOSTNAME = re.compile(r"^(www\.|[\w-]+(\.[\w-]+)*\.(com|org|net|edu|gov|io|ac\.uk))/")

# Runtime output. CLAUDE.md puts every generated artifact under
# OPENCLAW_WORKSPACE, which is gitignored, so a skill naming its own output is
# describing what it will write, not citing something that must already exist.
# Counted and not judged -- asserting these exist would fail on a clean
# checkout for every skill that works.
_OUTPUT_ROOT = "workspace"

# This repository, by the name a sibling checkout would use for it.
_CLAW_LABEL = "culturebotai-claw"

# A first segment shaped like a repository name -- `CultureBotHT`, `kg-microbe`
# -- that no resolvable checkout answers to. Reporting such a path as missing
# would assert something this tool cannot know, so it is reported as
# unverifiable and names the checkout it would need.
_REPOSITORY_SHAPED = re.compile(r"^(?:[A-Z][A-Za-z0-9]*|[a-z][a-z0-9]*(?:-[a-z0-9]+)+)$")

# A skill whose paths are all relative to one repository says so once, in
# frontmatter, instead of repeating the prefix on every line -- which is what
# these files already do in prose ("Source path (in `kg-microbe/`)"), invisibly
# to any checker. `reference-root: mech` means the paths are per-Mech and are
# satisfied by any Mech checkout carrying them, the case a single prefix cannot
# express without naming a Mech the skill does not mean.
_FRONTMATTER_KEY = "reference-root"
ANY_MECH = "mech"

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def reference_root(path: Path, text: str | None = None) -> str | None:
    """The repository this skill's bare paths are relative to, if declared."""
    body = text if text is not None else Path(path).read_text(encoding="utf-8")
    match = _FRONTMATTER.match(body)
    if not match:
        return None
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == _FRONTMATTER_KEY:
            return value.strip().strip("\"'") or None
    return None


@dataclass(frozen=True)
class Reference:
    """One citation in one skill."""

    kind: str  # "path" or "command"
    text: str
    source: Path
    line: int
    # The repository a preceding `cd` put the shell in, when the block moved
    # somewhere before running anything. Without this, `cd ../kg-microbe &&
    # python scripts/x.py` reads as a claw path and is reported ambiguous --
    # a reference that was right all along.
    repository: str | None = None

    @property
    def skill(self) -> str:
        return self.source.parent.name if self.source.name.upper() == "SKILL.MD" else self.source.name


@dataclass(frozen=True)
class Finding:
    reference: Reference
    verdict: str  # "ok" | "ambiguous" | "missing" | "unverifiable"
    detail: str = ""


def skill_files(claw_root: Path) -> list[Path]:
    """Every skill and project command, each listed once.

    Real directory entries rather than a case-glob: `*/SKILL.md` under-reports
    a lowercase `skill.md` on Linux, and globbing both patterns double-reports
    on a case-insensitive macOS filesystem. The vendored frontmatter contract
    settled this the same way.
    """
    found: list[Path] = []
    skills = Path(claw_root) / ".claude" / "skills"
    if skills.is_dir():
        for directory in sorted(p for p in skills.iterdir() if p.is_dir()):
            found.extend(
                sorted(p for p in directory.iterdir() if p.name.upper() == "SKILL.MD")
            )
    commands = Path(claw_root) / ".claude" / "commands"
    if commands.is_dir():
        found.extend(sorted(p for p in commands.iterdir() if p.suffix == ".md"))
    return found


def extract_references(path: Path, text: str | None = None) -> list[Reference]:
    """Every reference in one file, in source order.

    Prose is read through backticks; shell fences through `shlex`.
    """
    body = text if text is not None else Path(path).read_text(encoding="utf-8")
    references: list[Reference] = []
    fence: str | None = None
    cwd: str | None = None
    for number, line in enumerate(body.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            fence = None if fence is not None else stripped[3:].strip().lower()
            cwd = None  # each block starts where the reader started
            continue
        if fence is not None:
            if fence in _SHELL_FENCES:
                found, cwd = _shell_references(path, line, number, cwd)
                references.extend(found)
            continue
        for match in _BACKTICK.finditer(line):
            token = match.group(1).strip()
            if _SLASH_REFERENCE.match(token):
                references.append(Reference("command", token, path, number))
                continue
            if _PLACEHOLDER.search(token):
                continue
            # A URL, a flag, or an absolute path is not a repository-relative
            # reference; neither is anything with a space in it.
            if token.startswith(("http", "/", "-", "~", "..")) or " " in token:
                continue
            if _GIT_REF.match(token) or _HOSTNAME.match(token):
                continue
            if _PATH_SHAPED.match(token):
                references.append(Reference("path", token.rstrip("/"), path, number))
    return references


class _Repository:
    """One checkout, answering "does this path belong here?" from git.

    Answers are cached per root: `git ls-files` runs once, and the ignore
    check runs at most once per distinct path.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._tracked: set[str] | None = None
        self._prefixes: set[str] | None = None
        self._ignored: dict[str, bool] = {}

    @property
    def is_git(self) -> bool:
        return (self.root / ".git").exists()

    def _load(self) -> None:
        if self._tracked is not None:
            return
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        tracked = {
            entry for entry in result.stdout.split("\0") if entry
        } if result.returncode == 0 else set()
        prefixes: set[str] = set()
        for entry in tracked:
            parts = entry.split("/")
            for index in range(1, len(parts)):
                prefixes.add("/".join(parts[:index]))
        self._tracked, self._prefixes = tracked, prefixes

    def tracked(self, relative: str) -> bool:
        """Whether git tracks this file, or any file beneath this directory."""
        self._load()
        assert self._tracked is not None and self._prefixes is not None
        return relative in self._tracked or relative in self._prefixes

    def ignored(self, relative: str) -> bool:
        """Whether the repository declares this path generated.

        `git check-ignore` answers for paths that do not exist, which is the
        whole point: a clone without the artifact must reach the same verdict
        as a working tree that has it.
        """
        if relative not in self._ignored:
            result = subprocess.run(
                ["git", "check-ignore", "-q", "--no-index", "--", relative],
                cwd=self.root,
                capture_output=True,
                check=False,
            )
            self._ignored[relative] = result.returncode == 0
        return self._ignored[relative]

    def verdict(self, relative: str) -> str:
        """"ok", "generated", or "missing" for one path in this repository."""
        if not self.is_git:
            # Not a checkout -- a temporary directory in a test, or a path
            # handed in directly. Fall back to the filesystem and say so.
            return "ok" if (self.root / relative).exists() else "missing"
        if self.tracked(relative):
            return "ok"
        if self.ignored(relative):
            return "generated"
        return "missing"


# Only these fences are read. A python, json or text block carries ratios,
# enums and literal data that the path rules would misread wholesale.
_SHELL_FENCES = frozenset({"", "bash", "sh", "shell", "zsh", "console"})

# An ALL-CAPS first segment with no extension anywhere is an ontology prefix or
# an enum -- `CHEBI/NCIT`, `FEBA/Hans80` -- not a directory.
_LABEL_PAIR = re.compile(r"^[A-Z0-9]+/")

# `${KGMICROBE_ROOT:-../kg-microbe}` is the portable way to write a checkout
# that an environment variable may override. Reading the fallback is what lets
# a command be portable AND checkable; without it, writing the better command
# loses the reference.
_ENV_FALLBACK = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*:-([^}]+)\}$")


def _cd_target(words: list[str]) -> str | None:
    """The repository a `cd` moves to, if it names one.

    `cd ../kg-microbe`, `cd /abs/path/to/kg-microbe` and `cd kg-microbe` all
    say the same thing about the paths that follow. Anything else -- a
    subdirectory, a variable, `cd -` -- returns None, and the block goes back
    to being read against the repository it started in.
    """
    for index, word in enumerate(words[:-1]):
        if word == "cd":
            target = words[index + 1].rstrip("/")
            fallback = _ENV_FALLBACK.match(target)
            if fallback:
                target = fallback.group(1).rstrip("/")
            if not target or "$" in target:
                return None
            return target.rsplit("/", 1)[-1] or None
    return None


def _shell_references(
    path: Path, line: str, number: int, cwd: str | None
) -> tuple[list[Reference], str | None]:
    """Path-shaped words in one line of a shell block, and where it left the shell.

    `shlex` is what separates a path from a flag, a quoted sentence, or a
    comment. An unbalanced quote -- common in an illustrative fragment -- makes
    it raise, and the line is skipped rather than guessed at.
    """
    try:
        words = shlex.split(line, comments=True)
    except ValueError:
        return [], cwd

    moved = _cd_target(words)
    found: list[Reference] = []
    for word in words:
        if word.startswith(("http", "/", "-", "~", "..")) or "$" in word or "*" in word:
            continue
        if _PLACEHOLDER.search(word) or _GIT_REF.match(word) or _HOSTNAME.match(word):
            continue
        if _LABEL_PAIR.match(word) and "." not in word:
            continue
        if _PATH_SHAPED.match(word):
            found.append(
                Reference("path", word.rstrip("/"), path, number, moved or cwd)
            )
    return found, moved or cwd


def _known_commands(claw_root: Path) -> set[str]:
    root = Path(claw_root) / ".claude"
    names: set[str] = set()
    for sub, pattern in (("skills", "*"), ("commands", "*.md"), ("workflows", "*")):
        directory = root / sub
        if not directory.is_dir():
            continue
        for entry in directory.glob(pattern):
            names.add(entry.name if sub == "skills" else entry.stem)
    return names


def check(
    claw_root: Path,
    downstream: Mapping[str, Path] | None = None,
    files: Iterable[Path] | None = None,
    repositories: Iterable[str] | None = None,
    mech_labels: Iterable[str] | None = None,
) -> list[Finding]:
    """Judge every reference in every skill.

    `downstream` maps a repository label to a resolved checkout. `repositories`
    names every repository the fleet knows of, resolvable or not, so that a
    path prefixed with an unresolvable one is reported as unverifiable rather
    than missing. Whatever is absent limits what can be concluded, and the
    verdicts say so rather than guessing.

    `mech_labels` says which of those labels are Mechs, for a
    `reference-root: mech` skill. Deriving it by subtracting known non-Mechs
    was wrong the moment claw was passed as its own repository: claw counted as
    a Mech, and every per-Mech path was reported "present in none of
    culturebotai-claw" (#216).
    """
    claw_root = Path(claw_root)
    downstream = dict(downstream or {})
    labels = set(repositories or ()) | set(downstream) | {_CLAW_LABEL}
    mechs = (
        set(mech_labels)
        if mech_labels is not None
        else set(downstream) - {"kg-microbe", _CLAW_LABEL}
    )
    commands = _known_commands(claw_root)
    repos = {label: _Repository(root) for label, root in downstream.items()}
    repos[_CLAW_LABEL] = _Repository(claw_root)
    findings: list[Finding] = []

    for path in files if files is not None else skill_files(claw_root):
        body = path.read_text(encoding="utf-8")
        declared = reference_root(path, body)
        for reference in extract_references(path, body):
            if reference.kind == "command":
                name = reference.text.lstrip("/")
                findings.append(
                    Finding(reference, "ok")
                    if name in commands
                    else Finding(
                        reference,
                        "missing",
                        f"no skill, command, or workflow named {name!r} in .claude/",
                    )
                )
                continue

            findings.append(
                _resolve_path(reference, repos, downstream, labels, mechs, declared)
            )
    return findings


def _resolve_path(
    reference: Reference,
    repos: Mapping[str, "_Repository"],
    downstream: Mapping[str, Path],
    labels: set[str],
    mechs: set[str],
    declared: str | None = None,
) -> Finding:
    """Decide what one path reference actually points at."""
    # Whether or not that repository is resolvable here. If it is not,
    # `_resolve_declared` says so; falling through to claw instead would report
    # a path that is correct in its own repository as missing from this one.
    if reference.repository:
        return _resolve_declared(
            reference, repos, downstream, labels, mechs, reference.repository
        )

    head, _, rest = reference.text.partition("/")

    if head == _OUTPUT_ROOT:
        return Finding(reference, "output", "runtime artifact under workspace/")

    # An explicit repository prefix answers the question the rest of this
    # function otherwise has to guess at: the path is relative to *that*
    # checkout, and there is nothing ambiguous left to report.
    if head in labels:
        repo = repos.get(head)
        if repo is None:
            return Finding(
                reference,
                "unverifiable",
                f"{head} is not a resolvable checkout here",
            )
        if not rest:
            return Finding(reference, "ok")
        # A repeated prefix is not a typo. CommunityMech's checkout sits at
        # `CommunityMech/CommunityMech`, so a skill citing
        # `CommunityMech/CommunityMech/reports/...` has written the path from
        # the directory the checkouts share, and both segments are real. Drop
        # them until the remainder is relative to the checkout itself.
        while rest.split("/")[0] == head:
            rest = rest.partition("/")[2]
        verdict = repo.verdict(rest)
        if verdict == "ok":
            return Finding(reference, "ok")
        if verdict == "generated":
            return Finding(reference, "output", f"{head} declares this generated")
        if rest.split("/")[0] == _OUTPUT_ROOT:
            return Finding(reference, "output", f"runtime artifact under {head}")
        return Finding(
            reference,
            "missing",
            f"not in {head}: git neither tracks it nor declares it generated",
        )

    if repos[_CLAW_LABEL].verdict(reference.text) == "ok":
        return Finding(reference, "ok")

    # A declaration says where the skill's *other* paths live; it does not stop
    # the skill citing claw's own files, which every one of these does. Claw is
    # tried first above, so the declaration only decides what claw does not
    # already answer -- and that leaves nothing ambiguous to report.
    if declared:
        return _resolve_declared(reference, repos, downstream, labels, mechs, declared)

    # A path written without a repository prefix may still name a real file
    # downstream -- most do. Say which, so the fix is to add the prefix rather
    # than to hunt for a file that was never missing.
    elsewhere = [
        label
        for label in sorted(downstream)
        if repos[label].verdict(reference.text) == "ok"
    ]
    if elsewhere:
        return Finding(
            reference,
            "ambiguous",
            f"not in claw; exists in {', '.join(elsewhere)} -- "
            f"write the repository prefix",
        )
    if _REPOSITORY_SHAPED.match(head) and head not in labels:
        return Finding(
            reference,
            "unverifiable",
            f"{head} looks like a repository this tool has no checkout for",
        )
    if downstream:
        return Finding(
            reference,
            "missing",
            f"not in claw and not in any of {', '.join(sorted(downstream))}",
        )
    return Finding(
        reference,
        "unverifiable",
        "not in claw, and no downstream checkout was resolvable to rule it "
        "in or out",
    )


def format_report(findings: list[Finding]) -> str:
    """A report a reader can act on, ordered worst first."""
    order = {"missing": 0, "ambiguous": 1, "unverifiable": 2, "output": 3, "ok": 4}
    counts = {verdict: 0 for verdict in order}
    for finding in findings:
        counts[finding.verdict] += 1

    lines = [
        f"{len(findings)} reference(s): "
        + ", ".join(f"{counts[v]} {v}" for v in sorted(counts, key=lambda v: order[v]))
    ]
    # `output` and `ok` are counted, not listed: a skill naming the file it
    # writes is not a defect, and sixty of them would bury the three that are.
    for finding in sorted(
        (f for f in findings if f.verdict not in ("ok", "output")),
        key=lambda f: (order[f.verdict], f.reference.skill, f.reference.line),
    ):
        reference = finding.reference
        lines.append(
            f"  {finding.verdict.upper():13} {reference.skill}:{reference.line}  "
            f"{reference.text}"
        )
        if finding.detail:
            lines.append(f"                {finding.detail}")
    return "\n".join(lines)


def _resolve_declared(
    reference: Reference,
    repos: Mapping[str, "_Repository"],
    downstream: Mapping[str, Path],
    labels: set[str],
    mechs: set[str],
    declared: str,
) -> Finding:
    """Judge a bare path, absent from claw, against its skill's declared root."""
    if declared == ANY_MECH:
        # Per-Mech by intention: `{mech}/scripts/...` is one file in every
        # checkout, and naming one Mech would be wrong. Existing anywhere in
        # the fleet is the whole claim being made.
        available = {label: repos[label] for label in mechs if label in repos}
        if not available:
            return Finding(
                reference,
                "unverifiable",
                "declared per-Mech, and no Mech checkout was resolvable",
            )
        if any(repo.verdict(reference.text) == "ok" for repo in available.values()):
            return Finding(reference, "ok")
        if any(
            repo.verdict(reference.text) == "generated" for repo in available.values()
        ):
            return Finding(reference, "output", "declared generated by a Mech")
        return Finding(
            reference,
            "missing",
            f"declared per-Mech but present in none of "
            f"{', '.join(sorted(available))}",
        )

    if declared not in labels:
        return Finding(
            reference,
            "unverifiable",
            f"declared reference-root {declared!r} is not a repository the "
            f"manifest knows",
        )
    repo = repos.get(declared)
    if repo is None:
        return Finding(
            reference,
            "unverifiable",
            f"declared reference-root {declared} is not a resolvable checkout here",
        )
    verdict = repo.verdict(reference.text)
    if verdict == "ok":
        return Finding(reference, "ok")
    if verdict == "generated":
        return Finding(reference, "output", f"{declared} declares this generated")
    return Finding(
        reference,
        "missing",
        f"not in {declared}: git neither tracks it nor declares it generated",
    )
