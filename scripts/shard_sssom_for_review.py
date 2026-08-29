"""Split a working-copy SSSOM TSV into N contiguous shards for the
agent-team review path (`team-review-sssom` skill).

Each shard is itself a valid mini-SSSOM: the full `#`-prefixed YAML
frontmatter and the column header are copied verbatim, followed by a
contiguous slice of data rows. This lets each agent open its shard
with any SSSOM-aware tool (including `sssom validate` and the existing
`review_sssom_synonyms.py`) without special-casing shard files.

Shards are written to `workspace/shards/sssom_review/shard_{i}.tsv`
(i = 0..N-1). The directory is wiped before writing so stale shards
from a prior run don't leak into this one.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CLAW_ROOT = REPO_ROOT
DEFAULT_INPUT = CLAW_ROOT / "workspace" / "reports" / "mim_ingredient_mappings.sssom.tsv"
DEFAULT_SHARD_DIR = CLAW_ROOT / "workspace" / "shards" / "sssom_review"


def _split_sssom(path: Path) -> tuple[str, str, list[str]]:
    """Return (header_text, column_header_line, data_lines) for an SSSOM
    TSV. Preserves trailing newlines; each list element is one data
    row INCLUDING its trailing newline."""
    lines = path.read_text().splitlines(keepends=True)
    header_lines: list[str] = []
    data_lines: list[str] = []
    column_header: str = ""
    for ln in lines:
        if ln.startswith("#"):
            header_lines.append(ln)
        elif not column_header:
            column_header = ln
        else:
            data_lines.append(ln)
    if not column_header:
        raise SystemExit(f"No column header found in {path} — not a valid SSSOM TSV")
    return "".join(header_lines), column_header, data_lines


def _shard_ranges(n_rows: int, n_shards: int) -> list[tuple[int, int]]:
    """Return N (start, end) tuples covering [0, n_rows) as evenly as
    possible. end is exclusive."""
    base, extra = divmod(n_rows, n_shards)
    ranges: list[tuple[int, int]] = []
    start = 0
    for i in range(n_shards):
        size = base + (1 if i < extra else 0)
        ranges.append((start, start + size))
        start += size
    return ranges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--n", type=int, default=4, help="number of shards (default: 4)")
    ap.add_argument("--shard-dir", type=Path, default=DEFAULT_SHARD_DIR)
    ap.add_argument("--dry-run", action="store_true",
                    help="print shard plan without writing")
    args = ap.parse_args()

    if args.n < 1:
        raise SystemExit("--n must be >= 1")
    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")

    header_text, column_header, data_lines = _split_sssom(args.input)
    ranges = _shard_ranges(len(data_lines), args.n)

    print(f"Sharding {args.input.name}: {len(data_lines)} rows → {args.n} shards",
          file=sys.stderr)
    for i, (start, end) in enumerate(ranges):
        print(f"  shard_{i}.tsv: rows [{start}, {end})  ({end - start} rows)",
              file=sys.stderr)

    if args.dry_run:
        print("  (dry-run — no files written)", file=sys.stderr)
        return

    if args.shard_dir.exists():
        shutil.rmtree(args.shard_dir)
    args.shard_dir.mkdir(parents=True)

    for i, (start, end) in enumerate(ranges):
        out = args.shard_dir / f"shard_{i}.tsv"
        with out.open("w") as f:
            f.write(header_text)
            if not header_text.endswith("\n"):
                f.write("\n")
            f.write(column_header)
            for line in data_lines[start:end]:
                f.write(line)
        print(f"  wrote {out.name} ({end - start} rows)", file=sys.stderr)

    print(f"\nShards: {args.shard_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
