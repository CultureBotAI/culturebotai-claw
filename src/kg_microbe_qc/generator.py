"""QC dashboard generator: walk YAMLs, score slot coverage, render HTML."""
from __future__ import annotations

import dataclasses
import datetime as _dt
import io
import os
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import yaml  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclasses.dataclass
class SlotScore:
    slot: str
    expected: int
    populated: int
    threshold: float
    required: bool

    @property
    def coverage(self) -> float:
        return self.populated / self.expected if self.expected else 0.0

    @property
    def status(self) -> str:
        c = self.coverage
        if c >= self.threshold:
            return "PASS"
        if self.required:
            return "FAIL"
        return "WARN"


@dataclasses.dataclass
class DashboardStats:
    repo_name: str
    record_count: int
    timestamp: str | None
    scores: list[SlotScore]

    @property
    def overall_coverage(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.coverage for s in self.scores) / len(self.scores)

    @property
    def fail_count(self) -> int:
        return sum(1 for s in self.scores if s.status == "FAIL")


def _is_populated(value: Any) -> bool:
    """Treat None/empty-string/empty-list/empty-dict as not-populated."""
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)) and not value:
        return False
    return True


def _resolve_slot(record: dict, dotted_path: str) -> Any:
    """Read a dotted path through nested dicts. e.g. 'ontology_mapping.ontology_id'.
    Returns None on any missing segment."""
    cur: Any = record
    for part in dotted_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


#: Dotted paths searched for the corpus timestamp when the config names none.
#: A segment may resolve to a list, in which case every element is searched.
DEFAULT_TIMESTAMP_PATHS = ("curation_history.timestamp",)


def _iter_path_values(node: Any, parts: tuple[str, ...]) -> Iterable[Any]:
    """Yield every value at a dotted path, descending into lists on the way."""
    if isinstance(node, list):
        for item in node:
            yield from _iter_path_values(item, parts)
        return
    if not parts:
        yield node
        return
    if isinstance(node, dict) and parts[0] in node:
        yield from _iter_path_values(node[parts[0]], parts[1:])


def _parse_timestamp(value: Any) -> _dt.datetime | None:
    """Coerce an ISO-8601 timestamp to an aware UTC datetime, or None.

    Accepts the str form and the datetime/date that PyYAML produces for an
    unquoted scalar. A naive value is read as UTC.
    """
    if isinstance(value, _dt.datetime):
        parsed = value
    elif isinstance(value, _dt.date):
        parsed = _dt.datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = _dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def _corpus_timestamp(
    records: list[dict], paths: Iterable[str]
) -> str | None:
    """Latest provenance timestamp across the corpus, as an ISO-8601 string.

    This is deliberately derived from the records rather than the clock so
    that regenerating an unchanged corpus is a no-op and staleness can be
    checked by diffing. Returns None when no record carries a parseable
    timestamp -- callers must not substitute the current time.
    """
    split = [tuple(p.split(".")) for p in paths]
    latest: _dt.datetime | None = None
    for record in records:
        for parts in split:
            for value in _iter_path_values(record, parts):
                parsed = _parse_timestamp(value)
                if parsed is not None and (latest is None or parsed > latest):
                    latest = parsed
    if latest is None:
        return None
    return latest.isoformat(timespec="seconds")


def _walk_yamls(yaml_dir: Path, pattern: str) -> Iterable[dict]:
    for path in sorted(yaml_dir.rglob(pattern)):
        try:
            with open(path) as f:
                y = yaml.safe_load(f)
            if isinstance(y, dict):
                yield y
        except Exception:
            continue


def _score(records: list[dict], slots: list[dict]) -> list[SlotScore]:
    out: list[SlotScore] = []
    n = len(records)
    for spec in slots:
        slot = spec["path"]
        threshold = float(spec.get("threshold", 0.95))
        required = bool(spec.get("required", False))
        populated = sum(
            1 for r in records if _is_populated(_resolve_slot(r, slot))
        )
        out.append(SlotScore(slot, n, populated, threshold, required))
    return out


def _render_chart(scores: list[SlotScore]) -> bytes:
    """Render a horizontal bar chart of coverage; return PNG bytes."""
    if not scores:
        return b""
    labels = [s.slot for s in scores]
    coverage = [s.coverage * 100 for s in scores]
    thresholds = [s.threshold * 100 for s in scores]
    colors = [
        {"PASS": "#2c8a3a", "WARN": "#d68f00", "FAIL": "#b8302c"}[s.status]
        for s in scores
    ]

    fig_h = max(2, 0.35 * len(scores) + 1.0)
    fig, ax = plt.subplots(figsize=(8, fig_h))
    y = list(range(len(scores)))
    ax.barh(y, coverage, color=colors, alpha=0.85, edgecolor="black",
            linewidth=0.4)
    for i, t in enumerate(thresholds):
        ax.axvline(x=t, ymin=(i / len(scores)) - 0.02 * 0,
                   ymax=(i / len(scores)) + 0.02 * 0, color="black",
                   linewidth=0)
        ax.plot([t, t], [i - 0.4, i + 0.4], color="black",
                linestyle="--", linewidth=0.8, alpha=0.5)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 102)
    ax.set_xlabel("Coverage (%)")
    ax.set_title("Slot coverage per record")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()


def generate_dashboard(
    *,
    config_path: Path,
    output_dir: Path,
) -> DashboardStats:
    """Read config, score, render PNG + HTML to output_dir.

    Output is a pure function of the corpus: the dashboard carries the
    latest provenance timestamp found in the records, not the time of the
    run, so regenerating an unchanged corpus produces no diff.

    Config YAML schema:

        repo_name: <string>            # appears in dashboard title
        yaml_dir: <path or glob root>  # absolute or relative to config
        pattern: "*.yaml"              # rglob pattern (default: *.yaml)
        timestamp_paths:               # optional; where to read provenance
          - curation_history.timestamp # (default) list segments are searched
        slots:
          - path: ingredients          # dotted path in YAML
            threshold: 0.95            # coverage required for PASS
            required: true             # missing = FAIL not WARN
          - path: ontology_mapping.ontology_id
            threshold: 0.80
            required: false
    """
    config_path = config_path.resolve()
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    repo_name = cfg.get("repo_name") or config_path.parent.name
    yaml_dir = Path(cfg["yaml_dir"])
    if not yaml_dir.is_absolute():
        yaml_dir = (config_path.parent / yaml_dir).resolve()
    pattern = cfg.get("pattern", "*.yaml")
    slots = cfg.get("slots") or []

    timestamp_paths = cfg.get("timestamp_paths") or DEFAULT_TIMESTAMP_PATHS

    records = list(_walk_yamls(yaml_dir, pattern))
    scores = _score(records, slots)
    stats = DashboardStats(
        repo_name=repo_name,
        record_count=len(records),
        timestamp=_corpus_timestamp(records, timestamp_paths),
        scores=scores,
    )

    chart_png = _render_chart(scores)
    if chart_png:
        (output_dir / "coverage.png").write_bytes(chart_png)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("dashboard.html.j2").render(stats=stats)
    (output_dir / "index.html").write_text(html)

    return stats


def cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="kg_microbe_qc")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    stats = generate_dashboard(config_path=args.config, output_dir=args.output)
    print(f"{stats.repo_name}: {stats.record_count} records, "
          f"{len(stats.scores)} slots, "
          f"{stats.fail_count} FAIL, "
          f"overall {stats.overall_coverage:.1%}, "
          f"corpus as of {stats.timestamp or 'unknown'}")
    return 1 if stats.fail_count else 0
