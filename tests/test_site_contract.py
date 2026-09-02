"""The site contract, checked rule by rule and against two real corpora.

Every rule here was measured on CommunityMech's and TraitMech's published pages
before it was written (see `kg_microbe_site.contract`), so the negative cases --
what must NOT be reported -- carry as much weight as the positive ones. Each of
them is a false positive an earlier draft actually produced.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_site import ASSET_TAGS, check_page, check_site, read_page
from kg_microbe_site.__main__ import main

PAGE = """<!doctype html>
<html lang="en"><head><title>A page</title></head>
<body><h1>One</h1><h2>Two</h2></body></html>
"""


def codes(findings) -> list[str]:
    return [finding.code for finding in findings]


def test_a_well_formed_page_reports_nothing():
    assert check_page(PAGE, "page.html") == []


# -- title and lang ---------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        '<html lang="en"><head></head><body><h1>x</h1></body></html>',
        '<html lang="en"><head><title></title></head><body><h1>x</h1></body></html>',
        '<html lang="en"><head><title>   </title></head><body><h1>x</h1></body></html>',
    ],
    ids=["absent", "empty", "whitespace"],
)
def test_a_title_that_says_nothing_is_a_missing_title(html):
    assert codes(check_page(html, "p.html")) == ["MISSING_TITLE"]


def test_lang_must_be_present_and_non_empty():
    assert "MISSING_LANG" in codes(check_page("<html><title>t</title></html>", "p.html"))
    assert "MISSING_LANG" in codes(
        check_page('<html lang=""><title>t</title></html>', "p.html")
    )


def test_title_text_split_by_markup_is_still_a_title():
    html = '<html lang="en"><title>A &amp; B</title></html>'
    assert read_page(html).title == "A & B"
    assert codes(check_page(html, "p.html")) == []


# -- images -----------------------------------------------------------------


def test_an_image_with_no_alt_attribute_is_reported():
    html = '<html lang="en"><title>t</title><img src="a.png"></html>'
    assert codes(check_page(html, "p.html")) == ["IMAGE_WITHOUT_ALT"]


def test_an_empty_alt_is_a_decision_and_is_accepted():
    # alt="" is the standard way to mark an image decorative. Treating it the
    # same as a missing alt would push authors to write noise for screen readers.
    html = '<html lang="en"><title>t</title><img src="a.png" alt=""></html>'
    assert codes(check_page(html, "p.html")) == []


def test_images_without_alt_are_counted_not_repeated():
    html = (
        '<html lang="en"><title>t</title>'
        '<img src="a.png"><img src="b.png"><img src="c.png" alt="c"></html>'
    )
    findings = check_page(html, "p.html")
    assert codes(findings) == ["IMAGE_WITHOUT_ALT"]
    assert "2 <img>" in findings[0].detail


# -- external assets --------------------------------------------------------


def test_a_script_from_a_cdn_is_an_external_asset():
    html = (
        '<html lang="en"><title>t</title>'
        '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script></html>'
    )
    findings = check_page(html, "p.html")
    assert codes(findings) == ["EXTERNAL_ASSET"]
    assert "cdn.jsdelivr.net" in findings[0].detail


def test_an_allowed_host_is_a_declared_dependency_not_a_finding():
    html = (
        '<html lang="en"><title>t</title>'
        '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script></html>'
    )
    assert check_page(html, "p.html", allowed_hosts=["cdn.jsdelivr.net"]) == []
    # Allowing one host does not allow another.
    other = html.replace("cdn.jsdelivr.net", "example.invalid")
    assert codes(check_page(other, "p.html", allowed_hosts=["cdn.jsdelivr.net"])) == [
        "EXTERNAL_ASSET"
    ]


def test_allowed_hosts_matching_ignores_case():
    html = '<html lang="en"><title>t</title><script src="https://CDN.Example/x.js"></script></html>'
    assert check_page(html, "p.html", allowed_hosts=["cdn.example"]) == []


def test_a_protocol_relative_asset_is_external():
    html = '<html lang="en"><title>t</title><script src="//cdn.example/x.js"></script></html>'
    findings = check_page(html, "p.html")
    assert codes(findings) == ["EXTERNAL_ASSET"]
    assert "cdn.example" in findings[0].detail


def test_a_link_to_another_site_is_not_an_external_asset():
    # The bug that made the first measurement wrong: 328 of 330 CommunityMech
    # pages were reported as loading external assets, and every one was an
    # ordinary content link. A page that links out does not depend on the
    # destination to render.
    html = (
        '<html lang="en"><title>t</title>'
        '<a href="https://example.org/paper">a paper</a></html>'
    )
    assert check_page(html, "p.html") == []


def test_a_canonical_link_is_metadata_not_an_asset():
    html = (
        '<html lang="en"><title>t</title>'
        '<link rel="canonical" href="https://example.org/p">'
        '<link rel="alternate" href="https://example.org/feed.xml"></html>'
    )
    assert check_page(html, "p.html") == []


def test_a_stylesheet_from_another_host_is_an_asset():
    html = (
        '<html lang="en"><title>t</title>'
        '<link rel="stylesheet" href="https://fonts.example/x.css"></html>'
    )
    assert codes(check_page(html, "p.html")) == ["EXTERNAL_ASSET"]


def test_asset_tags_does_not_claim_anchors():
    assert "a" not in ASSET_TAGS
    assert {"script", "img", "iframe", "link"} <= set(ASSET_TAGS)


# -- headings ---------------------------------------------------------------


def test_headings_must_start_at_h1():
    html = '<html lang="en"><title>t</title><h2>x</h2><h3>y</h3></html>'
    assert codes(check_page(html, "p.html")) == ["HEADING_DOES_NOT_START_AT_H1"]


def test_a_skipped_level_is_reported_once_per_page():
    html = '<html lang="en"><title>t</title><h1>a</h1><h3>b</h3><h1>c</h1><h4>d</h4></html>'
    assert codes(check_page(html, "p.html")) == ["HEADING_LEVEL_SKIPPED"]


def test_going_back_up_any_number_of_levels_is_fine():
    html = '<html lang="en"><title>t</title><h1>a</h1><h2>b</h2><h3>c</h3><h1>d</h1></html>'
    assert check_page(html, "p.html") == []


def test_a_page_with_no_headings_is_not_judged_on_headings():
    html = '<html lang="en"><title>t</title><p>prose</p></html>'
    assert check_page(html, "p.html") == []


# -- site-wide reference resolution -----------------------------------------


@pytest.fixture
def site(tmp_path: Path) -> Path:
    (tmp_path / "sub").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "x.js").write_text("")
    (tmp_path / "sub" / "index.html").write_text(PAGE)
    return tmp_path


def write(root: Path, name: str, body: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        f'<html lang="en"><head><title>t</title></head><body><h1>h</h1>{body}</body></html>'
    )


def test_a_reference_to_a_missing_file_is_broken(site: Path):
    write(site, "p.html", '<a href="gone.html">x</a>')
    findings = [f for f in check_site(site) if f.page == "p.html"]
    assert codes(findings) == ["BROKEN_REFERENCE"]
    assert "gone.html" in findings[0].detail


def test_a_reference_to_a_directory_resolves_through_its_index(site: Path):
    write(site, "p.html", '<a href="sub/">x</a><a href="sub">y</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []


def test_a_site_absolute_reference_resolves_against_the_site_root(site: Path):
    # Not against the filesystem root: resolving "/assets/x.js" with pathlib's
    # absolute-path rule looks outside the site entirely, and on a machine that
    # happens to have /assets it would wrongly pass. Not against the page's own
    # directory either -- which is why this page is in a subdirectory. With the
    # page at the site root the two are the same directory, and a mutation
    # replacing the root with the page's parent survived that version of this
    # test.
    write(site, "sub/p.html", '<script src="/assets/x.js"></script>')
    assert [f for f in check_site(site) if f.page == "sub/p.html"] == []
    write(site, "sub/q.html", '<script src="/assets/missing.js"></script>')
    assert codes([f for f in check_site(site) if f.page == "sub/q.html"]) == [
        "BROKEN_REFERENCE"
    ]


def test_a_reference_from_a_subdirectory_is_relative_to_that_page(site: Path):
    (site / "sub" / "deep.html").write_text(
        '<html lang="en"><title>t</title><h1>h</h1>'
        '<a href="index.html">near</a><a href="../assets/x.js">up</a></html>'
    )
    assert [f for f in check_site(site) if f.page == "sub/deep.html"] == []


@pytest.mark.parametrize(
    "reference",
    ["mailto:a@example.org", "tel:+100", "javascript:void(0)", "data:text/plain,x", "#top", ""],
)
def test_references_that_are_not_files_are_not_resolved(site: Path, reference: str):
    write(site, "p.html", f'<a href="{reference}">x</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []


def test_a_fragment_or_query_is_stripped_before_resolving(site: Path):
    write(site, "p.html", '<a href="sub/index.html#section">x</a><a href="sub/?q=1">y</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []


def test_an_external_reference_is_never_resolved_on_disk(site: Path):
    write(site, "p.html", '<a href="https://example.org/nothing/here">x</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []


def test_an_unrendered_template_expression_is_named_as_such(site: Path):
    # Reporting this as a broken link would be a lie: the reference is not
    # wrong, it was never rendered.
    write(site, "p.html", "<a href=\"{{ '/' | relative_url }}\">x</a>")
    findings = [f for f in check_site(site) if f.page == "p.html"]
    assert codes(findings) == ["UNRENDERED_TEMPLATE"]


def test_check_site_reports_pages_by_their_path_within_the_site(site: Path):
    (site / "sub" / "bad.html").write_text("<html><body><h2>x</h2></body></html>")
    pages = {f.page for f in check_site(site)}
    assert "sub/bad.html" in pages


def test_pages_may_be_supplied_explicitly(site: Path):
    write(site, "p.html", '<a href="gone.html">x</a>')
    write(site, "q.html", '<a href="also-gone.html">x</a>')
    findings = check_site(site, pages=[site / "p.html"])
    assert {f.page for f in findings} == {"p.html"}



# -- srcset (#239) ----------------------------------------------------------


def test_a_responsive_image_from_a_cdn_is_an_external_asset():
    """<picture><source srcset> is the standard responsive pattern, and before
    #239 it was invisible to every rule: srcset is a candidate list, not a
    single URL, so it could not be another ASSET_TAGS entry."""
    html = (
        '<html lang="en"><title>t</title><picture>'
        '<source srcset="https://cdn.example/x.webp 2x">'
        '<img src="x.png" alt="x"></picture></html>'
    )
    findings = check_page(html, "p.html")
    assert codes(findings) == ["EXTERNAL_ASSET"]
    assert "cdn.example" in findings[0].detail


def test_every_srcset_candidate_is_judged_not_only_the_first():
    html = (
        '<html lang="en"><title>t</title>'
        '<img alt="x" src="a.png" srcset="a.png 1x, https://cdn.one/b.png 2x, '
        'https://cdn.two/c.png 3x"></html>'
    )
    findings = check_page(html, "p.html")
    assert codes(findings) == ["EXTERNAL_ASSET", "EXTERNAL_ASSET"]
    assert {"cdn.one", "cdn.two"} == {
        f.detail.split("loads from ")[1].split(";")[0] for f in findings
    }


def test_a_srcset_descriptor_is_not_mistaken_for_a_url(site: Path):
    (site / "a.png").write_text("")
    write(site, "p.html", '<img alt="x" src="a.png" srcset="a.png 1x, a.png 640w">')
    assert [f for f in check_site(site) if f.page == "p.html"] == []


def test_a_srcset_candidate_that_does_not_exist_is_broken(site: Path):
    write(site, "p.html", '<img alt="x" src="assets/x.js" srcset="gone.png 2x">')
    findings = [f for f in check_site(site) if f.page == "p.html"]
    assert codes(findings) == ["BROKEN_REFERENCE"]
    assert "gone.png" in findings[0].detail


# -- case-exact resolution (#240) -------------------------------------------


def test_a_reference_whose_case_differs_is_broken_on_every_machine(site: Path):
    """The site is served from Linux. macOS resolves REAL.html to real.html, so
    asking the filesystem gives one verdict on a laptop and another in
    production -- #240, the machine-dependence #203 moved off the filesystem for
    a different check. This test would pass for the wrong reason on Linux and
    used to fail on macOS; now it passes for the same reason on both."""
    (site / "real.html").write_text(PAGE)
    write(site, "p.html", '<a href="REAL.html">x</a>')
    findings = [f for f in check_site(site) if f.page == "p.html"]
    assert codes(findings) == ["BROKEN_REFERENCE"]


def test_a_directory_whose_case_differs_is_broken(site: Path):
    write(site, "p.html", '<a href="SUB/">x</a>')
    assert codes([f for f in check_site(site) if f.page == "p.html"]) == [
        "BROKEN_REFERENCE"
    ]


def test_exact_case_still_resolves(site: Path):
    write(site, "p.html", '<a href="sub/index.html">x</a><script src="assets/x.js"></script>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []



def test_a_reference_that_walks_through_a_file_is_broken(site: Path):
    """`page.html/thing.html` treats a file as a directory. The walk asks that
    file for a listing and must report broken rather than raise."""
    (site / "real.html").write_text(PAGE)
    write(site, "p.html", '<a href="real.html/deeper.html">x</a>')
    assert codes([f for f in check_site(site) if f.page == "p.html"]) == [
        "BROKEN_REFERENCE"
    ]


def test_a_dot_component_is_normalised_away_before_matching(site: Path):
    """"./sub/./index.html" names the same file as "sub/index.html". PurePosixPath
    drops the "." components, so the walk never looks for a directory entry
    called "." -- which no listing would contain."""
    write(site, "p.html", '<a href="./sub/./index.html">x</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []
# -- percent-encoding and <base href> (#241) --------------------------------


def test_a_percent_encoded_reference_resolves_to_the_file_it_names(site: Path):
    """%20 is the correct way to write a space. Comparing the encoded form
    against a filesystem name called a working link broken."""
    (site / "a b.html").write_text(PAGE)
    write(site, "p.html", '<a href="a%20b.html">x</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []


def test_a_percent_encoded_reference_to_nothing_is_still_broken(site: Path):
    write(site, "p.html", '<a href="no%20such.html">x</a>')
    assert codes([f for f in check_site(site) if f.page == "p.html"]) == [
        "BROKEN_REFERENCE"
    ]


def test_base_href_redefines_what_relative_means(site: Path):
    """Ignoring <base> judges every relative reference on the page against the
    wrong directory."""
    write(site, "p.html", '<base href="sub/"><a href="index.html">x</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []
    # ...and the same reference without the base does not resolve.
    write(site, "q.html", '<a href="index.html">x</a>')
    assert codes([f for f in check_site(site) if f.page == "q.html"]) == [
        "BROKEN_REFERENCE"
    ]


def test_a_site_absolute_base_is_read_against_the_site_root(site: Path):
    (site / "sub" / "deep").mkdir()
    (site / "sub" / "deep" / "leaf.html").write_text(PAGE)
    write(site, "sub/p.html", '<base href="/sub/deep/"><a href="leaf.html">x</a>')
    assert [f for f in check_site(site) if f.page == "sub/p.html"] == []


@pytest.mark.parametrize(
    "base", ["https://example.org/x/", "//example.org/x/"], ids=["absolute", "protocol-relative"]
)
def test_an_external_base_makes_relative_references_not_ours(site: Path, base: str):
    """A page based at another origin has no relative reference to this site, so
    there is nothing local to resolve. The first version of this test named a
    file that happened to exist beside the page, so it passed while the code
    still resolved locally -- and a page whose neighbour was missing got a
    BROKEN_REFERENCE for a link that points at another host entirely."""
    write(site, "sub/p.html", f'<base href="{base}"><a href="nothing-here.html">x</a>')
    assert [f for f in check_site(site) if f.page == "sub/p.html"] == []


def test_a_base_without_a_trailing_slash_replaces_its_last_segment(site: Path):
    """`<base href="sub">` makes the document base `/sub`; a sibling reference
    resolves beside it, not inside it. Only `sub/` means "inside"."""
    (site / "beside.html").write_text(PAGE)
    write(site, "p.html", '<base href="sub"><a href="beside.html">x</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []

    write(site, "q.html", '<base href="sub"><a href="index.html">x</a>')
    assert codes([f for f in check_site(site) if f.page == "q.html"]) == [
        "BROKEN_REFERENCE"
    ]


def test_only_the_first_base_counts(site: Path):
    """Browsers ignore a second <base>, so honouring it would judge references
    against a directory no reader's browser uses."""
    write(site, "p.html", '<base href="sub/"><base href="assets/"><a href="index.html">x</a>')
    assert [f for f in check_site(site) if f.page == "p.html"] == []


def test_a_site_absolute_reference_ignores_the_base(site: Path):
    write(site, "sub/p.html", '<base href="/assets/"><script src="/assets/x.js"></script>')
    assert [f for f in check_site(site) if f.page == "sub/p.html"] == []


def test_a_reference_that_leaves_the_published_site_is_named_as_such(site: Path):
    """Neither resolved nor broken. What is served beyond the declared root is
    not this check's to know, and answering from the checkout would answer a
    different question -- whether a file exists here, not whether the site
    serves it."""
    (site.parent / "outside.html").write_text(PAGE)
    write(site, "sub/p.html", '<a href="../../outside.html">x</a>')
    findings = [f for f in check_site(site) if f.page == "sub/p.html"]
    assert codes(findings) == ["REFERENCE_OUTSIDE_SITE"]
    assert "climbs out" in findings[0].detail


def test_the_outside_verdict_is_falsy():
    """`check_site` distinguishes it by identity, but any caller treating the
    verdict as a boolean must not read "outside the site" as "resolves"."""
    from kg_microbe_site.contract import _OUTSIDE

    assert bool(_OUTSIDE) is False
    assert not _OUTSIDE


def test_a_published_root_wider_than_the_checked_pages_resolves_the_climb(site: Path):
    """TraitMech's shape: check pages/, serve the whole repository. Ten of its
    trait pages link ../../../app/discussions/, which is published but sits
    outside the directory being checked."""
    wider = site.parent
    (wider / "app").mkdir(exist_ok=True)
    (wider / "app" / "index.html").write_text(PAGE)
    write(site, "sub/p.html", '<a href="../../app/index.html">x</a>')

    assert codes([f for f in check_site(site) if f.page == "sub/p.html"]) == [
        "REFERENCE_OUTSIDE_SITE"
    ]
    assert [
        f for f in check_site(site, published_root=wider) if f.page == "sub/p.html"
    ] == []


def test_a_wider_published_root_still_reports_a_reference_to_nothing(site: Path):
    """Widening the root must not turn the check off."""
    write(site, "sub/q.html", '<a href="../../app/absent.html">x</a>')
    findings = [
        f for f in check_site(site, published_root=site.parent) if f.page == "sub/q.html"
    ]
    assert codes(findings) == ["BROKEN_REFERENCE"]


def test_a_site_absolute_reference_means_the_published_root(site: Path):
    wider = site.parent
    (wider / "top.html").write_text(PAGE)
    write(site, "sub/p.html", '<a href="/top.html">x</a>')
    assert [
        f for f in check_site(site, published_root=wider) if f.page == "sub/p.html"
    ] == []
    # Without the wider root, "/top.html" means the checked directory's own root.
    assert codes([f for f in check_site(site) if f.page == "sub/p.html"]) == [
        "BROKEN_REFERENCE"
    ]


def test_a_climb_out_of_a_wider_published_root_is_still_outside(site: Path):
    (site.parent.parent / "elsewhere.html").write_text(PAGE)
    write(site, "sub/p.html", '<a href="../../../elsewhere.html">x</a>')
    assert codes(
        [f for f in check_site(site, published_root=site.parent) if f.page == "sub/p.html"]
    ) == ["REFERENCE_OUTSIDE_SITE"]



# -- the manifest declaration and the CLI -----------------------------------


MANIFEST = load_fleet_manifest()
CLAW_ROOT = Path(__file__).resolve().parents[1]

_ENABLED = sorted(
    name
    for name, mech in MANIFEST.mechs.items()
    if (c := mech.capabilities.get("site_contract")) is not None and c.is_enabled
)


def test_every_mech_decides_about_the_site_contract():
    """Absence must be a declared decision with a reason, never an omission."""
    for name, mech in MANIFEST.mechs.items():
        capability = mech.capabilities.get("site_contract")
        assert capability is not None, f"{name} does not declare site_contract"
        if not capability.is_enabled:
            assert capability.reason.strip(), f"{name} disables it without a reason"


def test_the_measured_corpora_are_the_ones_declared():
    """The docstring's numbers come from these four: CommunityMech and
    TraitMech as measured for the contract, CellStructureMech measured on
    joining (10 pages, no findings; CellStructureMech#50), and AntibioticMech
    measured on joining (#279): 2,927 pages and one stylesheet, reporting three
    UNEXAMINED_FOREGROUND -- --masthead-nav, --masthead-nav-hover and
    --tooltip-fg, whose grounds are a gradient and a translucent fill that the
    contrast check declines to guess at (AntibioticMech#149).

    If a fifth is enabled the numbers stop describing what the check runs on
    until it is re-measured."""
    assert _ENABLED == [
        "antibioticmech",
        "cellstructuremech",
        "communitymech",
        "traitmech",
    ]


@pytest.mark.parametrize("mech", _ENABLED)
def test_a_declared_site_still_holds_to_the_contract(mech):
    """The measured baseline, kept. CommunityMech's three skipped heading levels
    are the whole of it; TraitMech is clean once its charting CDN is declared."""
    try:
        root = resolve_mech_root(mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a {mech} checkout: {exc}")

    capability = MANIFEST.mechs[mech].capabilities["site_contract"]
    site = root / capability.settings["site_path"]
    if not site.is_dir():
        pytest.skip(f"{mech} has no site at {site}")

    declared = capability.settings.get("published_root")
    findings = check_site(
        site,
        allowed_hosts=list(capability.settings.get("allowed_hosts", ())),
        published_root=(root / declared).resolve() if declared else None,
    )
    baseline = {
        "communitymech": {"HEADING_LEVEL_SKIPPED"},
        "traitmech": set(),
        "cellstructuremech": set(),
    }[mech]
    assert {f.code for f in findings} == baseline, [str(f) for f in findings[:5]]


def test_traitmech_needs_its_published_root_to_come_out_clean():
    """#238, on the corpus that motivated it. Ten trait pages link
    ../../../app/discussions/, which TraitMech publishes (Pages serves main at
    /) but which sits outside the pages/ directory being checked. Without the
    declaration they read as climbing out of the site; with it they resolve, and
    they resolve case-exactly rather than by asking the checkout."""
    try:
        root = resolve_mech_root("traitmech", claw_root=CLAW_ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a traitmech checkout: {exc}")
    site = root / "pages"
    if not site.is_dir():
        pytest.skip("traitmech has no pages/ here")

    hosts = ["cdn.jsdelivr.net"]
    without = check_site(site, allowed_hosts=hosts)
    assert {f.code for f in without} == {"REFERENCE_OUTSIDE_SITE"}
    assert len(without) == 10

    assert check_site(site, allowed_hosts=hosts, published_root=root) == []


def test_the_declared_published_root_is_the_one_traitmech_needs():
    """A ledger: if the manifest stops declaring it, the test above stops being
    about anything."""
    settings = MANIFEST.mechs["traitmech"].capabilities["site_contract"].settings
    assert settings["published_root"] == "."
    assert "published_root" not in (
        MANIFEST.mechs["communitymech"].capabilities["site_contract"].settings
    )


def test_an_undeclared_cdn_would_be_caught_on_a_real_corpus():
    """A gate that cannot fail is not a gate. TraitMech passes only because it
    declares cdn.jsdelivr.net; without that declaration its 353 trait pages are
    353 findings."""
    try:
        root = resolve_mech_root("traitmech", claw_root=CLAW_ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a traitmech checkout: {exc}")
    site = root / "pages"
    if not site.is_dir():
        pytest.skip("traitmech has no pages/ here")

    findings = check_site(site, published_root=root)
    assert {f.code for f in findings} == {"EXTERNAL_ASSET"}
    assert len(findings) > 300


def test_the_cli_reports_a_disabled_mech_and_succeeds(capsys):
    assert main(["check", "--mech", "culturemech"]) == 0
    assert "declares no site contract" in capsys.readouterr().out


def test_the_cli_fails_when_the_site_is_not_there(capsys, tmp_path):
    assert main(["check", "--mech", "traitmech", "--site", str(tmp_path / "no")]) == 2
    assert "no site at" in capsys.readouterr().err


def test_the_cli_returns_nonzero_on_a_finding(capsys, tmp_path):
    (tmp_path / "p.html").write_text("<html><body><h2>x</h2></body></html>")
    assert main(["check", "--mech", "traitmech", "--site", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "MISSING_TITLE" in captured.err
    assert "1 pages" in captured.out


def test_the_cli_returns_zero_on_a_clean_site(capsys, tmp_path):
    (tmp_path / "p.html").write_text(PAGE)
    assert main(["check", "--mech", "traitmech", "--site", str(tmp_path)]) == 0
    assert "clean" in capsys.readouterr().out


def test_the_cli_resolves_the_site_from_the_manifest_when_none_is_given(capsys):
    """Without --site the site_path in the manifest is what gets checked, so
    that CI and a local run judge the same directory."""
    try:
        resolve_mech_root("communitymech", claw_root=CLAW_ROOT)
    except MechRootError:
        pytest.skip("needs a communitymech checkout")
    main(["check", "--mech", "communitymech"])
    site = MANIFEST.mechs["communitymech"].capabilities["site_contract"].settings[
        "site_path"
    ]
    assert f"/{site}:" in capsys.readouterr().out


def test_the_cli_rejects_a_published_root_that_is_not_there(capsys, tmp_path, monkeypatch):
    """A typo in published_root would otherwise turn every reference on every
    page into REFERENCE_OUTSIDE_SITE -- nothing can be inside a directory that
    does not exist -- so a whole-site misconfiguration reads like a whole-site
    finding. It must fail loudly instead."""
    import dataclasses

    (tmp_path / "p.html").write_text(PAGE)
    mech = MANIFEST.mechs["traitmech"]
    capability = mech.capabilities["site_contract"]
    broken = dataclasses.replace(
        capability,
        settings=dict(capability.settings, published_root="no-such-directory"),
    )
    patched = dataclasses.replace(
        mech, capabilities=dict(mech.capabilities, site_contract=broken)
    )
    # FleetManifest is not a dataclass, and the CLI only reads `.mechs`.
    manifest = SimpleNamespace(mechs=dict(MANIFEST.mechs, traitmech=patched))
    monkeypatch.setattr(
        "kg_microbe_site.__main__.load_fleet_manifest", lambda *a, **k: manifest
    )
    monkeypatch.setattr(
        "kg_microbe_site.__main__.resolve_mech_root", lambda *a, **k: tmp_path
    )
    assert main(["check", "--mech", "traitmech", "--site", str(tmp_path)]) == 2
    assert "is not a directory" in capsys.readouterr().err


def test_the_cli_passes_the_declared_published_root_through(capsys):
    """The library semantics being right is not enough: the CLI is what CI runs.
    TraitMech comes out clean only if published_root reaches `check_site` AND is
    resolved against the repository rather than the site -- resolving "." against
    pages/ gives pages/ back, and the ten references still read as outside."""
    try:
        resolve_mech_root("traitmech", claw_root=CLAW_ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a traitmech checkout: {exc}")

    assert main(["check", "--mech", "traitmech"]) == 0
    captured = capsys.readouterr()
    assert "clean" in captured.out
    assert "REFERENCE_OUTSIDE_SITE" not in captured.err


def test_the_cli_checks_an_explicit_site_without_a_checkout(capsys, tmp_path, monkeypatch):
    """CI builds into a directory that is not in any checkout, so --site must
    work when the Mech root cannot be resolved. Only published_root loses its
    repository-relative meaning then, and it falls back to the site."""
    (tmp_path / "p.html").write_text(PAGE)
    monkeypatch.setattr(
        "kg_microbe_site.__main__.resolve_mech_root",
        lambda *a, **k: (_ for _ in ()).throw(MechRootError("no checkout")),
    )
    assert main(["check", "--mech", "traitmech", "--site", str(tmp_path)]) == 0
    assert "clean" in capsys.readouterr().out


def test_the_cli_fails_closed_when_the_checkout_cannot_be_resolved(capsys, monkeypatch):
    """Never fall back to the working directory: #147's contract."""
    for mech in MANIFEST.mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    monkeypatch.setattr(
        "kg_microbe_site.__main__.resolve_mech_root",
        lambda *a, **k: (_ for _ in ()).throw(MechRootError("no checkout")),
    )
    assert main(["check", "--mech", "communitymech"]) == 2
    assert "no checkout" in capsys.readouterr().err


def test_the_cli_walks_the_site_once(capsys, tmp_path, monkeypatch):
    """#242, the shape #231 hid in the corpus reader: a second traversal just to
    count what the first one already visited is invisible until the corpus is
    large, and then it is not."""
    (tmp_path / "p.html").write_text(PAGE)
    walks = {"n": 0}
    original = Path.rglob

    def counted(self, pattern):
        if pattern == "*.html":
            walks["n"] += 1
        return original(self, pattern)

    monkeypatch.setattr(Path, "rglob", counted)
    assert main(["check", "--mech", "traitmech", "--site", str(tmp_path)]) == 0
    assert walks["n"] == 1
    assert "1 pages" in capsys.readouterr().out


def test_a_host_hidden_in_userinfo_does_not_match_the_allowlist():
    """https://cdn.jsdelivr.net@evil.example/x.js is served by evil.example. The
    netloc keeps the userinfo, so it cannot equal an allowed host and the check
    fails closed -- but only by construction, so it is pinned here."""
    html = (
        '<html lang="en"><title>t</title>'
        '<script src="https://cdn.jsdelivr.net@evil.example/x.js"></script></html>'
    )
    findings = check_page(html, "p.html", allowed_hosts=["cdn.jsdelivr.net"])
    assert codes(findings) == ["EXTERNAL_ASSET"]
    assert "evil.example" in findings[0].detail
