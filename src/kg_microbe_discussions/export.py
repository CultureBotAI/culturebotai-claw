"""Flatten Discussions across a repo's records into a static browser.

Config-driven (conf/discussions_config.yaml); dependency-light (pyyaml only).
Runs under the same python3.13 + PYTHONPATH invocation as kg_microbe_qc.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
from pathlib import Path
from typing import Any

import yaml

GAP_KINDS = {"KNOWLEDGE_GAP", "HUMAN_MODEL_MISMATCH"}
_TEMPLATE = Path(__file__).resolve().parent / "templates" / "index.html"


def _load_records(config_dir: Path, record_glob: str):
    for p in sorted(_glob.glob(str(config_dir / record_glob), recursive=True)):
        path = Path(p)
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if isinstance(doc, dict):
            yield path, doc


def _source_name(doc: dict, name_fields) -> str:
    for f in name_fields:
        v = doc.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _source_id(doc: dict, id_field) -> str:
    for f in ([id_field] if id_field else ["identifier", "id"]):
        v = doc.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _evidence_refs(discussion: dict) -> list[str]:
    refs = []
    for ev in discussion.get("evidence") or []:
        if isinstance(ev, dict) and ev.get("reference"):
            refs.append(str(ev["reference"]))
    return refs


def build_records(config_dir: Path, cfg: dict) -> tuple[list[dict], dict]:
    name_fields = cfg.get("name_fields", ["name", "label", "preferred_term"])
    id_field = cfg.get("id_field")
    field = cfg.get("discussions_field", "discussions")
    page_url_tmpl = cfg.get("page_url_template", "")  # e.g. "../pages/{stem}.html#{discussion_id}"

    records: list[dict] = []
    for path, doc in _load_records(config_dir, cfg["record_glob"]):
        discussions = doc.get(field) or []
        if not discussions:
            continue
        sname, sid = _source_name(doc, name_fields), _source_id(doc, id_field)
        for d in discussions:
            if not isinstance(d, dict):
                continue
            kind = d.get("kind", "")
            exps = d.get("proposed_experiments") or []
            refs = _evidence_refs(d)
            page_url = ""
            if page_url_tmpl:
                page_url = page_url_tmpl.format(stem=path.stem, category=path.parent.name,
                                                discussion_id=d.get("discussion_id", ""))
            records.append({
                "discussion_id": d.get("discussion_id", ""),
                "prompt": d.get("prompt", ""),
                "kind": kind or "UNSPECIFIED",
                "status": d.get("status", "") or "UNSPECIFIED",
                "is_gap": "Knowledge gap" if kind in GAP_KINDS else "Other discussion",
                "source_name": sname,
                "source_id": sid,
                "source_file": str(path.name),
                "attaches_to": list(d.get("attaches_to") or []),
                "rationale": d.get("rationale", ""),
                "num_experiments": len(exps),
                "num_evidence": len(refs),
                "evidence_refs": refs,
                "posed_by": d.get("posed_by", ""),
                "page_url": page_url,
            })

    metrics = {
        "total_discussions": len(records),
        "total_knowledge_gaps": sum(1 for r in records if r["is_gap"] == "Knowledge gap"),
        "total_source_entries": len({r["source_id"] or r["source_file"] for r in records}),
        "kinds": sorted({r["kind"] for r in records}),
    }
    return records, metrics


def write_browser(records: list[dict], metrics: dict, repo_name: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    data_js = (
        f"window.searchData = {json.dumps(records, indent=1)};\n"
        f"window.searchMetrics = {json.dumps(metrics, indent=1)};\n"
        f"window.repoName = {json.dumps(repo_name)};\n"
    )
    (out_dir / "data.js").write_text(data_js)
    (out_dir / "index.html").write_text(_TEMPLATE.read_text())


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the discussions/knowledge-gap browser.")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=None, help="output dir (default: <repo>/app/discussions)")
    args = ap.parse_args()

    cfg = yaml.safe_load(args.config.read_text())
    config_dir = args.config.resolve().parent
    out_dir = args.output or (config_dir.parent / "app" / "discussions")

    records, metrics = build_records(config_dir, cfg)
    write_browser(records, metrics, cfg.get("repo_name", ""), out_dir)
    print(f"{cfg.get('repo_name','')}: {metrics['total_discussions']} discussions "
          f"({metrics['total_knowledge_gaps']} knowledge gaps) across "
          f"{metrics['total_source_entries']} records → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
