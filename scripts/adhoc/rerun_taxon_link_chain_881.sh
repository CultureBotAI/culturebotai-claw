#!/usr/bin/env bash
# Re-run the taxon-link assessment's four scripts against the pinned Mech worktrees and diff the summaries.
# Purpose: regenerate the committed summaries under docs/reviews/2026-11-06-cross-mech-taxon-links/ after the
#   round-6 script corrections (culturebotai-claw#1067, #1068, #1069) at the Mech HEADs the document records,
#   so the diff shows what the corrections changed and nothing else.
# Inputs: claw's .env and ~/agent-work/culturebotai-claw/pin881/env.sh (written by pin_fleet_worktrees_881.py
#   --apply) already exported by the caller (set -a; . .env; . env.sh; set +a); $1 = output directory.
# Outputs: $1/{protein_example_taxa.tsv,summary_protein_example_taxa.md,taxon_curies.tsv,summary_all_curies.md,
#   outside_scope_classified.tsv,summary_classified.md,data_fixes_by_mech.md}, one .log per script, one .diff per
#   summary against the committed copy, and $1/digests.txt (SHA-256 of the TSVs).
# Serves: culturebotai-claw PR 881, review round 6. Written 2026-11-09.
set -euo pipefail
OUT=${1:?output directory}
case "${TAXONMECH_ROOT:-}" in
  */pin881-*) ;;
  *) echo "TAXONMECH_ROOT is not a pin881 worktree (${TAXONMECH_ROOT:-unset}); source pin881/env.sh first" >&2; exit 2 ;;
esac
cd "$(git rev-parse --show-toplevel)"
DOC=docs/reviews/2026-11-06-cross-mech-taxon-links
mkdir -p "$OUT"
uv run --quiet python scripts/adhoc/measure_protein_example_taxa_in_taxonmech.py --out "$OUT" > "$OUT/protein.log" 2> "$OUT/protein.err"
uv run --quiet python scripts/adhoc/measure_all_taxon_curies_in_taxonmech.py --out "$OUT" > "$OUT/curies.log"
uv run --quiet python scripts/adhoc/classify_taxa_outside_taxonmech_scope.py --measure "$OUT" --out "$OUT" > "$OUT/classify.log"
uv run --quiet python scripts/adhoc/report_taxon_data_fixes_by_mech.py --classified "$OUT/outside_scope_classified.tsv" \
  --curies "$OUT/taxon_curies.tsv" --examples "$OUT/protein_example_taxa.tsv" --out "$OUT" > "$OUT/fixes.log"
for f in summary_protein_example_taxa.md summary_all_curies.md summary_classified.md data_fixes_by_mech.md; do
  diff -u "$DOC/$f" "$OUT/$f" > "$OUT/$f.diff" && echo "$f: identical" || echo "$f: $(grep -c '^[-+][^-+]' "$OUT/$f.diff") changed lines"
done
shasum -a 256 "$OUT"/*.tsv | tee "$OUT/digests.txt"
