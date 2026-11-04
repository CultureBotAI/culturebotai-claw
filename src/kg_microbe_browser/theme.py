"""Theme and footer for the standalone pages claw renders for Mech sites.

The discussion browser and the QC dashboard are published inside Mech sites but
generated here, so they cannot lean on a Mech's stylesheet or its vendored
``theme-toggle.js``. Before #668 neither declared a dark theme or read the
fleet's ``mech-theme`` storage key, so a reader who chose dark on a Mech page
got a light page here, and neither page could state a licence.

This module is what both pages share:

* a page's colour tokens, emitted three times: light on ``:root``, and the dark
  values under both ``prefers-color-scheme: dark`` (readers who never chose)
  and ``:root[data-theme="dark"]`` (readers who did). Both dark blocks are
  written from one mapping, so they cannot drift the way hand-kept copies do;
* a head script that applies a saved choice before first paint, and a labelled
  toggle button that writes it, with the semantics of the fleet's vendored
  ``theme-toggle.js``. The button carries that script's ``theme-toggle``
  class, and the script mounts nothing when one exists, so a page that also
  loads it keeps one control rather than two;
* an optional caller palette, so a Mech keeps its identity, and an optional
  footer, typically the licence line and the X-Mech Suite link.

Palette and footer arrive from Mech configuration and are treated as data: a
colour must be a hex literal, a footer is text and links, and a link must be
http(s) or relative. Nothing a caller passes reaches the page as markup.

Importing it needs only the stdlib, because the discussion exporter runs where
PyYAML is the one dependency installed; `read_option` uses that PyYAML.
"""
from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

#: The storage key the fleet's vendored theme toggle reads and writes, and the
#: one the site-features guide names for a persisted theme.
STORAGE_KEY = "mech-theme"

#: The tokens a caller's palette may set: the surfaces and inks that carry a
#: Mech's identity. A page declares tokens of its own as well -- badge and
#: status colours -- which carry meaning rather than identity and stay the page's.
PALETTE_TOKENS = ("page", "card", "fg", "muted", "line", "accent")

# Every page's defaults must define these, because CHROME_CSS paints with them.
_REQUIRED_TOKENS = (*PALETTE_TOKENS, "focus")
_THEMES = ("light", "dark")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
# A browser drops tabs and newlines inside a URL and C0 controls or spaces
# around it, so "java\tscript:" is javascript:. Refusing them outright is
# simpler than tracking which Python release's urlsplit strips which.
_URL_UNSAFE = re.compile(r"[\x00-\x20\x7f]")
_LINK_SCHEMES = frozenset({"", "http", "https"})


class ThemeError(ValueError):
    """A palette or footer that cannot be rendered as data."""


@dataclass(frozen=True)
class Link:
    text: str
    href: str


FooterLine = tuple[str | Link, ...]


@dataclass(frozen=True)
class PageChrome:
    """What a page places, each part already safe to emit verbatim.

    ``head`` goes in ``<head>`` before any stylesheet, ``css`` first in the
    page's ``<style>``, ``toggle`` beside the project navigation and
    ``footer`` (empty without one) at the end of ``<body>``.
    """

    head: str
    css: str
    toggle: str
    footer: str


def validate_palette(value: object) -> dict[str, dict[str, str]]:
    """A caller's palette as ``{"light": {...}, "dark": {...}}``.

    ``None`` is no palette. Only `PALETTE_TOKENS` may be set, each to a
    ``#rgb`` or ``#rrggbb`` literal: anything else could close the style block,
    and a misspelt token would otherwise be dropped without a word. A theme the
    caller leaves out keeps the page's defaults -- a light accent is rarely
    readable on a dark ground -- so keeping an identity in dark means stating
    the dark values too.
    """
    if value is None:
        return {theme: {} for theme in _THEMES}
    if not isinstance(value, Mapping):
        raise ThemeError("palette must map 'light' and/or 'dark' to colour tokens")
    unknown = [key for key in value if key not in _THEMES]
    if unknown:
        raise ThemeError(f"palette: unknown theme {unknown[0]!r}; expected 'light' or 'dark'")
    palette: dict[str, dict[str, str]] = {}
    for theme in _THEMES:
        tokens = value.get(theme)
        if tokens is None:
            tokens = {}
        if not isinstance(tokens, Mapping):
            raise ThemeError(f"palette.{theme} must map token names to colours")
        for name, colour in tokens.items():
            if name not in PALETTE_TOKENS:
                raise ThemeError(
                    f"palette.{theme}: unknown token {name!r}; "
                    f"a palette may set {', '.join(PALETTE_TOKENS)}"
                )
            if not isinstance(colour, str) or not _HEX.fullmatch(colour):
                hint = " (quote it: in YAML an unquoted # starts a comment)" if colour is None else ""
                raise ThemeError(
                    f"palette.{theme}.{name}: {colour!r} is not a #rgb or #rrggbb colour{hint}"
                )
        palette[theme] = dict(tokens)
    return palette


def theme_css(defaults: Mapping[str, Mapping[str, str]], palette: object = None) -> str:
    """A page's token blocks: light on ``:root``, then the same dark values twice.

    Selectors start their line, which is where `kg_microbe_site.contrast`
    looks for them.
    """
    chosen = validate_palette(palette)
    light = {**defaults["light"], **chosen["light"]}
    dark = {**defaults["dark"], **chosen["dark"]}
    if light.keys() != dark.keys() or not set(_REQUIRED_TOKENS) <= light.keys():
        raise ValueError(
            "page defaults must name the same tokens in both themes, "
            f"including {', '.join(_REQUIRED_TOKENS)}"
        )

    def block(selector: str, scheme: str, tokens: Mapping[str, str], indent: str = "") -> str:
        lines = [f"{indent}{selector} {{", f"{indent}  color-scheme: {scheme};"]
        lines += [f"{indent}  --{name}: {value};" for name, value in tokens.items()]
        return "\n".join([*lines, f"{indent}}}"])

    return "\n".join([
        block(":root", "light", light),
        "@media (prefers-color-scheme: dark) {",
        block(':root:not([data-theme="light"])', "dark", dark, "  "),
        "}",
        block(':root[data-theme="dark"]', "dark", dark),
    ]) + "\n"


#: Placement and look of the toggle and footer, painted with the page's tokens.
#: The toggle sets no `display`, which would defeat its `hidden` attribute.
CHROME_CSS = """\
.topbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .5rem 1rem; }
.theme-toggle { font: inherit; font-size: .85rem; padding: .3rem .7rem; cursor: pointer;
  color: var(--fg); background: var(--card); border: 1px solid var(--line); border-radius: 6px; }
.theme-toggle[aria-pressed="true"] { border-color: var(--accent); }
.theme-toggle:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; }
.site-footer { color: var(--muted); font-size: .85rem; border-top: 1px solid var(--line); overflow-wrap: anywhere; }
.site-footer p { margin: .35rem 0; }
"""

_KEY = json.dumps(STORAGE_KEY)

# Synchronous and first in <head>, so the saved choice is on <html> before the
# body is parsed. Storage can be absent or throw (private windows, blocked site
# data); the page then follows the OS preference.
HEAD_HTML = f"""\
<script data-mech-theme="init">
(function () {{
  try {{
    var saved = localStorage.getItem({_KEY});
    if (saved === "dark" || saved === "light") document.documentElement.setAttribute("data-theme", saved);
  }} catch (error) {{}}
}})();
</script>
"""

# Hidden until this script runs, so without JavaScript there is no dead control
# and the page still follows the OS preference. aria-pressed reports whether
# the page is dark, chosen or inherited, as the vendored toggle does.
TOGGLE_HTML = f"""\
<button type="button" class="theme-toggle" aria-pressed="false" hidden>Dark theme</button>
<script data-mech-theme="toggle">
(function () {{
  var button = document.currentScript && document.currentScript.previousElementSibling;
  if (!button) return;
  var root = document.documentElement;
  var os = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function current() {{
    var chosen = root.getAttribute("data-theme");
    if (chosen === "dark" || chosen === "light") return chosen;
    return os && os.matches ? "dark" : "light";
  }}
  function show() {{ button.setAttribute("aria-pressed", current() === "dark" ? "true" : "false"); }}
  button.addEventListener("click", function () {{
    var next = current() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {{ localStorage.setItem({_KEY}, next); }} catch (error) {{}}
    show();
  }});
  if (os && os.addEventListener) os.addEventListener("change", show);
  show();
  button.hidden = false;
}})();
</script>
"""


def _safe_href(href: str) -> bool:
    if not href or _URL_UNSAFE.search(href):
        return False
    try:
        scheme = urlsplit(href).scheme
    except ValueError:
        return False
    return scheme.lower() in _LINK_SCHEMES


def _footer_part(part: object, number: int) -> str | Link:
    if isinstance(part, str):
        return part
    if isinstance(part, Mapping):
        if set(part) != {"text", "href"}:
            raise ThemeError(
                f"footer line {number}: a link has exactly 'text' and 'href', "
                f"not {sorted(map(str, part))}"
            )
        text, href = part["text"], part["href"]
        if not isinstance(text, str) or not text.strip():
            raise ThemeError(f"footer line {number}: link text must be non-empty text")
        if not isinstance(href, str) or not _safe_href(href):
            raise ThemeError(f"footer line {number}: {href!r} is not an http(s) or relative link")
        return Link(text, href)
    raise ThemeError(f"footer line {number}: {part!r} is neither text nor a link")


def validate_footer(value: object) -> tuple[FooterLine, ...]:
    """A caller's footer as lines of text and links; ``None`` is no footer.

    A footer is a list of lines. A line is a string, a link, or a list of
    strings and links, and a link is a mapping of exactly ``text`` and ``href``.
    Text is escaped, never parsed, and an href must be http(s) or relative: a
    ``javascript:`` licence link would run in every reader's page.
    """
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ThemeError("footer must be a list of lines")
    lines: list[FooterLine] = []
    for number, line in enumerate(value, 1):
        parts = [line] if isinstance(line, (str, Mapping)) else line
        if isinstance(parts, bytes) or not isinstance(parts, Sequence):
            raise ThemeError(f"footer line {number}: expected text, a link, or a list of them")
        lines.append(tuple(_footer_part(part, number) for part in parts))
    return tuple(lines)


def footer_html(footer: object) -> str:
    """The footer element, or "" when the caller gave no lines."""
    lines = validate_footer(footer)
    if not lines:
        return ""

    def render(part: str | Link) -> str:
        if isinstance(part, Link):
            return f'<a href="{html.escape(part.href)}">{html.escape(part.text)}</a>'
        return html.escape(part)

    body = "".join("  <p>" + "".join(map(render, line)) + "</p>\n" for line in lines)
    return f'<footer class="site-footer">\n{body}</footer>\n'


def page_chrome(
    defaults: Mapping[str, Mapping[str, str]],
    *,
    palette: object = None,
    footer: object = None,
) -> PageChrome:
    """Everything a page needs for #668, validated before anything is written."""
    return PageChrome(
        head=HEAD_HTML,
        css=theme_css(defaults, palette) + CHROME_CSS,
        toggle=TOGGLE_HTML,
        footer=footer_html(footer),
    )


def read_option(flag: str, path: Path | None, default: object = None) -> object:
    """A ``--palette`` or ``--footer`` file's value, or `default` without one.

    The file is YAML, which reads JSON too, and holds what the config key
    would. An unreadable or empty file is an error rather than a quiet fall
    back to the config: the caller named it in order to override.
    """
    import yaml  # see the module docstring; every caller already has it

    if path is None:
        return default
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ThemeError(f"{flag} {path}: {error}") from error
    if value is None:
        raise ThemeError(f"{flag} {path}: the file is empty")
    return value
