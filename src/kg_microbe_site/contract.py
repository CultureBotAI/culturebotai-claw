"""What a generated site must hold to, checked once for the fleet.

Phase 6 item 1 (#132), the half that is not page budgets (#229). The criterion
is that common site behaviour is "tested once centrally".

No Mech has an accessibility or asset check today, and there is no site shell to
consolidate -- so unlike the source catalogue or the graph auditor, there is no
existing implementation to generalize from. What made building this defensible
anyway is that CommunityMech and TraitMech both publish rendered pages that
are tracked in the repository, so every rule below was measured before it was
written.

Measured on CommunityMech's 330 published pages and TraitMech's 490:

    missing <title>                 0 and 0
    missing <html lang>             0 and 0
    images without alt              0 and 0
    broken internal references      0 and 0
    heading levels skipped          3 and 0
    external asset loads            0 and 353

Ten of TraitMech's references point outside its declared site_path, at pages
the repository publishes from elsewhere; they are resolved against the checkout
and happen to be right. #238 covers separating "the pages to check" from "the
root references resolve against", which TraitMech shows are not the same thing.

TraitMech's 353 are one `<script>` per trait page pulling a charting library
from cdn.jsdelivr.net. That is a real dependency on a third party to render a
published page, and `allowed_hosts` is how a repository says it is deliberate
rather than how the check is silenced.

Two things this deliberately does not try to do.

Parse with regexes. The first measurement did, and reported 328 of 330
CommunityMech pages as loading external assets. They were `<a href>` links in
page content -- normal, and nothing to do with what a page depends on to render.
A rule built on that measurement would have been wrong about every page.

Check template sources. Point this at Jekyll input rather than built output and
it reports `schema.html` missing because the repository holds `schema.md`, and
`{{ '/' | relative_url }}` as a dangling reference. Neither is a defect; both
are the checker being run one step too early. Run it on built output. An
unrendered expression that survives into built output is reported as
UNRENDERED_TEMPLATE rather than as a broken link, because there the build, not
the reference, is what went wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse

__all__ = [
    "ASSET_TAGS",
    "LINK_ASSET_RELS",
    "Finding",
    "PageFacts",
    "check_page",
    "check_site",
    "read_page",
]

# Tags whose reference is fetched to render the page. `<a href>` is deliberately
# absent: linking out is what a link is for.
ASSET_TAGS = {
    "script": "src",
    "img": "src",
    "iframe": "src",
    "source": "src",
    "video": "src",
    "audio": "src",
    "embed": "src",
    "link": "href",
}

# `<link>` is the one asset tag that is usually not an asset. A stylesheet or an
# icon is fetched to render the page; rel="canonical" or rel="alternate" is a
# statement about the page that no browser fetches. Treating those as asset
# loads would report every page carrying a canonical URL as depending on a third
# party, which is the opposite of true.
LINK_ASSET_RELS = frozenset(
    {"stylesheet", "icon", "shortcut", "apple-touch-icon", "preload", "manifest"}
)

_NOT_A_FILE = ("mailto:", "data:", "javascript:", "tel:")

# Jinja, Liquid and ERB left in a reference. Reporting these as broken links
# would be a lie -- the reference is not wrong, it was never rendered -- and
# on a built site an unrendered expression is itself the defect worth naming.
_TEMPLATE_MARKERS = ("{{", "}}", "{%", "<%")


@dataclass(frozen=True)
class Finding:
    code: str
    page: str
    detail: str

    def __str__(self) -> str:
        return f"{self.page}: {self.code}: {self.detail}"


@dataclass
class PageFacts:
    """What one page says about itself."""

    title: str = ""
    lang: str = ""
    headings: list[int] = field(default_factory=list)
    assets: list[tuple[str, str]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    images_without_alt: int = 0


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.facts = PageFacts()
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if tag == "html":
            self.facts.lang = attributes.get("lang", "")
        elif tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.facts.headings.append(int(tag[1]))
        elif tag == "a":
            target = attributes.get("href", "")
            if target:
                self.facts.links.append(target)

        if tag in ASSET_TAGS and self._is_asset(tag, attributes):
            reference = attributes.get(ASSET_TAGS[tag], "")
            if reference:
                self.facts.assets.append((tag, reference))
        elif tag == "link":
            # Not an asset, but still a reference that can dangle.
            reference = attributes.get("href", "")
            if reference:
                self.facts.links.append(reference)

        if tag == "img" and "alt" not in attributes:
            # An empty alt is a decision -- "this image carries no meaning".
            # A missing one is silence, and a screen reader reads the filename.
            self.facts.images_without_alt += 1

    @staticmethod
    def _is_asset(tag: str, attributes: dict[str, str]) -> bool:
        if tag != "link":
            return True
        rels = attributes.get("rel", "").lower().split()
        return any(rel in LINK_ASSET_RELS for rel in rels)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.facts.title += data


def read_page(html: str) -> PageFacts:
    reader = _Reader()
    reader.feed(html)
    reader.close()
    return reader.facts


def _is_external(reference: str) -> bool:
    if reference.startswith("//"):
        return True
    return urlparse(reference).scheme in ("http", "https")


def _host(reference: str) -> str:
    if reference.startswith("//"):
        reference = "https:" + reference
    return urlparse(reference).netloc.lower()


def _check_facts(
    facts: PageFacts, page: str, allowed_hosts: Sequence[str]
) -> list[Finding]:
    findings: list[Finding] = []

    if not facts.title.strip():
        findings.append(
            Finding(
                "MISSING_TITLE",
                page,
                "no non-empty <title>; a browser tab, a bookmark and a search "
                "result all show it",
            )
        )
    if not facts.lang.strip():
        findings.append(
            Finding(
                "MISSING_LANG",
                page,
                "<html> has no lang attribute, so a screen reader must guess "
                "the pronunciation",
            )
        )
    if facts.images_without_alt:
        findings.append(
            Finding(
                "IMAGE_WITHOUT_ALT",
                page,
                f"{facts.images_without_alt} <img> without an alt attribute; "
                'alt="" is the way to say an image is decorative',
            )
        )

    allowed = {host.lower() for host in allowed_hosts}
    for tag, reference in facts.assets:
        if not _is_external(reference):
            continue
        host = _host(reference)
        if host not in allowed:
            findings.append(
                Finding(
                    "EXTERNAL_ASSET",
                    page,
                    f"<{tag}> loads from {host}; the page then depends on a "
                    f"third party to render",
                )
            )

    levels = facts.headings
    if levels:
        if levels[0] != 1:
            findings.append(
                Finding(
                    "HEADING_DOES_NOT_START_AT_H1",
                    page,
                    f"first heading is h{levels[0]}",
                )
            )
        for before, after in zip(levels, levels[1:]):
            if after - before > 1:
                findings.append(
                    Finding(
                        "HEADING_LEVEL_SKIPPED",
                        page,
                        f"h{before} is followed by h{after}, so anything "
                        f"navigating by heading loses a level",
                    )
                )
                break

    return findings


def check_page(
    html: str, page: str, *, allowed_hosts: Sequence[str] = ()
) -> list[Finding]:
    """Judge one page against the contract."""
    return _check_facts(read_page(html), page, allowed_hosts)


def _resolves(root: Path, page: Path, reference: str) -> bool:
    # A leading "/" is site-absolute, not filesystem-absolute. Resolving it
    # against the filesystem would look outside the site and, on a machine that
    # happens to have /assets, wrongly pass.
    base = root if reference.startswith("/") else page.parent
    target = (base / reference.lstrip("/")).resolve()
    if target.is_file():
        return True
    # A directory reference is served as its index.
    return (target / "index.html").is_file()


def check_site(
    root: Path,
    *,
    allowed_hosts: Sequence[str] = (),
    pages: Iterable[Path] | None = None,
) -> list[Finding]:
    """Judge every page, and resolve every internal reference.

    Reference resolution needs the whole site, which is why it lives here rather
    than in `check_page`: a page cannot know whether its neighbour exists.
    """
    root = Path(root)
    found = sorted(pages) if pages is not None else sorted(root.rglob("*.html"))
    findings: list[Finding] = []

    for path in found:
        name = path.relative_to(root).as_posix()
        html = path.read_text(encoding="utf-8", errors="replace")
        facts = read_page(html)
        findings.extend(_check_facts(facts, name, allowed_hosts))

        references = [reference for _, reference in facts.assets] + facts.links
        for reference in references:
            target = reference.split("#", 1)[0].split("?", 1)[0].strip()
            if not target or _is_external(target) or target.startswith(_NOT_A_FILE):
                continue
            if any(marker in target for marker in _TEMPLATE_MARKERS):
                findings.append(
                    Finding(
                        "UNRENDERED_TEMPLATE",
                        name,
                        f"{target!r} still carries a template expression, so "
                        f"this is a template rather than a built page",
                    )
                )
                continue
            if not _resolves(root, path, target):
                findings.append(
                    Finding(
                        "BROKEN_REFERENCE", name, f"{target!r} resolves to nothing"
                    )
                )

    return findings
