"""
Promote the working-copy SSSOM (`workspace/reports/mim_ingredient_mappings.sssom.tsv`)
to the canonical publish location
(`MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv`).

This is stage 4 of the publish-sssom lifecycle. Run only after the first
three stages (build → validate → review) are green. This script
re-validates the working copy as its final check and exits non-zero on
any hard error.

Safety:
- Acquires the `mediaingredientmech` lock via plugins.lock_manager.LockManager
  (see CLAUDE.md "Lock System") before touching the MIM repo.
- Diffs the working copy against the published file as row *sets* keyed on
  `(subject_id, object_id)`, and refuses to promote if more than 5 rows would
  be genuinely removed (guards against truncation), or if any row would flip
  from `skos:exactMatch` to a weaker predicate -- whether as a same-subject
  flip or riding along with a subject re-spelling (guards against a rebuild
  quietly downgrading identity claims -- MediaIngredientMech#409).
- Appends an audit entry (pointer + counts, not the full diff -- see below)
  to workspace/status/sssom_promotions.jsonl.

Why a set diff and not a row count (MediaIngredientMech#416):
    A count is blind to churn. On 2026-08-21 the working copy had 2,885 rows
    against 2,938 published, and the count guard reported a flat "-53". The
    real shape was 155 rows out and 102 in, and 88/93 of those were the same
    records under a re-spelled subject -- the published file was carrying
    `MIM:` subjects whose record files had since been renamed. Reported as one
    net number, a correction is indistinguishable from a truncation, so the
    guard blocked for weeks on a difference nobody could see without rebuilding
    and diffing by hand. The diff below separates re-spellings (neutral) from
    genuine removals (gated) and predicate flips (reported), so the guard's own
    output is the diagnosis.

Usage:
    python scripts/publish_sssom.py --dry-run     # default: prints what would happen
    python scripts/publish_sssom.py --apply       # actually promote
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
WORKING_COPY = CLAW_ROOT / "workspace" / "reports" / "mim_ingredient_mappings.sssom.tsv"
PUBLISHED = MIM_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"
# One line per promotion: timestamp, hashes, row counts, and a diff_counts
# summary. Deliberately does NOT embed the full added/removed/respelled/
# flipped lists -- see diff_archive at the apply site (#113: an embedded
# diff has no size bound, and a first publish or a full re-spelling rebuild
# would write ~2,900 pairs as a single JSONL line).
AUDIT_LOG = CLAW_ROOT / "workspace" / "status" / "sssom_promotions.jsonl"
# The full diff, written on every run including --dry-run. stdout shows only
# EXAMPLES_SHOWN per category, and dry-run is the mode a curator uses to work
# out *why* promotion was refused -- so the remaining entries have to land
# somewhere readable rather than only in the apply-path audit log. Overwritten
# each run -- this is "what would the diff show right now", not history; a
# promotion's permanent record is the diff_archive file the apply path writes
# instead (named by the (previous_hash, published_hash) pair, not just the
# new hash -- see the comment where diff_archive is built for why a
# single-hash name would collide on a revert-and-redo).
DIFF_REPORT = CLAW_ROOT / "workspace" / "reports" / "sssom_promotion_diff.json"
LOCKS_DIR = CLAW_ROOT / "workspace" / "locks"
ROW_COUNT_DROP_LIMIT = 5

SSSOM_BIN = "sssom"

# How many examples of each diff category to print. The full lists go into
# DIFF_REPORT / diff_archive; stdout stays readable.
EXAMPLES_SHOWN = 8


def _load_lock_manager():
    """Import plugins.lock_manager directly, bypassing plugins/__init__.py
    (which has other heavy deps we don't need here)."""
    spec = importlib.util.spec_from_file_location(
        "lock_manager", CLAW_ROOT / "plugins" / "lock_manager.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LockManager


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open() as f:
        for line in f:
            if line.startswith("#"):
                continue
            if not line.strip():
                continue
            n += 1
    # minus the header row
    return max(0, n - 1)


def _read_rows(path: Path) -> list[dict[str, str]]:
    """Parse an SSSOM TSV into dicts, dropping the `#`-prefixed YAML preamble."""
    if not path.exists():
        return []
    with path.open() as f:
        body = [ln for ln in f if not ln.startswith("#") and ln.strip()]
    if not body:
        return []
    return list(csv.DictReader(body, delimiter="\t"))


# Characters MIM's `curie.py::mim_curie_for_stem` leaves alone; everything else
# it rewrites as `~HEX`. `~` is included so an already-escaped local id is a
# fixed point.
_SUBJECT_SAFE = re.compile(r"[^A-Za-z0-9_\-.~]")


def _spelling_key(subject: str) -> str:
    """Collapse the spellings of one record's subject to a single key.

    Two published-vs-rebuilt spelling differences are not identity changes:
    letter case (`MIM:EDTA_Stock` vs `MIM:Edta_Stock`, a scar of the
    `capitalize()` bug in MediaIngredientMech#147) and `~HEX` escaping
    (`MIM:(R)-lactate` vs `MIM:~28R~29-lactate`).

    Normalisation escapes rather than unescapes, because the escape is
    variable-width hex and therefore ambiguous to decode: `~3911` is
    `chr(0x391) + "1"`, but nothing in the string says so. Encoding has no such
    ambiguity, so both spellings are pushed to the escaped form and casefolded.

    Deliberately conservative. An older naming rule *stripped* unsafe characters
    rather than escaping them, so `MIM:Sodium` and `MIM:Sodium~28~29` are also
    one record -- but recovering that needs a lossy normalisation that could
    just as easily collapse two distinct records onto one key. Those are left to
    surface as a removal plus an addition for a human to confirm. A guard that
    guesses is the failure mode this function exists to remove.
    """
    prefix, sep, local = subject.partition(":")
    if not sep:
        return subject.casefold()
    escaped = _SUBJECT_SAFE.sub(lambda m: f"~{ord(m.group(0)):02X}", local)
    return f"{prefix.casefold()}:{escaped.casefold()}"


# Predicates that assert row identity outright. Flipping *away* from one of
# these to anything else discards information a downstream consumer may be
# relying on (MediaIngredientMech#409: a 249-row exactMatch -> closeMatch
# rebuild regression that no guard caught). Flipping the other way -- a
# provisional predicate tightened to exactMatch -- is the normal outcome of
# curation and is deliberately not gated.
#
# Scope is intentionally narrow: this only classifies exact-vs-not, not a
# full precision ordering across closeMatch/narrowMatch/broadMatch/
# relatedMatch (which SSSOM does not itself define a total order for). A
# lateral flip among those weaker predicates is reported (it is still in
# `flipped`) but not gated.
_EXACT_PREDICATES = frozenset({"skos:exactMatch"})


@dataclass
class SssomDiff:
    """A `(subject_id, object_id)`-keyed comparison of two SSSOM row sets."""

    # Rows whose (subject, object) key AND predicate both survived. NOT
    # "identical row" -- see column_changes, which is the rest of the story.
    same_key_and_predicate: int = 0
    added: list[tuple[str, str]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    respelled: list[tuple[str, str, str]] = field(default_factory=list)
    flipped: list[tuple[str, str, str, str]] = field(default_factory=list)
    # Respelling pairs (old_subject, new_subject, object, old_predicate,
    # new_predicate) whose predicate ALSO weakened from exactMatch. A
    # respelling changes the (subject, object) key itself, so a predicate
    # downgrade riding along with it would otherwise vanish from both
    # `flipped` (which only sees unchanged keys) and `respelled` (which
    # doesn't carry predicate_id) -- a respelling would silently launder a
    # widening flip past the gate. Kept as its own list rather than folded
    # into `flipped` because the tuple shapes differ (respelling has two
    # subjects, not one).
    #
    # Scope boundary, deliberately not closed further: this only pairs a
    # removed row with an added row when the OBJECT is unchanged (see
    # `added_by_spelling`'s key below). If a rebuild changes the subject's
    # spelling AND retargets the object (e.g. a corrected CHEBI id) AND
    # weakens the predicate, all in the same row, it reads as plain
    # `removed`+`added` -- gated by --allow-drop, not --allow-widening-flips.
    # Unlike a respelling (where `_spelling_key` gives an unambiguous
    # correlation key), there is no analogous "this is probably the same
    # record" signal once the object itself changes -- a different CHEBI id
    # asserts a different concept, so treating it as a continuation of the
    # same claim would be a guess, not a fact. See diff_rows() for how the
    # cheaper, unambiguous case (object unchanged) is still caught.
    respelled_widening: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    # column -> how many surviving rows changed it. Reported, not gated: most of
    # this is legitimate rebuild output (`source`, `mapping_date`) and gating it
    # would make promotion impossible. But it must be visible -- keying on
    # (subject, object, predicate) alone would let a rebuild rewrite every
    # object_label and still report "unchanged".
    column_changes: dict[str, int] = field(default_factory=dict)
    # Rows sharing a (subject_id, object_id) with an earlier row, and therefore
    # absent from this comparison. Non-zero means the diff does not account for
    # every row in the file and its numbers should not be trusted.
    collapsed_prev: int = 0
    collapsed_new: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.respelled or self.flipped)

    @property
    def widening_flips(self) -> list[tuple[str, str, str, str]]:
        """The subset of `flipped` that leaves an exact-identity predicate.

        Part of what `--allow-widening-flips` gates on -- see `all_widening`,
        which also covers the same loss riding along with a respelling.
        `flipped` itself stays ungated -- most predicate churn is legitimate
        (a provisional mapping tightened to exactMatch), and gating on the raw
        count would block that.
        """
        return [
            f for f in self.flipped
            if f[2] in _EXACT_PREDICATES and f[3] not in _EXACT_PREDICATES
        ]

    @property
    def all_widening(self) -> list[tuple]:
        """Every row that lost skos:exactMatch, respelled or not.

        This -- not `widening_flips` alone -- is what `--allow-widening-flips`
        gates on. `widening_flips` and `respelled_widening` have different
        tuple shapes (4 fields vs 5: a respelling carries two subjects), so
        they stay separate lists; this just unions them for gating/reporting.
        """
        return [*self.widening_flips, *self.respelled_widening]


def diff_rows(prev: list[dict[str, str]], new: list[dict[str, str]]) -> SssomDiff:
    """Compare two SSSOM row sets on `(subject_id, object_id)`.

    A row present on one side only is not automatically an add or a removal:
    if the same object appears on the other side under a subject that is only
    *spelled* differently, the record did not leave the mapping set, its
    subject was rewritten. Those pair up as `respelled` and are neutral for the
    truncation guard -- but they are reported, because 82 of them at once means
    every downstream consumer holding the old subject needs an alias row.
    """
    prev_by_key = {(r["subject_id"], r["object_id"]): r for r in prev}
    new_by_key = {(r["subject_id"], r["object_id"]): r for r in new}

    # Keying on (subject, object) silently drops any row that repeats the pair.
    # Neither artifact has one today, but "today's data has none" is not the
    # same as "this cannot happen", and an undetected collapse would make every
    # number below quietly wrong. Count them and say so.
    diff = SssomDiff(
        collapsed_prev=len(prev) - len(prev_by_key),
        collapsed_new=len(new) - len(new_by_key),
    )

    shared = prev_by_key.keys() & new_by_key.keys()
    column_changes: collections.Counter[str] = collections.Counter()
    for key in shared:
        old_row, new_row = prev_by_key[key], new_by_key[key]
        old_pred = old_row.get("predicate_id", "")
        new_pred = new_row.get("predicate_id", "")
        if old_pred != new_pred:
            diff.flipped.append((key[0], key[1], old_pred, new_pred))
        else:
            diff.same_key_and_predicate += 1
        # Everything the key and the predicate do not cover.
        for col in old_row.keys() | new_row.keys():
            if col in ("subject_id", "object_id", "predicate_id"):
                continue
            if old_row.get(col) != new_row.get(col):
                column_changes[col] += 1
    diff.column_changes = dict(column_changes.most_common())

    only_prev = prev_by_key.keys() - new_by_key.keys()
    only_new = new_by_key.keys() - prev_by_key.keys()

    # Index the added rows by (spelling-insensitive subject, object) so a removed
    # row can find its re-spelled counterpart. Two added rows can share a key
    # (e.g. `MIM:Foo` and `MIM:foo` onto the same object), so pop() keeps the
    # pairing one-to-one. Iterate sorted, not in set order, so which of them is
    # reported as the re-spelling does not vary with PYTHONHASHSEED.
    added_by_spelling: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for subject, obj in sorted(only_new):
        added_by_spelling.setdefault((_spelling_key(subject), obj), []).append((subject, obj))

    for subject, obj in sorted(only_prev):
        candidates = added_by_spelling.get((_spelling_key(subject), obj))
        if candidates:
            new_subject, _ = candidates.pop()
            diff.respelled.append((subject, new_subject, obj))
            # A respelling changes the (subject, object) key, so this pair
            # never appears in `shared` above -- a predicate downgrade riding
            # along with the respelling would otherwise be invisible.
            old_pred = prev_by_key[(subject, obj)].get("predicate_id", "")
            new_pred = new_by_key[(new_subject, obj)].get("predicate_id", "")
            if old_pred in _EXACT_PREDICATES and new_pred not in _EXACT_PREDICATES:
                diff.respelled_widening.append((subject, new_subject, obj, old_pred, new_pred))
        else:
            diff.removed.append((subject, obj))

    for remaining in added_by_spelling.values():
        diff.added.extend(remaining)
    diff.added.sort()

    return diff


def _print_diff(diff: SssomDiff) -> None:
    print("\nRow-set diff (keyed on subject_id + object_id):")
    print(f"  same key + predicate  {diff.same_key_and_predicate}")
    print(f"  added                 {len(diff.added)}")
    print(f"  removed               {len(diff.removed)}")
    print(f"  subject re-spelled    {len(diff.respelled)}")
    print(f"  predicate flipped     {len(diff.flipped)}")
    if diff.widening_flips:
        print(
            f"    of which widening (exactMatch -> weaker): {len(diff.widening_flips)}"
        )
    if diff.respelled_widening:
        print(
            f"  subject re-spelled AND widening (exactMatch -> weaker): "
            f"{len(diff.respelled_widening)}"
        )
    if diff.all_widening:
        print(
            f"  total widening (gated): {len(diff.all_widening)}  "
            "<- see --allow-widening-flips"
        )

    if diff.column_changes:
        print("\n  Other columns changed on surviving rows (reported, not gated):")
        for col, n in diff.column_changes.items():
            print(f"    {col:<24}{n}")
        if "object_label" in diff.column_changes:
            print(
                f"    ^ object_label moved on {diff.column_changes['object_label']} row(s). "
                "Rule B4 only checks\n"
                "      ontology-prefix objects and is skipped without the kg-microbe "
                "transforms, so\n"
                "      registry-prefix labels reach publication unverified. Read them "
                "before promoting."
            )

    if diff.collapsed_prev or diff.collapsed_new:
        print(
            f"\n  WARNING: {diff.collapsed_prev} published and {diff.collapsed_new} "
            "working-copy row(s) repeat a (subject_id, object_id) pair and are not\n"
            "  represented above. The counts in this diff are incomplete."
        )

    def show(title: str, items: list, fmt) -> None:
        if not items:
            return
        print(f"\n  {title}:")
        for item in items[:EXAMPLES_SHOWN]:
            print(f"    {fmt(item)}")
        if len(items) > EXAMPLES_SHOWN:
            print(f"    ... and {len(items) - EXAMPLES_SHOWN} more")

    show("removed", diff.removed, lambda r: f"{r[0]} -> {r[1]}")
    show("added", diff.added, lambda r: f"{r[0]} -> {r[1]}")
    show(
        "subject re-spelled (same object, same record)",
        diff.respelled,
        lambda r: f"{r[0]}  =>  {r[1]}   ({r[2]})",
    )
    show(
        "predicate flipped",
        diff.flipped,
        lambda r: f"{r[0]} -> {r[1]}: {r[2]} => {r[3]}",
    )
    show(
        "subject re-spelled AND predicate widened",
        diff.respelled_widening,
        lambda r: f"{r[0]} => {r[1]} -> {r[2]}: {r[3]} => {r[4]}",
    )

    if diff.respelled:
        print(
            f"\n  NOTE: {len(diff.respelled)} published MIM: subject(s) change spelling."
        )
        print(
            "  Record them in MediaIngredientMech/mappings/mim_curie_aliases.tsv so a"
        )
        print("  consumer holding the old subject can still resolve it.")


def _diff_payload(diff: SssomDiff) -> dict:
    """The full diff, for the audit log and the dry-run report."""
    return {
        "same_key_and_predicate": diff.same_key_and_predicate,
        "column_changes": diff.column_changes,
        "collapsed_prev": diff.collapsed_prev,
        "collapsed_new": diff.collapsed_new,
        "added": [list(r) for r in diff.added],
        "removed": [list(r) for r in diff.removed],
        "respelled": [list(r) for r in diff.respelled],
        "flipped": [list(r) for r in diff.flipped],
        "widening_flipped": [list(r) for r in diff.widening_flips],
        "respelled_widening": [list(r) for r in diff.respelled_widening],
    }


def _write_diff_report(diff: SssomDiff, path: Path = DIFF_REPORT) -> Path:
    """Write atomically (temp file + rename), not in place.

    This used to only back the scratch DIFF_REPORT (overwritten every run,
    low stakes if truncated by an interrupted write). It also now backs
    diff_archive -- a promotion's permanent audit record, referenced by the
    audit log's `diff_file` pointer -- where a crash mid-write would leave a
    truncated, undetectably-corrupt file with an audit-log entry pointing at
    it (CLAUDE.md: "Use atomic creation/replacement for locks and curated
    data").
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Randomized suffix + try/finally cleanup, matching
    # kg_microbe_history/scaffold.py::write_record()'s existing convention --
    # a fixed ".tmp" name collides when two invocations overlap (this runs
    # unconditionally on every --dry-run too, which never takes the
    # mediaingredientmech lock, so two concurrent dry-runs racing on the
    # shared DIFF_REPORT path is a real scenario, not a hypothetical one).
    tmp = path.with_name(path.name + f".tmp-{secrets.token_hex(4)}")
    try:
        tmp.write_text(json.dumps(_diff_payload(diff), indent=2) + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _validate(path: Path) -> list[str]:
    try:
        proc = subprocess.run(
            [SSSOM_BIN, "validate",
             "-V", "JsonSchema",
             "-V", "PrefixMapCompleteness",
             "-V", "StrictCurieFormat",
             str(path)],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        return ["sssom CLI not on PATH"]
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    markers = ("is not well-formed", "is not a valid URI or CURIE", "must be supplied")
    return [ln.strip() for ln in combined.splitlines() if any(m in ln for m in markers)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write the published file")
    ap.add_argument("--dry-run", action="store_true", help="(default) print what would happen")
    ap.add_argument("--allow-drop", type=int, default=ROW_COUNT_DROP_LIMIT,
                    help="Max number of rows the new file may genuinely remove vs the "
                         "published file. Subject re-spellings do not count against it. "
                         "Default: %(default)s. Set explicitly (with justification) "
                         "when intentionally consolidating records.")
    ap.add_argument("--allow-widening-flips", type=int, default=0,
                    help="Max number of rows the new file may flip FROM skos:exactMatch "
                         "to a weaker predicate -- counting both a same-subject flip and "
                         "a downgrade riding along with a subject re-spelling (the two "
                         "otherwise-invisible ways this can happen). Flips that tighten a "
                         "mapping TO exactMatch do not count. Default: %(default)s -- this "
                         "should always be a deliberate curation decision, not rebuild "
                         "noise (MediaIngredientMech#409). Set explicitly (with "
                         "justification) when intentionally relaxing a mapping.")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    if not WORKING_COPY.exists():
        print(f"Working copy missing: {WORKING_COPY}", file=sys.stderr)
        print("Run `just build-sssom` first.", file=sys.stderr)
        sys.exit(2)

    # Count rows the same way the diff does -- a line count and a csv parse
    # disagree on any quoted field carrying an embedded newline, and `comment`
    # is curator free text. One counter, so the banner and the guard can never
    # describe different things.
    prev_parsed = _read_rows(PUBLISHED)
    new_parsed = _read_rows(WORKING_COPY)
    new_rows, prev_rows = len(new_parsed), len(prev_parsed)
    new_hash = _sha256(WORKING_COPY)
    prev_hash = _sha256(PUBLISHED) if PUBLISHED.exists() else ""

    if prev_hash and prev_hash == new_hash:
        print(f"Published file already up to date (sha256={new_hash[:12]}). Nothing to do.")
        return

    print(f"Working copy: {WORKING_COPY} ({new_rows} rows, sha256={new_hash[:12]})")
    print(f"Published:    {PUBLISHED} ({prev_rows} rows, sha256={prev_hash[:12] or 'absent'})")
    print(f"Delta:        {new_rows - prev_rows:+d} rows")

    diff = diff_rows(prev_parsed, new_parsed)
    _print_diff(diff)
    report = _write_diff_report(diff)
    print(f"\n  Full diff (every entry, not just the {EXAMPLES_SHOWN} shown): {report}")

    if prev_rows and len(diff.removed) > args.allow_drop:
        print(
            f"\nRefusing to promote: {len(diff.removed)} rows would be removed "
            f"(limit: {args.allow_drop}).",
            file=sys.stderr,
        )
        if diff.respelled:
            print(
                f"  ({len(diff.respelled)} further published rows change only their "
                "subject spelling and are not counted here.)",
                file=sys.stderr,
            )
        print(
            "Adjudicate the removals listed above, or override with --allow-drop <N>.",
            file=sys.stderr,
        )
        sys.exit(2)

    if len(diff.all_widening) > args.allow_widening_flips:
        print(
            f"\nRefusing to promote: {len(diff.all_widening)} row(s) would flip from "
            f"skos:exactMatch to a weaker predicate (limit: {args.allow_widening_flips})"
            f", {len(diff.respelled_widening)} of them riding along with a respelling.",
            file=sys.stderr,
        )
        print(
            "Adjudicate the flips listed above, or override with "
            "--allow-widening-flips <N>.",
            file=sys.stderr,
        )
        sys.exit(2)

    print("\nRe-validating working copy before promotion...")
    errors = _validate(WORKING_COPY)
    if errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in errors[:20]:
            print(f"  - {e[:200]}", file=sys.stderr)
        sys.exit(2)
    print("  OK")

    if not apply:
        print("\n(dry-run) Would copy working copy to published path and log the promotion.")
        print("Pass --apply to perform the promotion.")
        return

    LockManager = _load_lock_manager()
    locker = LockManager({"locks_dir": str(LOCKS_DIR), "my_id": "publish_sssom"})
    if not locker.acquire_lock(
        "mediaingredientmech",
        operation="publish-sssom promotion",
        wait=True,
        max_wait=300,
    ):
        print("Could not acquire mediaingredientmech lock within 300s.", file=sys.stderr)
        sys.exit(2)

    try:
        PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
        # Atomic (temp file + rename), matching kg_microbe_history/scaffold.py
        # ::write_record()'s convention: PUBLISHED is the canonical curated
        # artifact CLAUDE.md's "atomic creation/replacement" rule names
        # directly, so it gets the same treatment as diff_archive below, not
        # a plain in-place write a crash or disk-full event could truncate.
        tmp_published = PUBLISHED.with_name(PUBLISHED.name + f".tmp-{secrets.token_hex(4)}")
        try:
            tmp_published.write_bytes(WORKING_COPY.read_bytes())
            os.replace(tmp_published, PUBLISHED)
        finally:
            tmp_published.unlink(missing_ok=True)
        published_hash = _sha256(PUBLISHED)

        try:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            # Full lists (not just the counts printed to stdout) go to a per-promotion
            # sibling file, not embedded in the JSONL line: a promotion that re-spells
            # every subject in a first publish or a full rebuild would write ~2,900
            # pairs as a single line, and nothing prunes or rotates AUDIT_LOG (#113).
            # A promotion that re-spells subjects is still the only record of which
            # old subjects stopped resolving, and the alias file is written from it --
            # so the full diff is archived, just not inline.
            #
            # Named on BOTH the previous and new hash, not just the new one: the
            # new hash alone collides on a revert-and-redo (MIM_ROOT rolled back
            # and re-promoted) or any deterministic rebuild reproducing an old
            # published state, silently overwriting an earlier promotion's
            # archived diff out from under its own audit-log `diff_file` pointer.
            # A (prev, new) pair can only repeat if the same transition happens
            # twice, in which case the diff content is identical anyway.
            diff_archive = (
                AUDIT_LOG.parent
                / f"sssom_diff_{(prev_hash[:12] or 'none')}_{published_hash[:12]}.json"
            )
            _write_diff_report(diff, diff_archive)
            entry = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "working_copy": str(WORKING_COPY),
                "published": str(PUBLISHED),
                "rows": new_rows,
                "prev_rows": prev_rows,
                "sha256": published_hash,
                "prev_sha256": prev_hash,
                "validators": ["JsonSchema", "PrefixMapCompleteness", "StrictCurieFormat"],
                "diff_file": str(diff_archive),
                "diff_counts": {
                    "added": len(diff.added),
                    "removed": len(diff.removed),
                    "respelled": len(diff.respelled),
                    "flipped": len(diff.flipped),
                    "widening_flipped": len(diff.widening_flips),
                    "respelled_widening": len(diff.respelled_widening),
                    "total_widening": len(diff.all_widening),
                },
            }
            with AUDIT_LOG.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            # PUBLISHED is already committed above -- this is a partial
            # failure, not a clean abort, and CLAUDE.md says not to swallow
            # that into an apparent success. Surface the sha256 so the
            # promotion can still be reconstructed/recorded by hand.
            #
            # diff_archive is written (and renamed into place) before the
            # AUDIT_LOG append -- if THAT later write is what failed, the
            # archive genuinely exists on disk with the full diff, and
            # claiming otherwise would send a curator's manual recovery down
            # the wrong path (assuming nothing to point the hand-written
            # audit line at, instead of just pointing it at the file that's
            # already there under the right (prev_hash, published_hash) name).
            archive_note = (
                f"diff_file={diff_archive} was written" if diff_archive.exists()
                else "no diff archive was written either"
            )
            print(
                f"\nPromoted → {PUBLISHED} (sha256={published_hash[:12]}) but FAILED to "
                f"write the audit-log entry ({exc}). {archive_note} -- record the "
                f"promotion manually (prev_sha256={prev_hash[:12] or 'absent'}) and "
                "investigate before the next promotion runs.",
                file=sys.stderr,
            )
            sys.exit(2)

        print(f"\nPromoted → {PUBLISHED}")
        print(f"Audit entry appended to {AUDIT_LOG}")
        print(f"Full diff archived to {diff_archive}")
    finally:
        locker.release_lock("mediaingredientmech")


if __name__ == "__main__":
    main()
