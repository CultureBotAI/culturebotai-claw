#!/usr/bin/env bash
# Hub-side enforcement of the vendored id↔label files.
#
# claw holds the canonical copy (shared/idlabel/). This diffs each Mech's
# checkout against it and fails if any Mech has drifted. It runs in claw's CI,
# which checks out the (public) Mechs anonymously and claw itself — so no tokens
# are needed even though claw is private. This is the CI counterpart to the
# per-Mech local `check_vendored_sync.sh` (fast local feedback); together they
# cover local dev and CI.
#
# Usage: audit_idlabel_fleet.sh <canon_dir> <mech_root>...
#   canon_dir  = claw's shared/idlabel  (holds scripts/ + tests/)
#   mech_root  = a Mech checkout root   (holds scripts/ + tests/)
# A mech_root that does not exist is skipped with a notice (a checkout may have
# been unavailable), not treated as pass or fail.
set -euo pipefail

FILES=(
  scripts/validate_id_label_correspondence.py
  scripts/chem_formula.py
  tests/test_id_label_empty_adapter.py
  tests/test_id_label_unknown_prefix.py
  tests/test_id_label_plausibility.py
)

canon="${1:?usage: audit_idlabel_fleet.sh <canon_dir> <mech_root>...}"
shift
[ -d "$canon" ] || { echo "ERROR: canonical dir not found: $canon"; exit 2; }

fail=0
checked=0
for root in "$@"; do
  # Tolerate a nesting level (some checkouts place the repo one dir down).
  base="$root"
  if [ ! -d "$base/scripts" ] && [ -d "$base"/*/scripts ] 2>/dev/null; then
    base="$(dirname "$(echo "$base"/*/scripts)")"
  fi
  if [ ! -d "$base/scripts" ]; then
    echo "SKIP: $root — no scripts/ found (checkout unavailable?)"; continue
  fi
  checked=$((checked + 1))
  for f in "${FILES[@]}"; do
    if [ ! -f "$base/$f" ]; then
      echo "DRIFT: $root missing $f (claw has it)"; fail=1; continue
    fi
    if ! cmp -s "$canon/$f" "$base/$f"; then
      echo "DRIFT: $root:$f differs from claw canonical"; fail=1
    fi
  done
done

if [ "$checked" -eq 0 ]; then
  echo "ERROR: no Mech checkouts were available to audit"; exit 2
fi
if [ "$fail" -eq 0 ]; then
  echo "OK: all ${#FILES[@]} vendored files agree with claw canonical across $checked Mech(s)"
else
  echo ""
  echo "Fleet drift — sync the lagging Mech(s) from claw shared/idlabel/ and bump their .vendored_canon_ref."
  exit 1
fi
