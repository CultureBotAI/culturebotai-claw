"""Whether a stylesheet's own tokens meet WCAG AA where they actually meet.

#249. Every Mech sets links and buttons in a brand accent on a tinted pastel
page ground, and none of the first five reached 4.5:1 against that ground. The
finding is a year old in fleet terms and two Mechs have joined since; one of
them, AntibioticMech, repeated it exactly -- accent `#96601F` on page `#E4DED3`
is 3.93:1, with eighteen links on the landing rendered outside any card.

It was not carelessness. That palette's pairings *were* measured before merge,
against `--bg`, the white card surface, where the same accent scores 5.26:1.
The dark palettes were WCAG-validated too, and genuinely pass at 6--8:1. What
nobody measured was the accent against `--page`, which is the surface `body`
actually paints. A check run against the wrong surface returns green for the
same reason a guard that skips returns green: it never examined the thing that
matters.

So this asks the question against the surface each token is painted on, for
every theme a stylesheet declares -- light, `prefers-color-scheme: dark`, and
`[data-theme="dark"]` -- because a Mech's stylesheet declares its dark values
twice and an edit can reach one and not the other.

Contrast ratios follow WCAG 2.1: relative luminance with the sRGB transfer
curve, `(L1 + 0.05) / (L2 + 0.05)`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Normal-size body text. Link text and button labels are body text, which is
# why AA applies at 4.5 rather than the 3.0 allowed for large text. Borders and
# other non-text boundaries are a different (3.0) requirement and are not
# judged here -- a border that fails is a hairline, not an unreadable word.
AA_NORMAL_TEXT = 4.5

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")

# The pairings that describe where text is actually painted. Each is
# (foreground token, background token, what it describes).
PAIRINGS: tuple[tuple[str, str, str], ...] = (
    ("--accent", "--page", "link or button label on the page ground"),
    ("--accent", "--card", "link or button label on a card"),
    ("--fg", "--page", "body text on the page ground"),
    ("--fg", "--card", "body text on a card"),
    ("--muted", "--page", "secondary text on the page ground"),
    ("--muted", "--card", "secondary text on a card"),
    ("--card", "--accent", "label reversed out of an accent fill"),
    # Aliases. A Mech's token vocabulary is its own: CellStructureMech writes
    # --ink where AntibioticMech writes --fg, and AntibioticMech reverses --bg
    # rather than --card out of an accent fill. Naming both spellings is what
    # keeps the table from silently examining nothing on half the fleet.
    ("--ink", "--page", "body text on the page ground"),
    ("--ink", "--card", "body text on a card"),
    ("--bg", "--accent", "label reversed out of an accent fill"),
    # Tokens that carry their own ground. Each is set beside an explicit
    # background in every rule that uses it, so judging it against --page would
    # report a failure on a surface it never sits on -- the mirror of the
    # defect this module exists for (#288).
    ("--warn", "--warn-soft", "warning text on its own ground"),
    ("--danger", "--page", "error text on the page ground"),
    ("--danger", "--card", "error text on a card"),
    ("--tooltip-fg", "--tooltip-bg", "tooltip text on its own ground"),
)

# Foregrounds the table knows about, derived rather than restated.
_EXAMINED_FOREGROUNDS = frozenset(foreground for foreground, _bg, _why in PAIRINGS)

_COLOUR_DECLARATION = re.compile(r"(?<![\w-])color\s*:\s*var\(\s*(--[\w-]+)")

# Where a stylesheet states each theme. The dark values are declared twice by
# design -- once for the OS preference, once for the toggle -- so both are
# judged; a token corrected in one and not the other is a real defect that
# shows only to readers who reached the theme the other way.
THEMES: tuple[tuple[str, str], ...] = (
    ("light", r"(?m)^:root\s*\{"),
    ("dark (prefers-color-scheme)", r'(?m)^\s*:root:not\(\[data-theme="light"\]\)\s*\{'),
    ("dark (data-theme)", r'(?m)^:root\[data-theme="dark"\]\s*\{'),
)


@dataclass(frozen=True)
class ContrastFinding:
    code: str
    stylesheet: str
    theme: str
    detail: str

    def __str__(self) -> str:
        return f"{self.stylesheet}: {self.theme}: {self.code}: {self.detail}"


def relative_luminance(colour: str) -> float:
    """WCAG 2.1 relative luminance of an sRGB hex colour."""
    value = colour.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    channels = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _block(css: str, pattern: str) -> dict[str, str] | None:
    """The custom properties of *every* rule whose selector matches, merged.

    Merged in document order with the later declaration winning, which is what
    a browser does. Reading only the first match looks equivalent and is not:
    AntibioticMech declares two bare `:root` rules, the palette and a separate
    corpus-map colour set, and the check passed only because the palette
    happens to come first. Reversed, it would have reported a clean stylesheet
    by reading a block with no palette in it -- a false green produced by
    source order.

    Returns None when the theme is not declared at all, which is different from
    declaring it with no tokens: a stylesheet that commits to a single look is
    a decision, and reporting it as a failure would be noise.
    """
    merged: dict[str, str] = {}
    found = False
    for match in re.finditer(pattern, css):
        found = True
        end = css.find("}", match.end())
        if end == -1:
            continue
        merged.update(
            {k: v.strip() for k, v in _DECL.findall(css[match.end() : end])}
        )
    return merged if found else None


def resolve(tokens: dict[str, str], name: str, base: dict[str, str]) -> str | None:
    """A token's literal colour, falling back to the light block.

    A dark block redefines only what changes, so an unredefined token keeps its
    light value -- reading the dark block alone would report tokens as missing
    that are simply inherited.
    """
    value = tokens.get(name) or base.get(name)
    if value is None or not _HEX.match(value):
        return None
    return value


def check_stylesheet(
    path: Path,
    *,
    minimum: float = AA_NORMAL_TEXT,
    pairings: tuple[tuple[str, str, str], ...] = PAIRINGS,
) -> list[ContrastFinding]:
    """Every declared theme's text pairings, judged against `minimum`."""
    css = path.read_text(encoding="utf-8")
    light = _block(css, THEMES[0][1])
    if light is None:
        return [
            ContrastFinding(
                "NO_TOKEN_BLOCK", path.name, "light",
                "no bare :root block, so no palette could be read",
            )
        ]

    findings: list[ContrastFinding] = []

    # A token set as `color:` that no pairing names is not judged at all, and
    # silence reads exactly like a pass. The table is hand-written, so it can
    # only be as complete as whoever last edited it -- this reports the gap
    # rather than leaving it to be noticed (#288).
    unexamined = sorted(
        set(_COLOUR_DECLARATION.findall(css)) - _EXAMINED_FOREGROUNDS
    )
    findings.extend(
        ContrastFinding(
            "UNEXAMINED_FOREGROUND", path.name, "any",
            f"{token} is set as `color:` but no pairing says what it sits on, "
            f"so its contrast is never judged",
        )
        for token in unexamined
    )

    for theme, pattern in THEMES:
        tokens = light if theme == "light" else _block(css, pattern)
        if tokens is None:
            continue
        for fg_name, bg_name, description in pairings:
            fg = resolve(tokens, fg_name, light)
            bg = resolve(tokens, bg_name, light)
            if fg is None or bg is None:
                continue
            ratio = contrast_ratio(fg, bg)
            if ratio < minimum:
                findings.append(
                    ContrastFinding(
                        "BELOW_AA", path.name, theme,
                        f"{description}: {fg_name} {fg} on {bg_name} {bg} "
                        f"is {ratio:.2f}:1, below {minimum}:1",
                    )
                )
    return findings
