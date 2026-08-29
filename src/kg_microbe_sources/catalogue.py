"""One validator for every Mech's `download.yaml` source catalogue.

Phase 6 item 3 (#132, #223): a common source manifest, generalized from the
strongest existing implementation.

Two Mechs have a catalogue and each wrote its own validator. ProteinTraitsMech's
checks `url` and nothing else, and was never wired into CI. TraitMech adopted it
and made both fixes -- every required field enforced, and run from `just qc` --
recording in its own docstring that licence provenance is the whole reason the
catalogue exists.

Adopting the stronger one unchanged would have been a mistake, and only running
it against the other Mech's data showed why: 47 errors, of which 46 are false.
The two repositories write different shapes. TraitMech writes one block per
source; ProteinTraitsMech writes one block per FILE, so `interpro` is six
blocks distinguished by `local_name`. Judged one block at a time, five of those
are "missing name", eleven are "missing license", and eleven are "duplicate
source id" -- while every group in fact carries a name, a licence and a seeder.

So the model here is a SOURCE GROUP: one or more file blocks sharing a source
id. Uniqueness is over (source, file); `name`, `license` and `seeder` are
obligations of the group, satisfied by any block in it. Both real catalogues
validate under this, and the one genuine defect in either -- two `prosite`
blocks that nothing distinguishes -- surfaces instead of drowning.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

__all__ = [
    "DEFAULT_SEEDER_GLOB",
    "DEFAULT_STATUSES",
    "GROUP_REQUIRED",
    "BLOCK_REQUIRED",
    "CatalogueError",
    "Finding",
    "Report",
    "SourceGroup",
    "load_blocks",
    "validate",
]


class CatalogueError(RuntimeError):
    """The catalogue could not be read at all."""


# Every block must say where it comes from and what state it is in; the rest is
# something the source as a whole is responsible for.
BLOCK_REQUIRED = ("url", "status")
GROUP_REQUIRED = ("name", "source", "license")

# `candidate` and `rejected` carry weight: a source characterised in full and
# deliberately not seeded has a reason, and it belongs in the catalogue rather
# than in a commit message nobody will find.
DEFAULT_STATUSES = frozenset(
    {"seeded", "candidate", "deferred", "rejected", "superseded", "enrichment"}
)

_RESTRICTIVE = (
    "noncommercial", "non-commercial", "-nc", "byncnd", "by-nc",
    "noderiv", "-nd", "login", "registration", "flagged",
)
_UNRESOLVED = ("unknown", "unclear", "tbd", "see upstream_licenses")

# The rule TraitMech wrote was `seed_*.py`, and its purpose was to stop
# `seeder: ../download.yaml` resolving to a real file and passing. That is a
# traversal problem, not a naming one -- and imposing the naming convention on
# ProteinTraitsMech makes its real `build_chebi_sidecar.py` an error. Constrain
# the shape to a bare Python filename and let each repository name its own
# scripts; the orphan-seeder sweep takes the convention as a parameter instead.
_SEEDER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.py")
DEFAULT_SEEDER_GLOB = "seed_*.py"


@dataclass(frozen=True)
class Finding:
    severity: str  # "error" or "warning"
    subject: str
    message: str

    def __str__(self) -> str:
        return f"[{self.subject}] {self.message}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, subject: str, message: str) -> None:
        self.findings.append(Finding("error", subject, message))

    def warn(self, subject: str, message: str) -> None:
        self.findings.append(Finding("warning", subject, message))


@dataclass(frozen=True)
class SourceGroup:
    """One source, as one or more file blocks."""

    source: str
    blocks: tuple[dict, ...]

    def first(self, key: str):
        """The value any block in the group declares, if one does.

        A group-level obligation is met by whichever block carries it: PTM
        declares a licence once for six InterPro files rather than six times.
        """
        for block in self.blocks:
            value = block.get(key)
            if value:
                return value
        return None

    @property
    def statuses(self) -> set[str]:
        return {
            status
            for b in self.blocks
            if isinstance(status := b.get("status"), str)
        }

    def file_of(self, block: dict) -> str | None:
        """What distinguishes this block from its siblings."""
        return block.get("local_name") or block.get("tag")


def load_blocks(path: Path) -> list[dict]:
    """Parse a catalogue, refusing anything that is not a non-empty list.

    An empty catalogue used to pass green in both Mechs, so deleting every
    source satisfied the gate. A catalogue with no sources is a broken file.
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogueError(f"cannot read source catalogue {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        # A syntax error must read as a diagnostic, not a parser traceback: the
        # operator needs to know which file failed and roughly where.
        raise CatalogueError(f"{path} is not valid YAML: {exc}") from exc

    if raw is None or not isinstance(raw, list):
        raise CatalogueError(f"{path} must be a YAML list of source blocks")
    if not raw:
        raise CatalogueError(f"{path} lists no sources")
    return raw


def _group(blocks: list[dict], report: Report) -> list[SourceGroup]:
    by_source: dict[str, list[dict]] = defaultdict(list)
    for index, block in enumerate(blocks):
        # A bare `-` with a mis-indented body parses to None, and the file's own
        # style makes that a one-keystroke mistake. Report it rather than
        # raising AttributeError on the next line.
        if not isinstance(block, dict):
            report.error(
                f"block[{index}]",
                f"is {type(block).__name__}, not a mapping -- check the "
                f"indentation under its `-`",
            )
            continue
        source = block.get("source")
        if not source or not isinstance(source, str):
            report.error(
                block.get("name") or f"block[{index}]",
                "missing required field: source",
            )
            continue
        by_source[source].append(block)
    return [SourceGroup(s, tuple(b)) for s, b in sorted(by_source.items())]


def validate(
    blocks: list[dict],
    *,
    seeder_dir: Path | None = None,
    statuses: frozenset[str] = DEFAULT_STATUSES,
    seeder_glob: str = DEFAULT_SEEDER_GLOB,
) -> Report:
    """Judge a parsed catalogue. Errors fail; warnings inform."""
    report = Report()
    groups = _group(blocks, report)
    referenced: set[str] = set()

    for group in groups:
        subject = group.first("name") or group.source

        for key in GROUP_REQUIRED:
            if not group.first(key):
                report.error(subject, f"missing required field: {key}")

        seen: dict[str | None, int] = {}
        for index, block in enumerate(group.blocks):
            for key in BLOCK_REQUIRED:
                if not block.get(key):
                    report.error(subject, f"block {index}: missing {key}")
            status = block.get("status")
            if status is not None and not isinstance(status, str):
                report.error(
                    subject,
                    f"block {index}: status must be a string, got "
                    f"{type(status).__name__}",
                )
            elif isinstance(status, str) and status not in statuses:
                report.error(
                    subject,
                    f"block {index}: invalid status {status!r}; expected one of "
                    f"{', '.join(sorted(statuses))}",
                )

            # Which file a block describes is what makes a multi-file source
            # readable at all. Two blocks naming neither cannot be told apart.
            name = group.file_of(block)
            if len(group.blocks) > 1:
                if name is None:
                    report.error(
                        subject,
                        f"block {index}: a source with more than one block must "
                        f"name the file each describes (local_name or tag)",
                    )
                elif name in seen:
                    report.error(
                        subject,
                        f"block {index}: {name!r} already describes block "
                        f"{seen[name]}",
                    )
                else:
                    seen[name] = index

        seeder = group.first("seeder")
        if seeder:
            script = str(seeder).split()[0]
            referenced.add(script)
            # Constrain the shape: without this, `seeder: ../download.yaml`
            # resolves to a real file and passes, which also lets a source dodge
            # the orphan-seeder warning.
            if not _SEEDER.fullmatch(script):
                report.error(
                    subject,
                    f"seeder must be a bare Python filename, got {script!r}",
                )
            elif seeder_dir is not None and not (seeder_dir / script).exists():
                report.error(subject, f"seeder script not found: {script}")
        elif "seeded" in group.statuses:
            report.error(subject, "status is 'seeded' but no seeder is named")

        licence = str(group.first("license") or "").lower()
        if any(token in licence for token in _RESTRICTIVE):
            report.warn(subject, f"restrictive licence: {group.first('license')}")
        elif any(token in licence for token in _UNRESOLVED):
            report.warn(subject, f"licence unresolved: {group.first('license')}")
        if group.first("upstream_licenses") and group.statuses & {"seeded", "enrichment"}:
            report.warn(
                subject,
                "is in use and carries upstream_licenses; anything published "
                "from it must carry those terms forward",
            )

    if seeder_dir is not None and seeder_dir.is_dir():
        for path in sorted(seeder_dir.glob(seeder_glob)):
            if path.name not in referenced:
                report.warn(path.name, "seeder is not referenced by any source")

    return report
