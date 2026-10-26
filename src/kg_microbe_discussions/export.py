"""Flatten Discussions across a repo's records into a static browser.

Config-driven (conf/discussions_config.yaml); dependency-light (pyyaml only).
Runs under the same python3.13 + PYTHONPATH invocation as kg_microbe_qc.

The page carries the fleet's theme contract itself (kg_microbe_browser.theme,
#668): dark values for the OS preference and for a saved ``mech-theme``
choice, and a toggle that writes that key. Two optional config keys carry
what is the Mech's own, its colours and a footer such as the licence line;
``--palette FILE`` and ``--footer FILE`` (YAML or JSON, holding what the key
would) take precedence, so one file can serve several pages:

    palette:              # tokens: page card fg muted line accent
      light: {accent: "#9d292d", page: "#fafafa"}
      dark: {accent: "#ffb3b5", page: "#101820"}
    footer:               # lines of text and {text, href} links
      - - "Data: "
        - {text: "CC BY 4.0", href: "https://github.com/CultureBotAI/<Mech>/blob/main/LICENSE-DATA"}
        - "; code: "
        - {text: "BSD-3-Clause", href: "https://github.com/CultureBotAI/<Mech>/blob/main/LICENSE-CODE"}
        - ". Third-party material keeps its own terms."
      - ["Part of the ", {text: "X-Mech Suite", href: "https://culturebotai.github.io/mechs/"}, "."]

Quote colours, since an unquoted ``#`` starts a YAML comment, and state the
licences as the Mech's own licence files do: they differ between Mechs.
Without either key the page keeps its neutral palette and has no footer.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import re
from pathlib import Path

import yaml

from kg_microbe_browser.theme import ThemeError, page_chrome, read_option

GAP_KINDS = {"KNOWLEDGE_GAP", "HUMAN_MODEL_MISMATCH"}
_TEMPLATE = Path(__file__).resolve().parent / "templates" / "index.html"
_SLOT = re.compile(r"<!--slot:([a-z-]+)-->")

#: The page's look before #668 in light, and its counterpart in dark. A
#: palette may override kg_microbe_browser.theme.PALETTE_TOKENS; the badge
#: colours stay these.
DEFAULT_PALETTE = {
    "light": {
        "page": "#fff", "card": "#fff", "fg": "#1a1a1a", "fg-soft": "#333",
        "muted": "#666", "line": "#e2e2e2", "accent": "#2a6", "focus": "#0969da",
        "badge": "#eef", "badge-fg": "#225", "gap": "#fee", "gap-fg": "#922",
    },
    "dark": {
        "page": "#0d1117", "card": "#161b22", "fg": "#e6edf3", "fg-soft": "#c9d1d9",
        "muted": "#9da7b3", "line": "#3d444d", "accent": "#56d39a", "focus": "#58a6ff",
        "badge": "#1f2747", "badge-fg": "#c8d1ff", "gap": "#3d1a1d", "gap-fg": "#ffb4ae",
    },
}


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


def render_index(*, palette: object = None, footer: object = None) -> str:
    """The browser page with its theme, palette and footer filled in."""
    chrome = page_chrome(DEFAULT_PALETTE, palette=palette, footer=footer)
    slots = {"theme-head": chrome.head, "theme-css": chrome.css,
             "theme-toggle": chrome.toggle, "footer": chrome.footer}
    template = _TEMPLATE.read_text()
    found = _SLOT.findall(template)
    if sorted(found) != sorted(slots):
        raise RuntimeError(f"{_TEMPLATE.name} must hold each slot of {sorted(slots)} once, "
                           f"found {found}")
    # One pass, so nothing a slot inserts is read as another slot.
    return _SLOT.sub(lambda match: slots[match.group(1)], template)


def write_browser(records: list[dict], metrics: dict, repo_name: str, out_dir: Path,
                  *, palette: object = None, footer: object = None) -> None:
    """Write index.html and data.js; see the module docstring for the options."""
    index = render_index(palette=palette, footer=footer)  # refuses before writing
    out_dir.mkdir(parents=True, exist_ok=True)
    data_js = (
        f"window.searchData = {json.dumps(records, indent=1)};\n"
        f"window.searchMetrics = {json.dumps(metrics, indent=1)};\n"
        f"window.repoName = {json.dumps(repo_name)};\n"
    )
    (out_dir / "data.js").write_text(data_js)
    (out_dir / "index.html").write_text(index)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the discussions/knowledge-gap browser.")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=None, help="output dir (default: <repo>/app/discussions)")
    ap.add_argument("--palette", type=Path, default=None,
                    help="YAML/JSON light and dark colour tokens; overrides the config's palette")
    ap.add_argument("--footer", type=Path, default=None,
                    help="YAML/JSON footer lines, e.g. the licence line; overrides the config's footer")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text())
    config_dir = args.config.resolve().parent
    out_dir = args.output or (config_dir.parent / "app" / "discussions")

    records, metrics = build_records(config_dir, cfg)
    try:
        write_browser(records, metrics, cfg.get("repo_name", ""), out_dir,
                      palette=read_option("--palette", args.palette, cfg.get("palette")),
                      footer=read_option("--footer", args.footer, cfg.get("footer")))
    except ThemeError as error:
        ap.error(str(error))
    print(f"{cfg.get('repo_name','')}: {metrics['total_discussions']} discussions "
          f"({metrics['total_knowledge_gaps']} knowledge gaps) across "
          f"{metrics['total_source_entries']} records → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
