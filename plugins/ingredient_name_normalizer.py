"""
Ingredient name normalization for cross-repo matching.

Canonicalizes hydrate-separator notation so surface forms like `MnCl2·4H2O`,
`MnCl2 x 4 H2O`, `MnCl2・4H2O`, and `MnCl2 . 4H2O` all normalize to the same
string. Does NOT strip the hydrate — anhydrous `MnCl2` stays distinct from
`MnCl2·4H2O`, because they have different CHEBI identities.
"""

import re
import unicodedata

# Unicode middle-dot family: U+00B7, U+30FB, U+22C5, U+2219 — all mean "·"
# in chemical formula context. Also handle ASCII-separator spellings.
_CANONICAL_DOT = "·"

# Matches <formula><separator><count>H2O where separator is any of:
#   ·  ・  ⋅  ∙   (Unicode middle dots)
#   x  X  ×       (times, with optional surrounding whitespace)
#   .             (period, with optional surrounding whitespace)
# and <count> is an optional digit run (defaults to implicit "1H2O").
_HYDRATE_RE = re.compile(
    r"""
    (?P<pre>\S)              # character right before the separator
    \s*
    (?P<sep>[·・⋅∙]|[xX×]|\.) # separator variants
    \s*
    (?P<count>\d*)           # optional digit count (e.g. "4" in "4H2O")
    \s*
    h2o                      # the water marker (lowercased)
    \b
    """,
    re.VERBOSE,
)


def canonicalize_hydrate(name: str) -> str:
    """Normalize a chemical name for matching: lowercase, collapse whitespace,
    canonicalize hydrate-notation separators.

    `MnCl2·4H2O`, `MnCl2 x 4 H2O`, `MnCl2・4H2O`, `MnCl2 . 4H2O`,
    `MnCl2·4 H2O` → `mncl2·4h2o`.

    `MnCl2` (anhydrous) → `mncl2` (not conflated with hydrated forms).
    """
    s = unicodedata.normalize("NFKC", name).lower().strip()
    s = re.sub(r"\s+", " ", s)

    def _repl(m: re.Match) -> str:
        pre = m.group("pre")
        count = m.group("count") or ""
        return f"{pre}{_CANONICAL_DOT}{count}h2o"

    s = _HYDRATE_RE.sub(_repl, s)
    return s
