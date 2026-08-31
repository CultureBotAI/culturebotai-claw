"""The contrast rule, exercised against palettes built to break it.

#249. Judging only the palettes that happen to ship is how this defect
survived: AntibioticMech's pairings were measured before merge and passed,
because they were measured against the card surface rather than the ground
`body` paints. A rule that has only ever seen the answer it expects has not
been tested (#216), so every branch here is driven by a constructed stylesheet.
"""

from __future__ import annotations

import pytest

from kg_microbe_site.contrast import (
    AA_NORMAL_TEXT,
    check_stylesheet,
    contrast_ratio,
    relative_luminance,
)

# The real one, kept as a fixture so the numbers in #249 stay checkable.
ANTIBIOTICMECH_LIGHT = {
    "--accent": "#96601F",
    "--page": "#E4DED3",
    "--card": "#ffffff",
    "--fg": "#1a1d21",
    "--muted": "#54606d",
}


def _stylesheet(tmp_path, light, *, dark=None, dark_toggle=None, name="style.css"):
    def block(selector, tokens):
        body = "".join(f"  {k}: {v};\n" for k, v in tokens.items())
        return f"{selector} {{\n{body}}}\n"

    css = block(":root", light)
    if dark is not None:
        inner = block(':root:not([data-theme="light"])', dark)
        css += "@media (prefers-color-scheme: dark) {\n" + inner + "}\n"
    if dark_toggle is not None:
        css += block(':root[data-theme="dark"]', dark_toggle)
    path = tmp_path / name
    path.write_text(css, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("foreground", "background", "expected"),
    [("#ffffff", "#000000", 21.0), ("#000000", "#ffffff", 21.0), ("#777777", "#777777", 1.0)],
)
def test_the_ratio_matches_known_constants(foreground, background, expected):
    """Anchors the arithmetic to values WCAG states, not to our own output."""
    assert contrast_ratio(foreground, background) == pytest.approx(expected, abs=0.01)


def test_three_and_six_digit_hex_agree():
    assert relative_luminance("#fff") == relative_luminance("#ffffff")


def test_the_shipped_failure_is_reproduced(tmp_path):
    """The number in #249, from the palette that produced it."""
    findings = check_stylesheet(_stylesheet(tmp_path, ANTIBIOTICMECH_LIGHT))

    assert [f.code for f in findings] == ["BELOW_AA"]
    assert "--accent #96601F on --page #E4DED3 is 3.93:1" in findings[0].detail
    assert findings[0].theme == "light"


def test_the_same_accent_passes_on_the_card_surface(tmp_path):
    """Why it was missed: measured against --card, this palette is fine.

    Pinning this makes the distinction the rule exists for explicit -- the
    accent is not simply too dark, it is too dark *for the ground body paints*.
    """
    passing = dict(ANTIBIOTICMECH_LIGHT, **{"--page": "#ffffff"})

    assert check_stylesheet(_stylesheet(tmp_path, passing)) == []
    assert contrast_ratio("#96601F", "#ffffff") == pytest.approx(5.26, abs=0.01)


def test_a_dark_block_inherits_tokens_it_does_not_redefine(tmp_path):
    """A dark block redefines only what changes. Reading it alone would report
    an inherited token as missing and judge nothing."""
    light = {"--accent": "#96601F", "--page": "#ffffff", "--card": "#ffffff"}
    # Redefines the ground to something the inherited accent cannot sit on.
    findings = check_stylesheet(
        _stylesheet(tmp_path, light, dark_toggle={"--page": "#7a6a3a"})
    )

    assert [f.theme for f in findings] == ["dark (data-theme)"]
    assert "--accent #96601F" in findings[0].detail


def test_a_theme_the_stylesheet_never_declares_is_not_a_failure(tmp_path):
    """A page that deliberately commits to one look is a decision, and
    reporting it would be noise that trains readers to ignore the check."""
    light = {"--accent": "#245a8d", "--page": "#ffffff", "--card": "#ffffff"}

    assert check_stylesheet(_stylesheet(tmp_path, light)) == []


def test_both_dark_declarations_are_judged_independently(tmp_path):
    """They are written twice by design. A token corrected in one and not the
    other themes correctly by toggle and incorrectly by OS preference."""
    light = {"--accent": "#245a8d", "--page": "#ffffff", "--card": "#ffffff"}
    # Each dark block redefines the whole surface set. An earlier version of
    # this fixture redefined only --accent and --page, so --card stayed #ffffff
    # and white-on-gold failed at 2.16:1 in the block meant to pass -- the rule
    # was right and the palette was careless, which is the defect in miniature.
    findings = check_stylesheet(
        _stylesheet(
            tmp_path,
            light,
            dark={"--accent": "#3a3a3a", "--page": "#222222", "--card": "#211e16"},
            dark_toggle={"--accent": "#d9a94a", "--page": "#222222", "--card": "#211e16"},
        )
    )

    themes = {f.theme for f in findings}
    assert "dark (prefers-color-scheme)" in themes
    assert "dark (data-theme)" not in themes


def test_a_non_literal_token_is_skipped_rather_than_crashing(tmp_path):
    """`--line: rgba(0,0,0,.12)` is real and shipped. A rule that raises on it
    would be disabled the first time it met a live stylesheet."""
    light = {
        "--accent": "rgba(0,0,0,.5)",
        "--page": "#E4DED3",
        "--card": "#ffffff",
        "--fg": "#1a1d21",
    }

    assert [f.detail for f in check_stylesheet(_stylesheet(tmp_path, light))] == []


def test_a_stylesheet_with_no_root_block_says_so(tmp_path):
    path = tmp_path / "style.css"
    path.write_text("body { color: #000; }\n", encoding="utf-8")

    assert [f.code for f in check_stylesheet(path)] == ["NO_TOKEN_BLOCK"]


def test_the_threshold_is_the_one_that_applies_to_body_text():
    """4.5 is AA for normal-size text. Link text and button labels are body
    text; the 3.0 allowance is for large text and non-text boundaries."""
    assert AA_NORMAL_TEXT == 4.5


def test_raising_the_threshold_finds_more(tmp_path):
    """The threshold is a parameter and is actually consulted -- a rule that
    ignored it would pass every assertion above."""
    palette = {"--accent": "#96601F", "--page": "#ffffff", "--card": "#ffffff"}
    path = _stylesheet(tmp_path, palette)

    assert check_stylesheet(path) == []
    assert check_stylesheet(path, minimum=7.0)  # AAA; 5.26 does not reach it
