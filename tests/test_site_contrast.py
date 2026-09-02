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


def test_a_non_literal_token_is_reported_rather_than_crashing_or_skipped(tmp_path):
    """`--line: rgba(0,0,0,.12)` is real and shipped, so a rule that raises on a
    non-literal would be disabled the first time it met a live stylesheet.

    It must not be silently skipped either. This test previously asserted the
    silence -- that a non-literal produced no finding at all -- which is the
    behaviour #288 removed: a pairing named in the table and then skipped looks
    examined and is not.
    """
    light = {
        "--accent": "rgba(0,0,0,.5)",
        "--page": "#E4DED3",
        "--card": "#ffffff",
        "--fg": "#1a1d21",
    }

    findings = check_stylesheet(_stylesheet(tmp_path, light))

    assert {f.code for f in findings} == {"UNJUDGEABLE_VALUE"}
    assert all("--accent" in f.detail for f in findings)


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


def test_a_second_root_block_does_not_hide_the_palette(tmp_path):
    """AntibioticMech declares two bare :root rules -- the palette and a
    separate corpus-map colour set. Reading only the first match passed only
    because the palette happens to come first in that file; reversed, the check
    reported a clean stylesheet by reading a block with no palette in it.
    """
    palette = ":root { --accent: #96601F; --page: #E4DED3; --card: #ffffff; }\n"
    map_colours = ":root { --cls0: #3f7fbf; --cls1: #d1651a; }\n"

    first = tmp_path / "first.css"
    first.write_text(palette + map_colours, encoding="utf-8")
    second = tmp_path / "second.css"
    second.write_text(map_colours + palette, encoding="utf-8")

    assert len(check_stylesheet(first)) == 1
    assert len(check_stylesheet(second)) == 1, "source order changed the verdict"


def test_a_later_declaration_wins_as_it_does_in_a_browser(tmp_path):
    """Merged in document order, not first-match: a stylesheet that redefines a
    token further down is judged on the value that actually paints.
    """
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --accent: #96601F; --page: #E4DED3; --card: #ffffff; }\n"
        ":root { --page: #ffffff; }\n",
        encoding="utf-8",
    )

    assert check_stylesheet(path) == []


def test_a_colour_token_no_pairing_names_is_reported(tmp_path):
    """#288. The pairing table is hand-written, so it is only as complete as
    whoever last edited it -- and a token it never names is not judged, which
    reads exactly like a pass. AntibioticMech sets four tokens as `color:` that
    the original six pairings did not cover.
    """
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --accent: #245a8d; --page: #ffffff; --card: #ffffff;\n"
        "        --invented: #767676; }\n"
        ".thing { color: var(--invented); }\n",
        encoding="utf-8",
    )

    findings = check_stylesheet(path)

    assert [f.code for f in findings] == ["UNEXAMINED_FOREGROUND"]
    assert "--invented" in findings[0].detail


def test_a_token_the_table_names_is_not_reported_as_unexamined(tmp_path):
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --accent: #245a8d; --page: #ffffff; --card: #ffffff; }\n"
        "a { color: var(--accent); }\n",
        encoding="utf-8",
    )

    assert check_stylesheet(path) == []


def test_a_token_carrying_its_own_ground_is_judged_against_that_ground(tmp_path):
    """--warn is set beside `background: var(--warn-soft)` in every rule that
    uses it. Judging it against --page would report a failure on a surface it
    never sits on -- the mirror of the defect this module exists for, and a
    mistake I made by hand while reviewing AntibioticMech#147.
    """
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --accent: #245a8d; --page: #E4DED3; --card: #ffffff;\n"
        # 4.43:1 on --page, which would fail; 5.43:1 on --warn-soft, which is
        # where it is actually painted.
        "        --warn: #8a5a00; --warn-soft: #fdf4e3; }\n"
        ".pill.warn { background: var(--warn-soft); color: var(--warn); }\n",
        encoding="utf-8",
    )

    assert check_stylesheet(path) == []


def test_the_alias_spellings_are_judged_on_every_surface(tmp_path):
    """A Mech's token vocabulary is its own: CellStructureMech writes --ink
    where AntibioticMech writes --fg. A table naming only one spelling examines
    nothing on the other half of the fleet.

    --page and --card differ here on purpose. An earlier version of this test
    set both to white, so --ink passed on either and dropping the --ink/--page
    pairing changed nothing -- a fixture that erased the distinction it was
    asserting, which is #286 for the third time.
    """
    path = tmp_path / "style.css"
    path.write_text(
        # --ink clears AA on the white card (7.00) and fails on the mid-grey
        # ground (1.62), so the --page pairing is the only thing that sees it.
        ":root { --accent: #000000; --page: #7a7a7a; --card: #ffffff;\n"
        "        --ink: #595959; --bg: #ffffff; }\n"
        "body { color: var(--ink); }\n"
        ".btn { background: var(--accent); color: var(--bg); }\n",
        encoding="utf-8",
    )

    findings = check_stylesheet(path)

    assert [f.code for f in findings] == ["BELOW_AA"]
    assert "--ink" in findings[0].detail and "--page" in findings[0].detail


def test_a_token_that_aliases_another_is_followed(tmp_path):
    """CellStructureMech declares `--fg: var(--ink)`. A resolver reading only
    literals judged neither pairing and reported the stylesheet clean by
    examining nothing -- the silence this module exists to break.

    Asserts the specific finding rather than the whole list: a minimal palette
    trips other pairings too, and pinning the list would make this test about
    the fixture instead of about alias-following.
    """
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --ink: #767676; --fg: var(--ink);\n"
        "        --page: #ffffff; --card: #8a8a8a; --accent: #245a8d; }\n",
        encoding="utf-8",
    )

    details = [f.detail for f in check_stylesheet(path)]

    # #767676 on #8a8a8a is 1.34:1, reachable only by following --fg -> --ink.
    assert any("--fg #767676 on --card #8a8a8a" in d for d in details), details


def test_an_alias_cycle_terminates_instead_of_hanging(tmp_path):
    """A cycle must end. It cannot be judged, so it is reported as such rather
    than silently skipped."""
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --fg: var(--ink); --ink: var(--fg);\n"
        "        --page: #ffffff; --card: #ffffff; --accent: #245a8d; }\n",
        encoding="utf-8",
    )

    codes = {f.code for f in check_stylesheet(path)}

    assert codes == {"UNJUDGEABLE_VALUE"}


def test_a_declared_pairing_that_cannot_be_judged_says_so(tmp_path):
    """A pairing named in the table but skipped because a value is not a
    literal looks examined and is not. `rgb(23 32 42 / .94)` cannot be judged
    without the backdrop it is composited over (AntibioticMech#148)."""
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --accent: #245a8d; --page: #ffffff;\n"
        "        --card: rgb(23 32 42 / .94); }\n",
        encoding="utf-8",
    )

    codes = {f.code for f in check_stylesheet(path)}

    assert "UNJUDGEABLE_VALUE" in codes


def test_an_absent_token_is_not_reported_as_unjudgeable(tmp_path):
    """Absence differs from a value that cannot be read. A Mech that declares
    no --page has not failed to state one readably."""
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --accent: #245a8d; --card: #ffffff; }\n",
        encoding="utf-8",
    )

    assert check_stylesheet(path) == []


def test_the_page_ground_is_found_under_either_spelling(tmp_path):
    """CellStructureMech paints `body{background:var(--pastel-b)}` and declares
    no --page at all, so every page-ground pairing resolved to nothing there --
    and the stylesheet was reported clean without its body ground examined."""
    path = tmp_path / "style.css"
    path.write_text(
        ":root { --ink: #767676; --pastel-b: #8a8a8a;\n"
        "        --card: #ffffff; --accent: #245a8d; }\n",
        encoding="utf-8",
    )

    details = [f.detail for f in check_stylesheet(path)]

    assert any("--ink #767676 on --pastel-b #8a8a8a" in d for d in details), details
