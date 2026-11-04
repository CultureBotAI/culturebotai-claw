"""The pages claw generates for Mech sites follow the fleet's theme contract (#668).

The discussion browser and the QC dashboard are published inside Mech sites. A
reader who chose dark there must get dark here, the choice must persist under
the fleet's ``mech-theme`` key, a Mech must be able to keep its palette and state
its licences, and nothing a caller passes may reach the page as markup.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from kg_microbe_browser.theme import (
    PALETTE_TOKENS,
    ThemeError,
    footer_html,
    validate_footer,
    validate_palette,
)
from kg_microbe_discussions import export
from kg_microbe_qc import generator
from kg_microbe_site.contrast import THEMES, _block, check_stylesheet

LIGHT, OS_DARK, CHOSEN_DARK = (pattern for _theme, pattern in THEMES)
HARNESS = Path(__file__).with_name("shared_html_theme_harness.cjs")
LICENCE_FOOTER = [
    ["Data: ", {"text": "CC BY 4.0", "href": "https://github.com/CultureBotAI/FixtureMech/blob/main/LICENSE-DATA"},
     "; code: ", {"text": "BSD-3-Clause", "href": "https://github.com/CultureBotAI/FixtureMech/blob/main/LICENSE-CODE"},
     ". Third-party material keeps its own terms."],
    ["Part of the ", {"text": "X-Mech Suite", "href": "https://culturebotai.github.io/mechs/"}, "."],
]


def _discussions(root: Path, **options) -> Path:
    out = root / "discussions"
    export.write_browser([], {"total_discussions": 0}, "FixtureMech", out, **options)
    return out / "index.html"


def _dashboard(root: Path, config_extra: dict | None = None, **options) -> Path:
    records = root / "records"
    records.mkdir(parents=True, exist_ok=True)
    (records / "one.yaml").write_text("name: one\n")
    config = root / "qc_config.yaml"
    config.write_text(yaml.safe_dump({
        "repo_name": "FixtureMech", "yaml_dir": str(records),
        "slots": [{"path": "name", "required": True, "threshold": 0.9}],
        **(config_extra or {}),
    }))
    out = root / "dashboard"
    generator.generate_dashboard(config_path=config, output_dir=out, **options)
    return out / "index.html"


PAGES = {"discussions": _discussions, "dashboard": _dashboard}
DEFAULTS = {"discussions": export.DEFAULT_PALETTE, "dashboard": generator.DEFAULT_PALETTE}

# Where each page paints text, so the dark contrast check examines the
# surfaces readers actually see rather than a generic list.
PAIRINGS = {
    "discussions": (
        ("--fg", "--page", "body text and facet labels"),
        ("--fg", "--card", "card heading, theme toggle"),
        ("--fg-soft", "--card", "rationale on a card"),
        ("--muted", "--page", "metrics, counts, facet headings, footer"),
        ("--muted", "--card", "source and evidence lines on a card"),
        ("--accent", "--page", "project and footer links"),
        ("--accent", "--card", "record and PMID links on a card"),
        ("--badge-fg", "--badge", "kind and status badges"),
        ("--gap-fg", "--gap", "knowledge-gap badge"),
    ),
    "dashboard": (
        ("--fg", "--page", "body text and table cells"),
        ("--fg", "--card", "stat values, table header, theme toggle"),
        ("--muted", "--page", "latest-curation line, required marker, footer"),
        ("--muted", "--card", "stat labels"),
        ("--accent", "--page", "project and footer links"),
        ("--pass", "--card", "FAIL-slot count of zero"),
        ("--fail", "--card", "FAIL-slot count"),
        ("--warn", "--card", "warning colour where it is set as text"),
        ("--pass-fg", "--pass-bg", "PASS badge"),
        ("--warn-fg", "--warn-bg", "WARN badge"),
        ("--fail-fg", "--fail-bg", "FAIL badge"),
    ),
}

# What each page drew before #668, read from its pre-#668 template. A page whose
# caller passes nothing must keep its light look; only the theme is new.
# (Cards were transparent on white, and the dashboard's links were Chrome's
# default blue.)
BEFORE_668 = {
    "discussions": {
        "--page": "#fff", "--card": "#fff", "--fg": "#1a1a1a", "--fg-soft": "#333",
        "--muted": "#666", "--line": "#e2e2e2", "--accent": "#2a6", "--focus": "#0969da",
        "--badge": "#eef", "--badge-fg": "#225", "--gap": "#fee", "--gap-fg": "#922",
    },
    "dashboard": {
        "--page": "#fff", "--card": "#f6f8fa", "--fg": "#222", "--muted": "#666",
        "--line": "#e5e7eb", "--accent": "#00e", "--focus": "#0969da",
        "--card-line": "#d0d7de", "--rule": "#ddd",
        "--pass": "#2c8a3a", "--warn": "#d68f00", "--fail": "#b8302c",
        "--pass-bg": "#dafbe1", "--pass-fg": "#1a7f37",
        "--warn-bg": "#fff8c5", "--warn-fg": "#9a6700",
        "--fail-bg": "#ffebe9", "--fail-fg": "#cf222e",
    },
}


def _tokens(text: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    light, os_dark, chosen_dark = (_block(text, pattern) for pattern in (LIGHT, OS_DARK, CHOSEN_DARK))
    assert light is not None and os_dark is not None and chosen_dark is not None
    return light, os_dark, chosen_dark


@pytest.mark.parametrize("page", PAGES)
def test_dark_values_are_declared_identically_for_the_os_and_a_saved_choice(tmp_path, page):
    text = PAGES[page](tmp_path).read_text()
    light, os_dark, chosen_dark = _tokens(text)

    assert os_dark == chosen_dark
    assert os_dark.keys() == light.keys()
    assert os_dark["--page"] != light["--page"] and os_dark["--fg"] != light["--fg"]
    # The OS block applies only while no light choice is saved.
    assert re.search(
        r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{', text
    )


@pytest.mark.parametrize("page", PAGES)
def test_a_saved_choice_is_read_before_the_page_is_styled(tmp_path, page):
    head = PAGES[page](tmp_path).read_text().split("</head>")[0]
    init = head.index('<script data-mech-theme="init">')
    assert init < head.index("<style>")
    assert 'localStorage.getItem("mech-theme")' in head[init:]


@pytest.mark.parametrize("page", PAGES)
def test_the_page_follows_a_saved_choice_and_the_toggle_persists_it(tmp_path, page):
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node is required to run the generated theme scripts")
    subprocess.run([node, str(HARNESS), str(PAGES[page](tmp_path))], check=True)


@pytest.mark.parametrize("page", PAGES)
def test_without_options_the_light_page_draws_what_it_drew_before(tmp_path, page):
    text = PAGES[page](tmp_path).read_text()
    assert _block(text, LIGHT) == BEFORE_668[page]
    assert "<footer" not in text


@pytest.mark.parametrize("page", PAGES)
def test_dark_text_meets_aa_where_it_is_painted(tmp_path, page):
    path = PAGES[page](tmp_path)
    findings = [
        finding for finding in check_stylesheet(path, pairings=PAIRINGS[page])
        if finding.theme != "light" and finding.code in {"BELOW_AA", "UNJUDGEABLE_VALUE"}
    ]
    assert findings == []
    # Both dark blocks must have been found, or the check above judged nothing.
    _tokens(path.read_text())
    # Every token the page sets as a text colour is one of the pairings above.
    painted = set(re.findall(r"(?<![\w-])color\s*:\s*var\(\s*(--[\w-]+)", path.read_text()))
    assert painted <= {foreground for foreground, _ground, _where in PAIRINGS[page]}


@pytest.mark.parametrize("page", PAGES)
def test_a_palette_reaches_light_and_both_dark_blocks(tmp_path, page):
    palette = {"light": {"accent": "#9d292d", "page": "#fafafa"}, "dark": {"accent": "#ffb3b5"}}
    light, os_dark, chosen_dark = _tokens(PAGES[page](tmp_path, palette=palette).read_text())

    assert (light["--accent"], light["--page"]) == ("#9d292d", "#fafafa")
    assert os_dark["--accent"] == chosen_dark["--accent"] == "#ffb3b5"
    # A theme the caller left out keeps the page's default.
    assert os_dark["--page"] == chosen_dark["--page"] == DEFAULTS[page]["dark"]["page"]


# The rule that paints each palette token, so a Mech's colour lands on the
# surface its name promises: "somewhere on the page" would be satisfied by a
# skip link while the page ground ignored the palette.
PAINTS = {
    "discussions": {
        "page": ("body", "background"), "fg": ("body", "color"), "card": (".card", "background"),
        "muted": (".metrics", "color"), "line": (".card", "border"), "accent": ("a", "color"),
    },
    "dashboard": {
        "page": ("body", "background"), "fg": ("body", "color"), "card": (".stat", "background"),
        "muted": (".meta", "color"), "line": ("th, td", "border-bottom"), "accent": ("a", "color"),
    },
}


@pytest.mark.parametrize("page", PAGES)
def test_each_palette_token_paints_the_surface_it_names(tmp_path, page):
    text = PAGES[page](tmp_path).read_text()
    assert set(PAINTS[page]) == set(PALETTE_TOKENS)
    for token, (selector, prop) in PAINTS[page].items():
        rules = " ".join(re.findall(rf"(?m)^\s*{re.escape(selector)} \{{([^}}]*)\}}", text))
        assert re.search(rf"(?<![\w-]){prop}\s*:[^;]*var\(--{token}\)", rules), (token, selector)


def test_the_same_footer_renders_identically_at_the_end_of_both_pages(tmp_path):
    expected = footer_html(LICENCE_FOOTER)
    for page in PAGES:
        text = PAGES[page](tmp_path / page, footer=LICENCE_FOOTER).read_text()
        assert text.count(expected) == 1
        assert text.index("</main>") < text.index(expected) < text.index("</body>")
    assert '<a href="https://culturebotai.github.io/mechs/">X-Mech Suite</a>' in expected


def test_footer_text_is_escaped_never_parsed():
    out = footer_html([["<script>alert(1)</script> & ",
                        {"text": "<b>CC BY 4.0</b>", "href": 'https://x.org/L?a=1&b="2"'}]])
    assert "<script>" not in out and "<b>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; " in out
    assert '<a href="https://x.org/L?a=1&amp;b=&quot;2&quot;">&lt;b&gt;CC BY 4.0&lt;/b&gt;</a>' in out


@pytest.mark.parametrize("href", [
    "javascript:alert(1)", "JavaScript:alert(1)", "java\tscript:alert(1)",
    " javascript:alert(1)", "javascript\n:alert(1)", "data:text/html,<p>x</p>",
    "vbscript:msgbox", "", "https://x.org/a b",
])
def test_footer_links_must_be_http_or_relative(href):
    with pytest.raises(ThemeError, match="is not an http"):
        validate_footer([{"text": "licence", "href": href}])


@pytest.mark.parametrize("href", [
    "https://github.com/CultureBotAI/FixtureMech/blob/main/LICENSE-DATA",
    "http://example.org/", "../../LICENSE", "/FixtureMech/", "#top",
])
def test_footer_links_may_be_http_or_relative(href):
    assert validate_footer([{"text": "licence", "href": href}]) != ()


@pytest.mark.parametrize("footer, message", [
    ("Data: CC BY 4.0", "must be a list"),
    ({"text": "x", "href": "https://x.org"}, "must be a list"),
    ([{"text": "x"}], "exactly 'text' and 'href'"),
    ([{"text": "x", "href": "https://x.org", "target": "_blank"}], "exactly 'text' and 'href'"),
    ([{"text": " ", "href": "https://x.org"}], "non-empty text"),
    ([[3.5]], "neither text nor a link"),
    ([7], "expected text, a link"),
])
def test_footer_refuses_shapes_it_cannot_render_as_text(footer, message):
    with pytest.raises(ThemeError, match=message):
        validate_footer(footer)


@pytest.mark.parametrize("palette, message", [
    ({"light": {"accent": "red; } body { display: none"}}, "not a #rgb"),
    ({"light": {"accent": "#fff</style><script>alert(1)</script>"}}, "not a #rgb"),
    ({"light": {"accent": "#ffff"}}, "not a #rgb"),
    ({"light": {"accent": 0x2A6}}, "not a #rgb"),
    ({"dark": {"accent": None}}, "quote it"),
    ({"light": {"badge": "#fff"}}, "unknown token 'badge'"),
    ({"sepia": {}}, "unknown theme 'sepia'"),
    (["#fff"], "must map"),
    ({"light": ["#fff"]}, "must map"),
])
def test_palette_refuses_anything_but_hex_palette_tokens(palette, message):
    with pytest.raises(ThemeError, match=message):
        validate_palette(palette)


@pytest.mark.parametrize("page", PAGES)
def test_an_invalid_option_writes_nothing(tmp_path, page):
    with pytest.raises(ThemeError):
        PAGES[page](tmp_path, palette={"light": {"accent": "red"}})
    with pytest.raises(ThemeError):
        PAGES[page](tmp_path, footer=[{"text": "x", "href": "javascript:alert(1)"}])
    assert not (tmp_path / page).exists()


def test_dashboard_reads_config_keys_and_arguments_replace_them(tmp_path):
    config = {"palette": {"light": {"accent": "#111111"}}, "footer": ["From the config"]}
    text = _dashboard(tmp_path / "config", config).read_text()
    assert _block(text, LIGHT)["--accent"] == "#111111" and "From the config" in text

    text = _dashboard(tmp_path / "args", config, palette={"light": {"accent": "#333333"}},
                      footer=["From an argument"]).read_text()
    assert _block(text, LIGHT)["--accent"] == "#333333"
    assert "From an argument" in text and "From the config" not in text


def test_discussion_cli_reads_config_keys_and_files_override_them(tmp_path):
    config = tmp_path / "conf" / "discussions_config.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump({
        "repo_name": "FixtureMech", "record_glob": "none/*.yaml",
        "palette": {"light": {"accent": "#111111"}}, "footer": ["From the config"],
    }))
    out = tmp_path / "out"
    assert export.main(["--config", str(config), "--output", str(out)]) == 0
    text = (out / "index.html").read_text()
    assert _block(text, LIGHT)["--accent"] == "#111111" and "From the config" in text

    palette = tmp_path / "palette.json"
    palette.write_text(json.dumps({"light": {"accent": "#333333"}}))
    footer = tmp_path / "footer.yaml"
    footer.write_text(yaml.safe_dump(["From a file"]))
    assert export.main(["--config", str(config), "--output", str(out),
                        "--palette", str(palette), "--footer", str(footer)]) == 0
    text = (out / "index.html").read_text()
    assert _block(text, LIGHT)["--accent"] == "#333333"
    assert "From a file" in text and "From the config" not in text


def test_qc_cli_files_override_the_config(tmp_path):
    _dashboard(tmp_path, {"footer": ["From the config"]})
    footer = tmp_path / "footer.yaml"
    footer.write_text(yaml.safe_dump(["From a file"]))
    out = tmp_path / "cli"
    assert generator.cli(["--config", str(tmp_path / "qc_config.yaml"), "--output", str(out),
                          "--footer", str(footer)]) == 0
    text = (out / "index.html").read_text()
    assert "From a file" in text and "From the config" not in text


def _bad_options(tmp_path: Path) -> list[tuple[list[str], str]]:
    bad = tmp_path / "bad.yaml"
    bad.write_text('light: {accent: "red"}\n')
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    return [
        (["--palette", str(bad)], "not a #rgb"),
        (["--palette", str(empty)], "the file is empty"),
        (["--footer", str(tmp_path / "missing.yaml")], "--footer"),
    ]


def test_discussion_cli_exits_nonzero_on_an_option_it_cannot_use(tmp_path, capsys):
    config = tmp_path / "discussions_config.yaml"
    config.write_text(yaml.safe_dump({"repo_name": "FixtureMech", "record_glob": "none/*.yaml",
                                      "footer": [{"text": "x", "href": "javascript:alert(1)"}]}))
    cases = [([], "is not an http"), *_bad_options(tmp_path)]
    for extra, message in cases:
        with pytest.raises(SystemExit) as exit_info:
            export.main(["--config", str(config), "--output", str(tmp_path / "out"), *extra])
        assert exit_info.value.code == 2
        assert message in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_qc_cli_exits_nonzero_on_an_option_it_cannot_use(tmp_path, capsys):
    _dashboard(tmp_path / "fixture", {"palette": {"dark": {"page": "#000000; color: red"}}},
               palette={})  # an argument replaces the config's invalid palette
    config = tmp_path / "fixture" / "qc_config.yaml"
    cases = [([], "not a #rgb"), *_bad_options(tmp_path)]
    for extra, message in cases:
        with pytest.raises(SystemExit) as exit_info:
            generator.cli(["--config", str(config), "--output", str(tmp_path / "out"), *extra])
        assert exit_info.value.code == 2
        assert message in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_discussion_page_keeps_what_traitmechs_shell_relies_on():
    """TraitMech's scripts/render_discussions_shell.py wraps this page and raises
    unless it finds one </head> and one project <nav>. Its stylesheet sets the
    page ground as --bg, and its vendored theme-toggle.js mounts nothing when a
    .theme-toggle exists, so the page must carry exactly one."""
    text = export.render_index()
    assert text.count("</head>") == 1
    assert text.count('<nav aria-label="Project navigation">') == 1
    assert text.count('class="theme-toggle"') == 1
    for selector in ("body", ".skip-link"):
        rule = re.search(rf"(?m)^\s*{re.escape(selector)} \{{([^}}]*)\}}", text)
        assert rule and "background: var(--bg, var(--page))" in rule.group(1)


def test_a_template_missing_a_slot_is_refused(tmp_path, monkeypatch):
    template = tmp_path / "index.html"
    template.write_text(export._TEMPLATE.read_text().replace("<!--slot:footer-->", ""))
    monkeypatch.setattr(export, "_TEMPLATE", template)
    with pytest.raises(RuntimeError, match="slot"):
        export.render_index()
