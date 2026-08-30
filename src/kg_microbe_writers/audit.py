"""Which scripts in a Mech write YAML, and what they declare about doing it.

#132 Phase 7, and #260 for how the rule was arrived at.

CultureMech, MediaIngredientMech, CommunityMech and TraitMech each carry a
`scripts/audit_writers.py`, and the copies differ pairwise by 174 to 228 lines. (ProteinTraitsMech's file shares the name and nothing else: a
different tool built on registered editors and guard tests.)

Those copies disagree about what a YAML writer *is*, and measuring them showed
why: a script in this fleet writes a YAML in several ways, and no copy detects
all of them.

    1  yaml.dump / yaml.safe_dump                  all four detect
    2  .write_text(yaml.dump(...))                 all four detect
    3  the Mech's own save helper --               TraitMech only
       save_yaml(, write_validated_<thing>(
    4  in-place edit: read_text, change the        CommunityMech only
       text, write_text back to a path that
       came from a *.yaml glob

CultureMech and MediaIngredientMech detect neither 3 nor 4, and compensate with
"`.write_text` appears somewhere and so does a `.yaml` token" -- which catches
the writers of kind 4 for the wrong reason and drags in scripts that read YAML
and write JSON. Measured on CultureMech: of the 26 its audit finds that kinds
1-3 do not, 14 are real in-place writers and 12 are not writers at all. Its
`_edison_capture.py` row is the clearest of those -- the file's only
`yaml.safe_dump` is inside a docstring saying the *caller* writes the YAML.

So this is not a merge of four opinions. Implementing all four techniques once
is strictly more accurate than any existing copy: it gains the helper writers
CultureMech and MediaIngredientMech miss, and drops the read-yaml-write-json
rows they invent, while losing nothing CommunityMech or TraitMech had.

What genuinely varies per Mech is small, and is declared rather than inferred:
where the scripts live, what the Mech's save helper is called, what its
validator is called, and whether it classifies a writer's output at all -- two
do, two do not.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

__all__ = [
    "COLUMNS",
    "Evidence",
    "WriterProfile",
    "WriterRow",
    "as_tsv",
    "audit",
    "writes_yaml",
]

# 1 and 2. `.write_text(yaml.dump(...))` is already covered by the first
# alternative; it is named in the docstring because it is how three of the four
# copies phrase the rule.
_DUMPS_YAML = re.compile(r"yaml\.(?:safe_)?dump\s*\(")

# 4 and 5. Either a path taken from a YAML glob and read-modified-written, or a
# write to a path built from a `.yaml` filename. The second catches a writer
# that serialises YAML by hand rather than through the yaml module --
# CultureMech's import_jcm_grmd.py builds `yaml_text` with its own dump_record()
# and writes it to `..._{name}.yaml`, which techniques 1 to 4 all miss.
_YAML_GLOB = re.compile(r"(?:r?glob)\s*\(\s*['\"][^'\"]*\.ya?ml['\"]")
_ASSIGNMENT = re.compile(r"^\s*(\w+)\s*=\s*([^\n]*)$", re.MULTILINE)
# A name assigned from an expression that introduces a different file
# extension is that file, whatever it was derived from. Without this the taint
# spreads from a YAML *input* -- `files = COMMUNITIES.glob("*.yaml")` -- through
# unrelated assignments to a writer of `INDEX.md`, which is how CommunityMech's
# growth_conditions_sweep.py was briefly reported as a YAML writer.
_OTHER_EXTENSION = re.compile(r"\.(?:md|json|tsv|csv|txt|html?|mmd|xml|ya?ml\w)\b")
_READ_TEXT_VAR = re.compile(r"(\w+)\s*\.\s*read_text\s*\(")
_WRITE_TEXT_VAR = re.compile(r"(\w+)\s*\.\s*write_text\s*\(\s*([^\n]*)")
# A write whose argument is JSON is not a YAML write however the path was found.
_JSON_ARGUMENT = re.compile(r"json\.dumps?\s*\(")

# Identical in all four copies, under three different constant names. Both the
# opt-out (`--dry-run`) and opt-in (`--apply`, `--write`) conventions count; the
# second is strictly safer, since the default is then not to write.
_WRITE_SAFEGUARD = re.compile(
    r"--dry[-_]run|dry_run\s*[:=]|--apply\b|args\.apply\b|--write\b|args\.write\b"
)
_CURATION_BASE = (
    r"curation_history.*?(?:append|\+=|\.insert)",
    r"['\"]curator['\"]\s*:",
    r"append_curation_event",
)
_VALIDATE_BASE = (r"linkml[._-]?validate", r"validator\.validate\s*\(")

COLUMNS = (
    "path",
    "writes_yaml",
    "target_kind",
    "appends_curation_history",
    "has_write_safeguard",
    "validates_before_write",
    "wired_into_just",
)


@dataclass(frozen=True)
class WriterProfile:
    """The per-Mech half. Everything else is shared."""

    search_dirs: tuple[str, ...]
    # Paths the audit does not judge. The audit tool itself is the standing
    # case: its regexes contain the literal `yaml.safe_dump`, so any rule that
    # reads source as text will call it a writer. All four copies exclude it.
    exclude: tuple[str, ...] = ()
    save_helpers: tuple[str, ...] = ()
    validators: tuple[str, ...] = ()
    curation_markers: tuple[str, ...] = ()
    target_kinds: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def helper_pattern(self) -> re.Pattern[str] | None:
        if not self.save_helpers:
            return None
        return re.compile("|".join(rf"\b{re.escape(h)}\s*\(" for h in self.save_helpers))

    def curation_pattern(self) -> re.Pattern[str]:
        return re.compile("|".join((*_CURATION_BASE, *self.curation_markers)))

    def validate_pattern(self) -> re.Pattern[str]:
        return re.compile("|".join((*_VALIDATE_BASE, *self.validators)))


@dataclass(frozen=True)
class Evidence:
    """Why a script was judged a YAML writer -- or was not.

    Kept because the four copies disagreed and nobody could see why. A row that
    says *how* it was detected can be argued with; a bare yes cannot.
    """

    dumps: bool = False
    helper: bool = False
    in_place: bool = False

    def __bool__(self) -> bool:
        return self.dumps or self.helper or self.in_place

    def reasons(self) -> tuple[str, ...]:
        named = (("yaml-dump", self.dumps), ("save-helper", self.helper),
                 ("in-place-edit", self.in_place))
        return tuple(name for name, on in named if on)


def _blocks(source: str) -> list[str]:
    """The source split at top-level `def`s.

    A variable name is only evidence within the function that uses it.
    CommunityMech's growth_conditions_sweep.py reads a community YAML through
    `path` in one function and writes INDEX.md through a different `path` in
    another, ninety lines apart -- which a whole-file name match reads as an
    in-place YAML edit. Splitting first is what makes the name mean something.
    """
    parts, current = [], []
    for line in source.splitlines(keepends=True):
        if line.startswith("def ") and current:
            parts.append("".join(current))
            current = []
        current.append(line)
    parts.append("".join(current))
    return parts


def _yaml_path_names(source: str) -> set[str]:
    """Variables that hold a path to a `.yaml` file.

    A `.yaml` filename is usually assembled a step away from where it is
    written -- `fname = f"...{name}.yaml"` then `out_path = out_dir / fname` --
    so this follows assignments until the set stops growing. Assignments only:
    a docstring mention, or a glob of *input* YAMLs, cannot make an unrelated
    write look like a YAML write.
    """
    assignments = _ASSIGNMENT.findall(source)
    names = {
        target
        for target, value in assignments
        if re.search(r"\.ya?ml\b", value) and not _OTHER_EXTENSION.search(value)
    }
    for _ in range(4):  # a fixpoint in practice; bounded so it always ends
        grown = set(names)
        for target, value in assignments:
            if _OTHER_EXTENSION.search(value):
                continue
            if any(re.search(rf"\b{re.escape(n)}\b", value) for n in names):
                grown.add(target)
        if grown == names:
            break
        names = grown
    return names


def writes_yaml(source: str, profile: WriterProfile) -> Evidence:
    """All four detection techniques, in one place."""
    helper = profile.helper_pattern()
    in_place = False
    globs_yaml = bool(_YAML_GLOB.search(source))
    for block in _blocks(source):
        writes = _WRITE_TEXT_VAR.findall(block)
        if not writes:
            continue
        read = set(_READ_TEXT_VAR.findall(block)) if globs_yaml else set()
        yaml_paths = _yaml_path_names(block) | _yaml_path_names(source.split("def ")[0])
        for name, argument in writes:
            if _JSON_ARGUMENT.search(argument):
                continue
            if name in read or name in yaml_paths:
                in_place = True
                break
        if in_place:
            break
    return Evidence(
        dumps=bool(_DUMPS_YAML.search(source)),
        helper=bool(helper.search(source)) if helper else False,
        in_place=in_place,
    )


@dataclass(frozen=True)
class WriterRow:
    path: str
    evidence: Evidence
    target_kind: str
    appends_curation_history: bool
    has_write_safeguard: bool
    validates_before_write: bool
    wired_into_just: bool

    def as_row(self, *, target_kind: bool = True) -> tuple[str, ...]:
        def yn(value: bool) -> str:
            return "yes" if value else "no"

        values = [
            self.path,
            yn(bool(self.evidence)),
            self.target_kind,
            yn(self.appends_curation_history),
            yn(self.has_write_safeguard),
            yn(self.validates_before_write),
            yn(self.wired_into_just),
        ]
        if not target_kind:
            del values[2]
        return tuple(values)


def _tracked_python(root: Path, search_dirs: Sequence[str]) -> list[Path]:
    """Python files git tracks under the profile's directories.

    From git rather than a filesystem walk: a working tree carries caches, build
    output and untracked scratch, and whether a script is *in the repository* is
    the question (#203).
    """
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", *[f"{d}/*.py" for d in search_dirs]],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [Path(line) for line in result.stdout.splitlines() if line]


def _classify(source: str, target_kinds: Mapping[str, tuple[str, ...]]) -> str:
    """Two Mechs classify a writer's output; two do not.

    A Mech that declares no kinds emits an empty string rather than a column of
    "unknown", so its TSV keeps the shape its consumers already read.
    """
    if not target_kinds:
        return ""
    matched = [
        kind
        for kind, patterns in target_kinds.items()
        if any(re.search(pattern, source) for pattern in patterns)
    ]
    if not matched:
        return "unknown"
    return matched[0] if len(matched) == 1 else "mixed"


def audit(root: Path, profile: WriterProfile) -> list[WriterRow]:
    root = Path(root)
    curation = profile.curation_pattern()
    validates = profile.validate_pattern()
    justfile = root / "justfile"
    recipes = (
        justfile.read_text(encoding="utf-8", errors="replace")
        if justfile.is_file()
        else ""
    )

    rows: list[WriterRow] = []
    excluded = set(profile.exclude)
    for relative in sorted(_tracked_python(root, profile.search_dirs)):
        if relative.as_posix() in excluded:
            continue
        try:
            source = (root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        evidence = writes_yaml(source, profile)
        if not evidence:
            continue
        rows.append(
            WriterRow(
                path=relative.as_posix(),
                evidence=evidence,
                target_kind=_classify(source, profile.target_kinds),
                appends_curation_history=bool(curation.search(source)),
                has_write_safeguard=bool(_WRITE_SAFEGUARD.search(source)),
                validates_before_write=bool(validates.search(source)),
                wired_into_just=relative.name in recipes
                or relative.as_posix() in recipes,
            )
        )
    return rows


def as_tsv(rows: Iterable[WriterRow], *, target_kind: bool = True) -> str:
    columns = COLUMNS if target_kind else tuple(c for c in COLUMNS if c != "target_kind")
    lines = ["\t".join(columns)]
    lines.extend("\t".join(row.as_row(target_kind=target_kind)) for row in rows)
    return "\n".join(lines) + "\n"
