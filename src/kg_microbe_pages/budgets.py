"""Page-size and file-count budgets for a generated site (#132 Phase 6, item 1).

The acceptance criterion is that common site behaviour and budgets are "tested
once centrally". Today one Mech has budgets at all -- ProteinTraitsMech, whose
`audit_pages_size.py` runs in its Pages workflow against `conf/pages_budgets.json`
-- and the others generate a site with nothing watching its size.

What generalizes from that script is the shape: measure the built site, compare
against declared limits, fail with the numbers. What does not is the layout it
measures. `data/records.*.json` and `data/detail/*.json` are that site's browse
shards and detail buckets, written into the code as literals, so no other Mech
can use it without editing it. Here a Mech names its own groups as globs and the
same checker reads them.

The part most worth carrying over is the smallest. That script fails when it
finds no browse shards or no detail buckets, which looks like a footnote and is
the only thing standing between it and a budget that cannot fail: a site that
generated nothing is under every size limit. Generalized, every group may
declare `min_files`, and a site with no files at all is a failure regardless of
what any group says.

Budgets themselves stay in the Mech. A limit is tuned to one site's content and
its owners' judgement about what is too big; the mechanism is what belongs here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "BudgetError",
    "GroupBudget",
    "SiteBudgets",
    "audit",
    "load_budgets",
    "measure",
]

_SCALAR_METRICS = ("site_total_bytes", "generated_file_count")


class BudgetError(RuntimeError):
    """The budget declaration could not be read."""


@dataclass(frozen=True)
class GroupBudget:
    """A named part of the site, and what it may cost."""

    name: str
    glob: str
    total_bytes: int | None = None
    largest_bytes: int | None = None
    min_files: int = 0


@dataclass(frozen=True)
class SiteBudgets:
    site_total_bytes: int | None = None
    generated_file_count: int | None = None
    min_files: int = 1
    groups: tuple[GroupBudget, ...] = field(default_factory=tuple)


def load_budgets(path: Path) -> SiteBudgets:
    """Read a budget file, refusing anything it cannot act on."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise BudgetError(f"cannot read budgets {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BudgetError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BudgetError(f"{path} must be a JSON object")

    unknown = set(raw) - set(_SCALAR_METRICS) - {"min_files", "groups"}
    if unknown:
        raise BudgetError(
            f"{path} has unknown keys: {', '.join(sorted(unknown))}. A budget "
            f"nothing reads is a limit nobody is holding to."
            + _conversion_hint(unknown)
        )

    groups: list[GroupBudget] = []
    for name, spec in (raw.get("groups") or {}).items():
        if not isinstance(spec, dict):
            raise BudgetError(f"{path}: group {name!r} must be an object")
        extra = set(spec) - {"glob", "total_bytes", "largest_bytes", "min_files"}
        if extra:
            raise BudgetError(f"{path}: group {name!r} has unknown keys {sorted(extra)}")
        if not spec.get("glob"):
            raise BudgetError(f"{path}: group {name!r} must name a glob")
        groups.append(
            GroupBudget(
                name=name,
                glob=str(spec["glob"]),
                total_bytes=_optional_int(spec.get("total_bytes"), path, name),
                largest_bytes=_optional_int(spec.get("largest_bytes"), path, name),
                min_files=_optional_int(spec.get("min_files"), path, name) or 0,
            )
        )

    return SiteBudgets(
        site_total_bytes=_optional_int(raw.get("site_total_bytes"), path, "site"),
        generated_file_count=_optional_int(
            raw.get("generated_file_count"), path, "site"
        ),
        min_files=(
            1 if raw.get("min_files") is None
            else _optional_int(raw.get("min_files"), path, "site") or 0
        ),
        groups=tuple(sorted(groups, key=lambda g: g.name)),
    )


# The flat keys ProteinTraitsMech's own budget file uses. They named its two
# groups in the metric name -- `largest_browse_shard_bytes` -- which is why no
# other repository could use that file's schema. Recognising them is not
# accepting them: two ways to say one thing is the duplication this phase
# removes. It is so the migration reads as mechanical rather than as a rewrite.
_LEGACY_GROUPS = {
    "browse_index": ("browse_index_total_bytes", "largest_browse_shard_bytes"),
    "detail": ("detail_total_bytes", "largest_detail_bucket_bytes"),
}


def _conversion_hint(unknown: set[str]) -> str:
    named = {
        group: keys
        for group, keys in _LEGACY_GROUPS.items()
        if set(keys) & unknown
    }
    if not named:
        return ""
    lines = [
        "",
        "",
        "These are per-group limits with the group written into the metric "
        "name. Declare the group instead, so the glob says which files it "
        "means:",
        "",
        '  "groups": {',
    ]
    for group, (total, largest) in sorted(named.items()):
        lines.append(
            f'    "{group}": {{"glob": "...", "total_bytes": <{total}>, '
            f'"largest_bytes": <{largest}>, "min_files": 1}},'
        )
    lines.append("  }")
    return "\n".join(lines)


def _optional_int(value: Any, path: Path, subject: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetError(f"{path}: {subject} limit must be an integer, got {value!r}")
    if value < 0:
        raise BudgetError(f"{path}: {subject} limit must not be negative")
    return value


def measure(site: Path, budgets: SiteBudgets) -> dict[str, int]:
    """Measure the built site, in the shape the budgets are written in."""
    site = Path(site)
    files = [path for path in sorted(site.rglob("*")) if path.is_file()]
    sizes = {path: path.stat().st_size for path in files}

    metrics: dict[str, int] = {
        "site_total_bytes": sum(sizes.values()),
        "generated_file_count": len(files),
    }
    for group in budgets.groups:
        matched = [path for path in sorted(site.glob(group.glob)) if path.is_file()]
        metrics[f"{group.name}_files"] = len(matched)
        metrics[f"{group.name}_total_bytes"] = sum(sizes.get(p, 0) for p in matched)
        metrics[f"{group.name}_largest_bytes"] = max(
            (sizes.get(p, 0) for p in matched), default=0
        )
    return metrics


def audit(site: Path, budgets: SiteBudgets) -> tuple[dict[str, int], list[str]]:
    """Measure and compare. Returns the metrics and every limit exceeded."""
    site = Path(site)
    if not site.is_dir():
        return {}, [f"{site} is not a directory; nothing was generated"]

    metrics = measure(site, budgets)
    failures: list[str] = []

    # Before any size limit. A site that generated nothing is under every one
    # of them, which is how a budget stops being a check at all.
    if metrics["generated_file_count"] < budgets.min_files:
        failures.append(
            f"site has {metrics['generated_file_count']} file(s); expected at "
            f"least {budgets.min_files} -- an empty site passes every size budget"
        )

    for name in _SCALAR_METRICS:
        limit = getattr(budgets, name)
        if limit is not None and metrics[name] > limit:
            failures.append(f"{name}: {metrics[name]:,} > {limit:,}")

    for group in budgets.groups:
        found = metrics[f"{group.name}_files"]
        if found < group.min_files:
            failures.append(
                f"{group.name}: {found} file(s) matched {group.glob!r}; expected "
                f"at least {group.min_files}"
            )
        for suffix, limit in (
            ("total_bytes", group.total_bytes),
            ("largest_bytes", group.largest_bytes),
        ):
            if limit is None:
                continue
            actual = metrics[f"{group.name}_{suffix}"]
            if actual > limit:
                failures.append(f"{group.name}_{suffix}: {actual:,} > {limit:,}")

    return metrics, failures


def as_json(metrics: Mapping[str, int], failures: list[str]) -> str:
    return (
        json.dumps(
            {"metrics": dict(sorted(metrics.items())), "failures": failures},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
