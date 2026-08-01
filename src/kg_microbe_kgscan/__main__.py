"""CLI: python -m kg_microbe_kgscan --config conf/kgscan_config.yaml [--apply ...]

Dry-run (default) emits a triage packet; --apply appends proposed
Discussion(kind=KNOWLEDGE_GAP) records to the matched YAMLs (guarded:
deterministic id for idempotency, min-score gate, --limit, and only EOF-append
when a record has no existing `discussions:` key).
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import sys
from pathlib import Path

import yaml

from .scan import build_discussion, scan_record


def _load_records(config_dir: Path, record_glob: str):
    pattern = str((config_dir / record_glob))
    for p in sorted(_glob.glob(pattern, recursive=True)):
        path = Path(p)
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if isinstance(doc, dict):
            yield path, doc


def _record_id(doc: dict, cfg: dict, path: Path) -> str:
    for f in ([cfg["id_field"]] if cfg.get("id_field") else ["identifier", "id"]):
        v = doc.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return path.stem


def _append_discussion(path: Path, field: str, discussion: dict) -> str:
    """EOF-append a `discussions:` block. Returns 'written' | 'dedup' | 'has_block'."""
    text = path.read_text()
    if discussion["discussion_id"] in text:
        return "dedup"
    import re
    if re.search(rf"^{re.escape(field)}:", text, flags=re.MULTILINE):
        # An existing block is present — don't risk a mid-file insertion.
        return "has_block"
    block = yaml.dump({field: [discussion]}, sort_keys=False, default_flow_style=False,
                      allow_unicode=True, width=4096)
    sep = "" if text.endswith("\n") else "\n"
    path.write_text(text + sep + block)
    return "written"


def render_markdown(packet: dict) -> str:
    lines = [f"# Knowledge-gap scan — {packet['repo_name']}", "",
             f"- engine: {packet['engine']}",
             f"- records scanned: {packet['records_scanned']}",
             f"- gaps proposed (score >= {packet['min_score']}): {packet['proposed']}",
             f"- applied: {packet['applied']}", ""]
    for item in packet["results"]:
        if not item.get("discussion"):
            continue
        d = item["discussion"]
        lines += [f"## {item['name']}  (score {item['score']})",
                  f"- record: `{item['record_id']}`  ·  file: `{item['file']}`",
                  f"- discussion_id: `{d['discussion_id']}`  ·  write: {item['write_status']}",
                  f"- prompt: {d['prompt']}", "- evidence:"]
        for ev in d["evidence"]:
            lines.append(f"    - {ev['reference']} — {ev['snippet']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--engine", choices=["europepmc", "edison"], default="europepmc")
    ap.add_argument("--apply", action="store_true", help="write proposed Discussions into records")
    ap.add_argument("--limit", type=int, default=0, help="cap records scanned (0 = all)")
    ap.add_argument(
        "--offset",
        type=int,
        default=0,
        help=(
            "start this many records into the corpus, wrapping around the end. "
            "With --limit it gives a rotating window, so successive scheduled runs "
            "walk the whole corpus instead of re-scanning the same head every time."
        ),
    )
    ap.add_argument("--min-score", type=int, default=None, help="override config min_score")
    ap.add_argument("--page-size", type=int, default=25)
    ap.add_argument("--max-signals", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--output-json", type=Path, default=None)
    ap.add_argument("--output-md", type=Path, default=None)
    args = ap.parse_args()

    if args.engine == "edison":
        raise NotImplementedError(
            "The Edison deep-research engine is not yet wired. Use --engine europepmc "
            "(free). The Edison hook is reserved for a future, credit-spending pass.")

    cfg = yaml.safe_load(args.config.read_text())
    config_dir = args.config.resolve().parent
    field = cfg.get("discussions_field", "discussions")
    min_score = args.min_score if args.min_score is not None else int(cfg.get("min_score", 5))

    records = list(_load_records(config_dir, cfg["record_glob"]))
    total = len(records)
    if args.offset and total:
        # Rotate rather than slice-and-truncate: an offset past the end should
        # wrap to the start, so a caller can keep incrementing a run counter
        # forever without knowing the corpus size.
        start = args.offset % total
        records = records[start:] + records[:start]
    if args.limit:
        records = records[: args.limit]

    results, proposed, applied = [], 0, 0
    for path, doc in records:
        rid = _record_id(doc, cfg, path)
        scan = scan_record(doc, cfg, args.page_size, args.max_signals, args.timeout)
        if not scan or scan.get("error") or scan["score"] < min_score:
            continue
        d = build_discussion(rid, scan)
        if not d:
            continue
        proposed += 1
        write_status = "dry-run"
        if args.apply:
            write_status = _append_discussion(path, field, d)
            if write_status == "written":
                applied += 1
        results.append({"name": scan["name"], "record_id": rid,
                        "file": str(path), "score": scan["score"],
                        "write_status": write_status, "discussion": d})
        print(f"  [{scan['score']}] {scan['name']} -> {d['discussion_id']} ({write_status})",
              file=sys.stderr)

    packet = {"repo_name": cfg.get("repo_name", ""), "engine": args.engine,
              "records_scanned": len(records), "min_score": min_score,
              "proposed": proposed, "applied": applied, "results": results}

    out_json = args.output_json or (config_dir.parent / "reports" / "knowledge_gap_scan.json")
    out_md = args.output_md or (config_dir.parent / "reports" / "knowledge_gap_scan.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(packet, indent=2))
    out_md.write_text(render_markdown(packet))
    print(f"{cfg.get('repo_name','')}: scanned {len(records)}, proposed {proposed}, "
          f"applied {applied} (engine={args.engine}, min_score={min_score})", file=sys.stderr)
    print(f"  packet: {out_json}  /  {out_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
