#!/usr/bin/env bash
# Single fleet-wide enforcer for the vendored byte-identical id-label files.
#
# This replaces two overlapping checks that used to live in different repos:
#
#   * CultureMech's scripts/audit_vendored_fleet.sh  — "the four Mechs agree with
#     the hub" (retired in favour of this).
#   * claw's `matches-hub` job                        — "claw's mirror agrees with
#     the hub" (folded in below).
#
# Both directions are now asserted in one place, so there is one thing to read
# when drift is reported and one thing to fix when the file set changes.
#
# TOPOLOGY IS UNCHANGED. CultureMech is still the hub and claw's shared/idlabel/
# is still a passive mirror of it (claw#19, restated in claw#22). Moving the
# *audit* into claw does not make claw canonical — it compares everything against
# CultureMech@main exactly as before. Do not read this as reviving claw#21, which
# framed claw as the fleet's enforcer while leaving CultureMech's audit running;
# that was reverted as redundant. The difference here is that the old audit is
# actually retired, which is what claw#21's commit message incorrectly claimed.
#
# Dependency-free: bash + curl + cmp.
set -euo pipefail

ORG="${ORG:-CultureBotAI}"
HUB="${HUB:-CultureMech}"
REF="${REF:-main}"
REPOS=(CultureMech MediaIngredientMech CommunityMech TraitMech proteintraitsmech)
# Worst-case curl budget: (len(FILES)+len(MAPPED)) x (1 + non-hub repos) for
# direction 1, + len(FILES) for direction 2, + (1 + non-hub repos) for
# direction 4. At 5 FILES, 2 MAPPED, 4 non-hub repos, and 4 SPOKE_FILES,
# --max-time 10 each: (5+2)x5 + 5 + 4x5 = 60 calls, ~600s worst case against
# .github/workflows/id-label-canon.yaml's timeout-minutes: 15 (900s).
# Re-check this math before growing REPOS,
# FILES/MANIFEST, MAPPED, or SPOKE_MANIFEST further.

# claw's mirror lives here, and its MANIFEST is the single list of vendored
# files. Read it rather than restating it: a hardcoded copy would be a second
# list that can drift from the first, which is the exact defect this audit
# exists to catch (see claw#37).
MIRROR_ROOT="${MIRROR_ROOT:-shared/idlabel}"
MANIFEST="${MANIFEST:-${MIRROR_ROOT}/MANIFEST}"

if [ ! -s "$MANIFEST" ]; then
  echo "ERROR: manifest '$MANIFEST' is missing or empty — refusing to audit nothing." >&2
  exit 2
fi
# Same relative path in every Mech repo.
mapfile -t FILES < <(grep -vE '^\s*(#|$)' "$MANIFEST")
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "ERROR: manifest '$MANIFEST' lists no files." >&2
  exit 2
fi
# Same bytes, per-repo path src/<lowercased-repo>/<suffix>.
MAPPED=(
  schema/mech_shared.yaml
  schema/history.yaml
)
# Note the mirror carries the manifest set only — not mech_shared.yaml or
# history.yaml, which are schema modules rather than part of the id-label
# validator set.

lc() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
raw() { printf 'https://raw.githubusercontent.com/%s/%s/%s/%s' "$ORG" "$1" "$REF" "$2"; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail=0
checked=0

fetch_hub() { # path -> $tmp/hub
  if ! curl -fsSL --max-time 10 "$(raw "$HUB" "$1")" -o "$tmp/hub"; then
    echo "ERROR: hub ${HUB}@${REF} is missing $1"
    return 1
  fi
}

echo "Auditing against hub ${ORG}/${HUB}@${REF}"
echo

# --- direction 1: every Mech agrees with the hub -----------------------------
for f in "${FILES[@]}"; do
  fetch_hub "$f" || { fail=1; continue; }
  for r in "${REPOS[@]}"; do
    [ "$r" = "$HUB" ] && continue
    if ! curl -fsSL --max-time 10 "$(raw "$r" "$f")" -o "$tmp/r"; then
      echo "DRIFT: ${r} is missing ${f} (hub has it)"; fail=1; continue
    fi
    cmp -s "$tmp/hub" "$tmp/r" || { echo "DRIFT: ${r}:${f} differs from hub"; fail=1; }
    checked=$((checked + 1))
  done
done

for suf in "${MAPPED[@]}"; do
  hubf="src/$(lc "$HUB")/${suf}"
  fetch_hub "$hubf" || { fail=1; continue; }

  # history.yaml is also packaged by claw's local history CLI. It is an
  # operational mirror, not another authority, so include it in the same audit.
  if [ "$suf" = "schema/history.yaml" ]; then
    claw_history="${CLAW_HISTORY:-shared/history/history.yaml}"
    if [ ! -f "$claw_history" ]; then
      echo "DRIFT: claw history mirror is missing ${claw_history}"; fail=1
    else
      cmp -s "$tmp/hub" "$claw_history" || {
        echo "DRIFT: ${claw_history} differs from ${HUB}:${hubf}"; fail=1;
      }
      checked=$((checked + 1))
    fi
  fi

  for r in "${REPOS[@]}"; do
    [ "$r" = "$HUB" ] && continue
    rf="src/$(lc "$r")/${suf}"
    if ! curl -fsSL --max-time 10 "$(raw "$r" "$rf")" -o "$tmp/r"; then
      echo "DRIFT: ${r} is missing ${rf} (hub has it)"; fail=1; continue
    fi
    cmp -s "$tmp/hub" "$tmp/r" || { echo "DRIFT: ${r}:${rf} differs from hub"; fail=1; }
    checked=$((checked + 1))
  done
done

# --- direction 2: claw's mirror agrees with the hub --------------------------
# Reads the working tree, not the network: this runs inside claw, so the checkout
# under test is the thing that must be correct. Fetching claw from raw would
# check main rather than the branch a PR is proposing.
for f in "${FILES[@]}"; do
  local_path="${MIRROR_ROOT}/${f}"
  if [ ! -f "$local_path" ]; then
    echo "DRIFT: mirror is missing ${local_path}"; fail=1; continue
  fi
  fetch_hub "$f" || { fail=1; continue; }
  cmp -s "$tmp/hub" "$local_path" || { echo "DRIFT: ${local_path} differs from hub"; fail=1; }
  checked=$((checked + 1))
done

# --- direction 3: the mirror carries nothing the manifest does not list -------
# An unlisted file under the mirror is never audited and never vendored to the
# Mechs, so it looks canonical while being local-only.
#
# git ls-files, not find: only TRACKED files matter. Untracked local artifacts
# (__pycache__, editor droppings) are not drift and must not fail the fleet.
while IFS= read -r present; do
  rel="${present#"${MIRROR_ROOT}/"}"
  case "$rel" in MANIFEST|README.md) continue ;; esac
  listed=0
  for f in "${FILES[@]}"; do [ "$f" = "$rel" ] && { listed=1; break; }; done
  if [ "$listed" -eq 0 ]; then
    echo "UNLISTED: ${present} is not in ${MANIFEST} — it is audited by nothing and vendored nowhere"
    fail=1
  fi
done < <(git ls-files "$MIRROR_ROOT" 2>/dev/null | sort)

# --- direction 4: fleet-governance files agree with the hub ------------------
# CultureMech now governs check_vendored_sync.sh itself. Compare claw's passive
# mirror and every non-hub Mech directly to that canonical copy. This is the
# post-propagation gate for #90: companion PRs may be briefly staggered, but the
# fleet audit cannot go green until every copy has landed.
SPOKE_ROOT="${SPOKE_ROOT:-shared/spoke}"
SPOKE_MANIFEST="${SPOKE_MANIFEST:-${SPOKE_ROOT}/MANIFEST}"

if [ ! -s "$SPOKE_MANIFEST" ]; then
  echo "ERROR: spoke manifest '$SPOKE_MANIFEST' is missing or empty — refusing to audit nothing." >&2
  exit 2
fi
mapfile -t SPOKE_FILES < <(grep -vE '^\s*(#|$)' "$SPOKE_MANIFEST")
if [ "${#SPOKE_FILES[@]}" -eq 0 ]; then
  echo "ERROR: spoke manifest '$SPOKE_MANIFEST' lists no files." >&2
  exit 2
fi

for f in "${SPOKE_FILES[@]}"; do
  ref_path="${SPOKE_ROOT}/${f}"
  if [ ! -f "$ref_path" ]; then
    echo "DRIFT: spoke mirror is missing ${ref_path}"; fail=1; continue
  fi
  fetch_hub "$f" || { fail=1; continue; }
  cmp -s "$tmp/hub" "$ref_path" || {
    echo "DRIFT: ${ref_path} differs from hub"; fail=1;
  }
  checked=$((checked + 1))

  # claw consumes two governance artifacts itself. Keep those operational
  # copies byte-identical too; the timestamp test is Mech/schema-specific.
  case "$f" in
    tests/test_skill_frontmatter.py|prompts/backlog-loop-goal.md)
      if [ ! -f "$f" ]; then
        echo "DRIFT: claw operational copy is missing ${f}"; fail=1
      else
        cmp -s "$tmp/hub" "$f" || { echo "DRIFT: claw:${f} differs from hub"; fail=1; }
        checked=$((checked + 1))
      fi
      ;;
  esac

  for r in "${REPOS[@]}"; do
    [ "$r" = "$HUB" ] && continue
    if ! curl -fsSL --max-time 10 "$(raw "$r" "$f")" -o "$tmp/r"; then
      echo "DRIFT: ${r} is missing ${f} (hub has it)"; fail=1; continue
    fi
    cmp -s "$tmp/hub" "$tmp/r" || { echo "DRIFT: ${r}:${f} differs from hub"; fail=1; }
    checked=$((checked + 1))
  done
done

# An unlisted file under the spoke mirror is audited by nothing and vendored
# nowhere — same reasoning as direction 3.
while IFS= read -r present; do
  rel="${present#"${SPOKE_ROOT}/"}"
  case "$rel" in MANIFEST|README.md) continue ;; esac
  listed=0
  for f in "${SPOKE_FILES[@]}"; do [ "$f" = "$rel" ] && { listed=1; break; }; done
  if [ "$listed" -eq 0 ]; then
    echo "UNLISTED: ${present} is not in ${SPOKE_MANIFEST} — it is audited by nothing and vendored nowhere"
    fail=1
  fi
done < <(git ls-files "$SPOKE_ROOT" 2>/dev/null | sort)

echo
if [ "$fail" -eq 0 ]; then
  echo "OK: ${checked} comparisons agree — ${#REPOS[@]} Mech repos and claw's mirrors all match ${HUB}@${REF}"
else
  echo "Fleet drift detected."
  echo "Fix: sync the lagging copy from ${HUB}@${REF}, then bump that repo's"
  echo "scripts/.vendored_canon_ref (spokes) or re-vendor ${MIRROR_ROOT} (claw)."
  exit 1
fi
