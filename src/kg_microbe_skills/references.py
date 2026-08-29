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

What it does NOT cover: only backticked text is read, so a path written inside
a fenced code block is invisible to it. That is deliberate rather than an
oversight -- 85 path-shaped tokens live in those blocks and most are not paths
at all (`25842/-2246`, `CHEBI/NCIT`, `HIGH/MEDIUM/LOW`, `$AUDIT_DIR/fleet.tsv`),
so applying these rules there would produce far more noise than findings. The
consequence is real and worth stating: a command example citing a file that has
moved will not be caught. Extending coverage needs shell-aware parsing (#202).

The checker refuses to guess when it cannot see. With no downstream checkout
resolvable, a path absent from claw is UNVERIFIABLE, never MISSING -- the
distinction #161 established for the unmapped inventory, for the same reason:
a partial answer reported as a complete one is worse than a partial answer that
says so.
"""

from __future__ import annotations

import re
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
    """Every backticked reference in one file, in source order."""
    body = text if text is not None else Path(path).read_text(encoding="utf-8")
    references: list[Reference] = []
    for number, line in enumerate(body.splitlines(), start=1):
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
) -> list[Finding]:
    """Judge every reference in every skill.

    `downstream` maps a repository label to a resolved checkout. `repositories`
    names every repository the fleet knows of, resolvable or not, so that a
    path prefixed with an unresolvable one is reported as unverifiable rather
    than missing. Whatever is absent limits what can be concluded, and the
    verdicts say so rather than guessing.
    """
    claw_root = Path(claw_root)
    downstream = dict(downstream or {})
    labels = set(repositories or ()) | set(downstream) | {_CLAW_LABEL}
    commands = _known_commands(claw_root)
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
                _resolve_path(reference, claw_root, downstream, labels, declared)
            )
    return findings


def _resolve_path(
    reference: Reference,
    claw_root: Path,
    downstream: Mapping[str, Path],
    labels: set[str],
    declared: str | None = None,
) -> Finding:
    """Decide what one path reference actually points at."""
    head, _, rest = reference.text.partition("/")

    if head == _OUTPUT_ROOT:
        return Finding(reference, "output", "runtime artifact under workspace/")

    # An explicit repository prefix answers the question the rest of this
    # function otherwise has to guess at: the path is relative to *that*
    # checkout, and there is nothing ambiguous left to report.
    if head in labels:
        if head == _CLAW_LABEL:
            root: Path | None = claw_root
        else:
            root = downstream.get(head)
        if root is None:
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
        if (Path(root) / rest).exists():
            return Finding(reference, "ok")
        if rest.split("/")[0] == _OUTPUT_ROOT:
            return Finding(reference, "output", f"runtime artifact under {head}")
        return Finding(reference, "missing", f"no such path in {head}")

    if (claw_root / reference.text).exists():
        return Finding(reference, "ok")

    # A declaration says where the skill's *other* paths live; it does not stop
    # the skill citing claw's own files, which every one of these does. Claw is
    # tried first above, so the declaration only decides what claw does not
    # already answer -- and that leaves nothing ambiguous to report.
    if declared:
        return _resolve_declared(reference, downstream, labels, declared)

    # A path written without a repository prefix may still name a real file
    # downstream -- most do. Say which, so the fix is to add the prefix rather
    # than to hunt for a file that was never missing.
    elsewhere = [
        label
        for label, root in sorted(downstream.items())
        if (Path(root) / reference.text).exists()
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
    downstream: Mapping[str, Path],
    labels: set[str],
    declared: str,
) -> Finding:
    """Judge a bare path, absent from claw, against its skill's declared root."""
    if declared == ANY_MECH:
        # Per-Mech by intention: `{mech}/scripts/...` is one file in every
        # checkout, and naming one Mech would be wrong. Existing anywhere in
        # the fleet is the whole claim being made.
        mechs = {
            label: root for label, root in downstream.items() if label != "kg-microbe"
        }
        if not mechs:
            return Finding(
                reference,
                "unverifiable",
                "declared per-Mech, and no Mech checkout was resolvable",
            )
        if any((Path(root) / reference.text).exists() for root in mechs.values()):
            return Finding(reference, "ok")
        return Finding(
            reference,
            "missing",
            f"declared per-Mech but present in none of {', '.join(sorted(mechs))}",
        )

    if declared not in labels:
        return Finding(
            reference,
            "unverifiable",
            f"declared reference-root {declared!r} is not a repository the "
            f"manifest knows",
        )
    root = downstream.get(declared)
    if root is None:
        return Finding(
            reference,
            "unverifiable",
            f"declared reference-root {declared} is not a resolvable checkout here",
        )
    if (Path(root) / reference.text).exists():
        return Finding(reference, "ok")
    return Finding(reference, "missing", f"no such path in {declared}")
