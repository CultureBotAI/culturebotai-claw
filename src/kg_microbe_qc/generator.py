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
    timestamp: str
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

    Config YAML schema:

        repo_name: <string>            # appears in dashboard title
        yaml_dir: <path or glob root>  # absolute or relative to config
        pattern: "*.yaml"              # rglob pattern (default: *.yaml)
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

    records = list(_walk_yamls(yaml_dir, pattern))
    scores = _score(records, slots)
    stats = DashboardStats(
        repo_name=repo_name,
        record_count=len(records),
        timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
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
          f"overall {stats.overall_coverage:.1%}")
    return 1 if stats.fail_count else 0
