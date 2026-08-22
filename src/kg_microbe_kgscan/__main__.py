"""CLI: python -m kg_microbe_kgscan --config conf/kgscan_config.yaml [--apply ...]

Dry-run (default) emits a triage packet; --apply appends proposed
Discussion(kind=KNOWLEDGE_GAP) records to the matched YAMLs (guarded:
deterministic id for idempotency, min-score gate, --limit, and only EOF-append
when a record has no existing `discussions:` key).

Precision gates (#69): the signal sentence must mention a topic term
(`require_topic_in_sentence: false` in the config disables -- see scan.py's
docstring), contentless boilerplate is rejected, and a sentence filed under
two records in one run keeps only the best-scored filing. Existing Discussion
evidence is indexed across the complete corpus before an offset window is
selected, so rotating scheduled runs cannot file the same sentence under a
second record (#72).
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import sys
from pathlib import Path

import yaml

from .scan import build_discussion, prompt_key, scan_record


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


def _existing_prompt_owners(records, cfg: dict, field: str) -> dict[str, tuple[str, ...]]:
    """Index existing Discussion evidence snippets across the whole corpus.

    The index is built before ``--offset``/``--limit`` are applied. Otherwise
    rotating windows would only see their own slice and cross-run dedup would
    remain ineffective (#72). Empty or malformed entries are ignored rather
    than collapsed onto one empty key.
    """
    owners: dict[str, set[str]] = {}
    for path, doc in records:
        rid = _record_id(doc, cfg, path)
        discussions = doc.get(field) or []
        if not isinstance(discussions, list):
            continue
        for discussion in discussions:
            if not isinstance(discussion, dict):
                continue
            evidence = discussion.get("evidence") or []
            if not isinstance(evidence, list):
                continue
            # A scanner-built Discussion puts the promoted sentence first,
            # but index every evidence snippet so older/manual records cannot
            # hide a duplicate in a later citation.
            for entry in evidence:
                key = prompt_key({"evidence": [entry]})
                if key:
                    owners.setdefault(key, set()).add(rid)
    return {key: tuple(sorted(rids)) for key, rids in owners.items()}


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
             f"- applied: {packet['applied']}",
             f"- existing filings skipped: {packet.get('existing_skipped', 0)}",
             f"- cross-record duplicates dropped: {packet.get('duplicates_dropped', 0)}", ""]
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
    # The losers, not just their count: a curator reading only the Markdown
    # (or the workflow's head-of-file step summary) must be able to see which
    # record lost a sentence to which, or the dedup is invisible judgement.
    dropped = [r for r in packet["results"]
               if str(r.get("write_status", "")).startswith("cross_record_duplicate")]
    if dropped:
        lines.append("## Dropped cross-record duplicates")
        for r in dropped:
            kept = r["write_status"].removeprefix("cross_record_duplicate_of:")
            lines.append(f"- `{r['record_id']}` (score {r['score']}) lost to `{kept}`: "
                         f"{r.get('duplicate_sentence', '')}")
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

    all_records = list(_load_records(config_dir, cfg["record_glob"]))
    existing_owners = _existing_prompt_owners(all_records, cfg, field)
    records = all_records
    total = len(records)
    if args.offset and total:
        # Rotate rather than slice-and-truncate: an offset past the end should
        # wrap to the start, so a caller can keep incrementing a run counter
        # forever without knowing the corpus size.
        start = args.offset % total
        records = records[start:] + records[:start]
    if args.limit:
        records = records[: args.limit]

    # Phase 1: scan everything. Dedup needs the full candidate set before any
    # verdicts, because the BEST-scored filing of a shared sentence must win
    # (#76) -- deciding while streaming kept whichever record the glob reached
    # first, and --offset rotation changed the winner between runs.
    scanned = []
    for path, doc in records:
        rid = _record_id(doc, cfg, path)
        scan = scan_record(doc, cfg, args.page_size, args.max_signals, args.timeout)
        if not scan or scan.get("error") or scan["score"] < min_score:
            continue
        d = build_discussion(rid, scan)
        if not d:
            continue
        scanned.append((path, rid, scan, d))

    # Cross-record dedup (#69): the same promoted sentence under two records
    # means at least one filing is wrong. Highest score wins; ties break on
    # record id, so the outcome is deterministic regardless of scan order.
    winner: dict[str, str] = {}
    best: dict[str, tuple[int, str]] = {}
    for _path, rid, scan, d in scanned:
        key = prompt_key(d)
        rank = (scan["score"], )
        cur = best.get(key)
        if cur is None or rank > (cur[0],) or (rank == (cur[0],) and rid < cur[1]):
            best[key] = (scan["score"], rid)
            winner[key] = rid

    results, proposed, applied, duplicates, existing_skipped = [], 0, 0, 0, 0
    for path, rid, scan, d in scanned:
        key = prompt_key(d)
        owners = existing_owners.get(key, ())
        if owners:
            owner = owners[0]
            if rid in owners:
                existing_skipped += 1
                status = f"already_present_in:{rid}"
            else:
                duplicates += 1
                status = f"cross_record_duplicate_of:{owner}"
            results.append({"name": scan["name"], "record_id": rid,
                            "file": str(path), "score": scan["score"],
                            "write_status": status,
                            "duplicate_sentence": d["evidence"][0]["snippet"],
                            "discussion": None})
            print(f"  [dup] {scan['name']}: gap sentence already filed under "
                  f"{', '.join(owners)} -- dropped", file=sys.stderr)
            continue
        if rid != winner[key]:
            duplicates += 1
            results.append({"name": scan["name"], "record_id": rid,
                            "file": str(path), "score": scan["score"],
                            "write_status": f"cross_record_duplicate_of:{winner[key]}",
                            "duplicate_sentence": d["evidence"][0]["snippet"],
                            "discussion": None})
            print(f"  [dup] {scan['name']}: same gap sentence filed under "
                  f"{winner[key]} (higher score) -- dropped", file=sys.stderr)
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
              "proposed": proposed, "applied": applied,
              "existing_skipped": existing_skipped,
              "duplicates_dropped": duplicates, "results": results}

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
