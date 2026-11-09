"""Large built sites must not enumerate each directory for every record link."""

from collections import Counter
from pathlib import Path

import pytest

from kg_microbe_site import check_site


def write(root: Path, name: str, body: str = "") -> Path:
    page = root / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f'<html lang="en"><title>Page</title><h1>Page</h1>{body}</html>')
    return page


def test_directory_listings_are_shared_across_links_and_pages(tmp_path, monkeypatch):
    write(tmp_path, "records/index.html")
    write(tmp_path, "assets/viewer.js")
    links = (
        '<script src="/assets/viewer.js"></script>'
        + ''.join(f'<a href="/records/?id={i}#record">row</a>' for i in range(25))
        + '<a href="/records/INDEX.html">wrong case</a>'
    )
    pages = [write(tmp_path, f"browse-{i}.html", links) for i in range(3)]
    visits = Counter()
    original = Path.iterdir

    def counted(path):
        visits[path] += 1
        return original(path)

    monkeypatch.setattr(Path, "iterdir", counted)
    findings = check_site(tmp_path, pages=pages)
    assert [(f.page, f.code) for f in findings] == [
        (page.name, "BROKEN_REFERENCE") for page in pages
    ]
    assert visits == {
        tmp_path.resolve(): 1,
        (tmp_path / "assets").resolve(): 1,
        (tmp_path / "records").resolve(): 1,
    }


def test_each_check_sees_added_removed_and_renamed_index_files(tmp_path):
    page = write(tmp_path, "browse.html", '<a href="records/">records</a>')

    def codes():
        return [f.code for f in check_site(tmp_path, pages=[page])]

    assert codes() == ["BROKEN_REFERENCE"]
    index = write(tmp_path, "records/index.html")
    assert codes() == []
    index.unlink()
    assert codes() == ["BROKEN_REFERENCE"]
    write(tmp_path, "records/index.html")
    assert codes() == []
    renamed = index.rename(index.with_name("INDEX.html"))
    assert codes() == ["BROKEN_REFERENCE"]
    renamed.rename(index)
    assert codes() == []


@pytest.mark.parametrize("error", [PermissionError, FileNotFoundError, NotADirectoryError])
def test_failed_directory_listings_keep_every_finding_and_retry_next_check(
    tmp_path, monkeypatch, error
):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    page = write(tmp_path, "browse.html", '<a href="blocked/file.html">row</a>' * 3)
    visits = Counter()
    original = Path.iterdir

    def inaccessible(path):
        visits[path] += 1
        if path == blocked.resolve():
            raise error("unavailable directory")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", inaccessible)
    for invocation in (1, 2):
        findings = check_site(tmp_path, pages=[page])
        assert [f.code for f in findings] == ["BROKEN_REFERENCE"] * 3
        assert visits[blocked.resolve()] == invocation


def test_cached_listings_preserve_base_urls_and_symlink_boundaries(tmp_path):
    published = tmp_path / "public"
    pages = published / "pages"
    write(published, "records/index.html")
    write(tmp_path, "private/index.html")
    (published / "inside").symlink_to(published / "records", target_is_directory=True)
    (published / "outside").symlink_to(tmp_path / "private", target_is_directory=True)
    page = write(
        pages,
        "browse.html",
        '<base href="/inside/"><a href="index.html">relative</a>'
        '<a href="/inside/">absolute</a><a href="/outside/">outside</a>'
        '<a href="/inside/INDEX.html">wrong case</a>',
    )
    assert [f.code for f in check_site(pages, pages=[page], published_root=published)] == [
        "REFERENCE_OUTSIDE_SITE",
        "BROKEN_REFERENCE",
    ]
