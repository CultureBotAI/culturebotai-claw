"""The cache fetcher adds only what the gate needs, and only what it can verify (#729).

Offline: every request goes to an injected transport that answers from
constructed PubMed XML, so identity, overwrite and failure rules are exercised
without NCBI.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import urllib.parse
from types import SimpleNamespace

import pytest

from kg_microbe_evidence import (
    EvidenceConfig,
    EvidenceValidator,
    cache_file_name,
    validate_corpus,
)
from kg_microbe_evidence import fetch as fetcher

TODAY = dt.date(2026, 11, 3)


def article(pmid, abstract="Growth increased under iron.", doi=None, label=None, cited_doi=None):
    text = f'<AbstractText Label="{label}">{abstract}</AbstractText>' if label else f"<AbstractText>{abstract}</AbstractText>"
    body = f"<Abstract>{text}</Abstract>" if abstract else ""
    location = f'<ELocationID EIdType="doi">{doi}</ELocationID>' if doi else ""
    # A record's reference list carries the DOIs of the papers it cites.
    references = (f'<ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">{cited_doi}'
                  f"</ArticleId></ArticleIdList></Reference></ReferenceList>") if cited_doi else ""
    return (f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>"
            f"<Journal><Title>J</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>"
            f"<ArticleTitle>Title {pmid}</ArticleTitle>{location}{body}"
            f"<AuthorList><Author><LastName>Doe</LastName><Initials>J</Initials></Author></AuthorList>"
            f"</Article></MedlineCitation><PubmedData>{references}</PubmedData></PubmedArticle>")


class FakeNCBI:
    """Answers efetch from `articles` and esearch from `search`; records every call."""

    def __init__(self, articles=(), search=None, fail=0):
        self.articles = {a.split("<PMID>")[1].split("</PMID>")[0]: a for a in articles}
        self.search = search or {}
        self.fail = fail
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        if self.fail:
            self.fail -= 1
            raise OSError("connection reset")
        if url == fetcher.ESEARCH:
            doi = params["term"].split('"')[1]
            ids = self.search.get(doi, [])[: int(params["retmax"])]  # PubMed honours retmax
            return json.dumps({"esearchresult": {"idlist": ids}}).encode()
        ids = params["id"].split(",")
        found = "".join(self.articles[i] for i in ids if i in self.articles)
        return f"<PubmedArticleSet>{found}</PubmedArticleSet>".encode()


CONFIG = EvidenceConfig.from_settings({"cache_dir": "references_cache", "reference_fields": ["reference"],
                                       "snippet_fields": ["snippet"]})


def corpus(root, *references):
    lines = ["evidence:"] + [f"- reference: '{r}'\n  snippet: growth increased" for r in references]
    (root / "item.yaml").write_text("\n".join(lines) + "\n")
    return validate_corpus(root, ["item.yaml"], CONFIG)


def run(root, report, transport, **kwargs):
    return fetcher.fetch_missing(root, CONFIG, report, transport=transport, apply=True,
                                 sleep=lambda _: None, today=TODAY, **kwargs)


def test_dry_run_plans_only_missing_caches_and_touches_nothing(tmp_path):
    report = corpus(tmp_path, "PMID:2", "doi:10.1000/x", "UniProtKB:P1")

    def no_network(url, params):
        raise AssertionError("dry run must not call the network")
    result = fetcher.fetch_missing(tmp_path, CONFIG, report, transport=no_network)
    assert (result.planned_pmids, result.planned_dois) == (["2"], ["10.1000/x"])
    assert not (tmp_path / "references_cache").exists()


def test_written_pmid_cache_is_read_back_by_the_gate(tmp_path):
    report = corpus(tmp_path, "PMID:2", "PMID:3", "PMID:4")
    ncbi = FakeNCBI([article(2), article(3, abstract=None)])
    result = run(tmp_path, report, ncbi)
    assert result.written == ["PMID:2"]
    assert result.no_abstract == ["PMID:3"] and result.not_found == ["PMID:4"]
    assert not (tmp_path / "references_cache/PMID_3.md").exists()
    cached = tmp_path / "references_cache/PMID_2.md"
    assert cached.stat().st_mode & 0o777 == 0o644
    text = cached.read_text()
    assert text.startswith("# PMID:2\n") and "retrieved 2026-11-03" in text
    assert "https://pubmed.ncbi.nlm.nih.gov/2/" in text
    after = validate_corpus(tmp_path, ["item.yaml"], CONFIG)
    assert after["verdicts"]["OK"] == 1 and after["verdicts"]["MISSING_CACHE"] == 2
    assert len(ncbi.calls) == 1  # one batched efetch for three PMIDs


def test_structured_abstract_labels_are_kept(tmp_path):
    report = corpus(tmp_path, "PMID:5")
    run(tmp_path, report, FakeNCBI([article(5, label="RESULTS")]))
    assert "**RESULTS:** Growth increased under iron." in (tmp_path / "references_cache/PMID_5.md").read_text()


def test_doi_is_accepted_only_from_a_record_that_lists_it(tmp_path):
    report = corpus(tmp_path, "doi:10.1000/Good", "doi:10.1000/wrong", "doi:10.1000/none", "doi:10.1000/two")
    ncbi = FakeNCBI([article(7, doi="10.1000/GOOD"), article(8, doi="10.1000/elsewhere")],
                    search={"10.1000/good": ["7"], "10.1000/wrong": ["8"], "10.1000/two": ["7", "8"]})
    result = run(tmp_path, report, ncbi)
    assert result.written == ["DOI:10.1000/good"]
    assert result.doi_unverified == ["DOI:10.1000/wrong"]
    assert result.doi_unresolved == ["DOI:10.1000/none"]
    assert result.doi_ambiguous == ["DOI:10.1000/two"]
    text = (tmp_path / "references_cache" / cache_file_name("DOI", "10.1000/good")).read_text()
    assert text.startswith("# DOI:10.1000/good\n") and "**PMID:** 7" in text
    after = validate_corpus(tmp_path, ["item.yaml"], CONFIG)
    assert after["verdicts"]["OK"] == 1


def test_a_record_for_another_pmid_is_never_written_under_the_requested_one(tmp_path):
    report = corpus(tmp_path, "PMID:2")

    def wrong_record(url, params):
        return f"<PubmedArticleSet>{article(99)}</PubmedArticleSet>".encode()
    result = run(tmp_path, report, wrong_record)
    assert result.written == [] and result.not_found == ["PMID:2"]
    assert not (tmp_path / "references_cache/PMID_99.md").exists()


def test_existing_cache_is_never_replaced(tmp_path):
    cache = tmp_path / "references_cache"
    cache.mkdir()
    (cache / "PMID_2.md").write_text("curated bytes")
    assert fetcher._write_new(cache, "PMID_2.md", "fetched bytes") is False
    assert (cache / "PMID_2.md").read_text() == "curated bytes"
    assert [p.name for p in cache.iterdir()] == ["PMID_2.md"]  # no temporary left behind


def test_a_cache_created_after_the_check_is_not_replaced(tmp_path, monkeypatch):
    """The no-clobber link is the real guard; the early existence check is a shortcut."""
    cache = tmp_path / "references_cache"
    cache.mkdir()
    (cache / "PMID_2.md").write_text("written concurrently")
    exists = fetcher.Path.exists
    monkeypatch.setattr(fetcher.Path, "exists", lambda self: False if self.name == "PMID_2.md" else exists(self))
    assert fetcher._write_new(cache, "PMID_2.md", "fetched bytes") is False
    assert (cache / "PMID_2.md").read_text() == "written concurrently"
    assert sorted(p.name for p in cache.iterdir()) == ["PMID_2.md"]


def test_text_that_would_not_read_back_is_not_written(tmp_path):
    report = corpus(tmp_path, "PMID:6")
    result = run(tmp_path, report, FakeNCBI([article(6, abstract="## Abstract hidden heading")]))
    assert result.unrenderable == ["PMID:6"] and result.written == []


def test_failure_after_retries_reports_partial_work_without_the_key(tmp_path):
    report = corpus(tmp_path, "PMID:2", "doi:10.1000/x")
    ncbi = FakeNCBI([article(2)])
    calls = {"n": 0}

    def flaky(url, params):
        calls["n"] += 1
        if url == fetcher.ESEARCH:
            raise OSError("connection reset")
        return ncbi(url, params)
    with pytest.raises(fetcher.FetchError) as raised:
        run(tmp_path, report, flaky, api_key="SECRET-KEY")
    assert raised.value.partial["written"] == ["PMID:2"]
    assert "SECRET-KEY" not in str(raised.value)
    assert calls["n"] == 1 + fetcher.ATTEMPTS


@pytest.mark.parametrize(("api_key", "pause"), [(None, 1 / 3), ("k", 1 / 10)])
def test_successive_requests_are_spaced_at_ncbis_published_rate(tmp_path, api_key, pause):
    """#737: three requests (PMID efetch, DOI esearch, DOI efetch) give exactly two pauses."""
    report = corpus(tmp_path, "PMID:2", "doi:10.1000/good")
    pauses = []
    ncbi = FakeNCBI([article(2), article(7, doi="10.1000/good")], search={"10.1000/good": ["7"]})
    fetcher.fetch_missing(tmp_path, CONFIG, report, transport=ncbi, apply=True,
                          sleep=pauses.append, today=TODAY, api_key=api_key)
    assert len(ncbi.calls) == 3
    assert pauses == [pytest.approx(pause)] * 2


def test_a_failed_request_backs_off_before_retrying(tmp_path):
    report = corpus(tmp_path, "PMID:2")
    pauses = []
    result = fetcher.fetch_missing(tmp_path, CONFIG, report, transport=FakeNCBI([article(2)], fail=1),
                                   apply=True, sleep=pauses.append, today=TODAY)
    assert result.written == ["PMID:2"]
    assert pauses == [pytest.approx(2 / 3), pytest.approx(1 / 3)]  # back-off, then the rate pause


def test_api_key_is_sent_as_a_parameter_and_identity_is_anonymous(tmp_path):
    report = corpus(tmp_path, "PMID:2")
    ncbi = FakeNCBI([article(2)])
    run(tmp_path, report, ncbi, api_key="k")
    assert ncbi.calls[0][1]["api_key"] == "k"
    assert "email" not in ncbi.calls[0][1] and "@" not in fetcher.USER_AGENT


def test_limit_is_a_canary_that_still_reports_everything_missing(tmp_path):
    """#740: --limit narrows what this run covers, not what it reports as missing."""
    report = corpus(tmp_path, "PMID:2", "PMID:3", "doi:10.1000/x")
    result = fetcher.fetch_missing(tmp_path, CONFIG, report, limit=2)
    assert (result.missing_pmids, result.missing_dois) == (["2", "3"], ["10.1000/x"])
    assert (result.planned_pmids, result.planned_dois) == (["2"], ["10.1000/x"])


@pytest.mark.parametrize(("references", "limit", "covered"), [
    (("PMID:2", "PMID:3", "doi:10.1000/x"), 1, ([], ["10.1000/x"])),
    (("PMID:2", "PMID:3", "doi:10.1000/x"), 2, (["2"], ["10.1000/x"])),
    (("PMID:2", "doi:10.1000/x", "doi:10.1000/y", "doi:10.1000/z"), 4, (["2"], ["10.1000/x", "10.1000/y", "10.1000/z"])),
    (("PMID:2", "PMID:3"), 1, (["2"], [])),
    (("doi:10.1000/x", "doi:10.1000/y"), 1, ([], ["10.1000/x"])),
])
def test_a_limited_canary_covers_a_doi_whenever_one_is_pending(tmp_path, references, limit, covered):
    """#744: a canary must take the batch's paths, so the DOI path is never skipped."""
    report = corpus(tmp_path, *references)
    result = fetcher.fetch_missing(tmp_path, CONFIG, report, limit=limit)
    assert (result.planned_pmids, result.planned_dois) == covered


def test_http_transport_posts_form_parameters(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"ok"

    def urlopen(request, timeout):
        seen.update(url=request.full_url, data=request.data, agent=request.get_header("User-agent"))
        return Response()
    monkeypatch.setattr(fetcher.urllib.request, "urlopen", urlopen)
    assert fetcher.http_transport(fetcher.EFETCH, {"db": "pubmed", "id": "1,2"}) == b"ok"
    assert urllib.parse.parse_qs(seen["data"].decode()) == {"db": ["pubmed"], "id": ["1,2"]}
    assert seen["agent"] == fetcher.USER_AGENT


def test_written_doi_cache_survives_validator_identity_rules(tmp_path):
    report = corpus(tmp_path, "https://doi.org/10.1000/A:B")
    run(tmp_path, report, FakeNCBI([article(7, doi="10.1000/a:b")], search={"10.1000/a:b": ["7"]}))
    validator = EvidenceValidator(tmp_path, CONFIG)
    assert validator.check_item({"reference": "doi:10.1000/a:b", "snippet": "growth increased"}).verdict == "OK"


# --- review findings on #730 (#738, #739) ------------------------------------

def test_the_plan_is_exactly_the_gates_missing_caches(tmp_path):
    """#738: a cached source (matching or not) or a broken cache is never refetched."""
    cache = tmp_path / "references_cache"
    cache.mkdir()
    (cache / "PMID_1.md").write_text("# PMID:1\n\n## Abstract\n\nGrowth increased.\n")
    (cache / "PMID_5.md").write_text("not a cache file")
    (tmp_path / "item.yaml").write_text(
        "evidence:\n"
        "- reference: PMID:1\n  snippet: growth increased\n"
        "- reference: PMID:1\n  snippet: something else\n"
        "- reference: PMID:2\n  snippet: growth increased\n"
        "- reference: PMID:5\n  snippet: growth increased\n"
        "- reference: UniProtKB:P1\n  snippet: growth increased\n")
    report = validate_corpus(tmp_path, ["item.yaml"], CONFIG)
    assert {r["verdict"] for r in report["results"]} == {
        "OK", "SNIPPET_NOT_IN_SOURCE", "MISSING_CACHE", "INVALID_CACHE", "UNSUPPORTED_REFERENCE"}
    assert fetcher.plan(report) == (["2"], [])


def test_a_doi_in_the_records_reference_list_is_not_its_own(tmp_path):
    """#738: only the record's own ELocationID and ArticleIdList identify it."""
    report = corpus(tmp_path, "doi:10.1000/cited")
    ncbi = FakeNCBI([article(7, doi="10.1000/own", cited_doi="10.1000/cited")],
                    search={"10.1000/cited": ["7"]})
    result = run(tmp_path, report, ncbi)
    assert result.doi_unverified == ["DOI:10.1000/cited"] and result.written == []


@pytest.mark.parametrize("reply", [b"[]", b'{"esearchresult": []}', b'{"esearchresult": {"idlist": "7"}}',
                                   b'{"esearchresult": {"idlist": ["seven"]}}', b"not json"])
def test_a_malformed_search_reply_stops_with_the_partial_result(tmp_path, reply):
    """#739: no traceback, and what was already written is still reported."""
    report = corpus(tmp_path, "PMID:2", "doi:10.1000/x")
    ncbi = FakeNCBI([article(2)])

    def transport(url, params):
        return reply if url == fetcher.ESEARCH else ncbi(url, params)
    with pytest.raises(fetcher.FetchError) as raised:
        run(tmp_path, report, transport)
    assert raised.value.partial["written"] == ["PMID:2"]


def test_a_rejected_query_names_no_record(tmp_path):
    report = corpus(tmp_path, "doi:10.1000/x")
    result = run(tmp_path, report, lambda url, params: b'{"esearchresult": {"ERROR": "bad query"}}')
    assert result.doi_unresolved == ["DOI:10.1000/x"]


# --- the fetch CLI (#738) ----------------------------------------------------

def _repo(root):
    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test")  # git does not require an address here
    git("remote", "add", "origin", "https://github.com/CultureBotAI/HabitatMech.git")
    git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "fixture")


def _manifest(enabled=True, globs=("item.yaml",), cache_dir="references_cache"):
    settings = {"cache_dir": cache_dir, "reference_fields": ["reference"], "snippet_fields": ["snippet"]}
    capability = SimpleNamespace(is_enabled=enabled, settings=settings, reason="measured reason")
    mech = SimpleNamespace(key="habitatmech", github="CultureBotAI/HabitatMech", record_globs=globs,
                           capability=lambda name: capability)
    return SimpleNamespace(mechs={"habitatmech": mech})


@pytest.fixture
def cli_root(tmp_path, tmp_path_factory, monkeypatch):
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path_factory.mktemp("workspace")))
    _repo(tmp_path)
    corpus(tmp_path, "PMID:2")
    monkeypatch.setattr(fetcher, "load_fleet_manifest", lambda: _manifest())
    monkeypatch.setattr(fetcher, "http_transport", FakeNCBI([article(2)]))
    monkeypatch.setattr(fetcher.time, "sleep", lambda _: None)
    return tmp_path


def test_cli_dry_run_reports_the_plan_and_writes_nothing(cli_root, capsys):
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root)]) == 0
    assert "1 PMIDs and 0 DOIs lack a cache; this run covers 1 and 0" in capsys.readouterr().out
    assert not (cli_root / "references_cache").exists()


def test_cli_apply_writes_and_exits_zero(cli_root):
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply"]) == 0
    assert (cli_root / "references_cache/PMID_2.md").is_file()


def test_cli_exits_one_when_requests_fail(cli_root, monkeypatch, capsys):
    def down(url, params):
        raise OSError("down")
    monkeypatch.setattr(fetcher, "http_transport", down)
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply"]) == 1
    assert "fetch stopped" in capsys.readouterr().err


def test_cli_refuses_unreadable_records(cli_root, monkeypatch):
    (cli_root / "broken.yaml").write_text("evidence: [\n")
    monkeypatch.setattr(fetcher, "load_fleet_manifest", lambda: _manifest(globs=("*.yaml",)))
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply"]) == 2
    assert not (cli_root / "references_cache").exists()


def test_cli_refuses_to_write_through_a_symlinked_parent(cli_root, monkeypatch):
    """A symlinked cache_dir itself is already INVALID_CACHE to the gate, so nothing is
    planned. A symlinked parent inside the repository leaves the items MISSING_CACHE,
    and the fetcher must still refuse to write through it."""
    (cli_root / "elsewhere").mkdir()
    (cli_root / "sources").symlink_to(cli_root / "elsewhere", target_is_directory=True)
    monkeypatch.setattr(fetcher, "load_fleet_manifest", lambda: _manifest(cache_dir="sources/abstracts"))
    # #745: the dry run checks the destination too, so it fails where --apply would.
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root)]) == 2
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply"]) == 2
    assert list((cli_root / "elsewhere").iterdir()) == []


def test_cli_refuses_a_disabled_mech(cli_root, monkeypatch, capsys):
    monkeypatch.setattr(fetcher, "load_fleet_manifest", lambda: _manifest(enabled=False))
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root)]) == 2
    assert "measured reason" in capsys.readouterr().err


def test_cli_checks_the_json_destination_before_any_work(cli_root):
    with pytest.raises(SystemExit) as raised:
        fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply",
                      "--json", str(cli_root / "missing-dir/out.json")])
    assert raised.value.code == 2
    assert not (cli_root / "references_cache").exists()


# --- second review on #730 (#742 to #747) ------------------------------------

def test_cli_prints_everything_missing_beside_what_a_limited_run_covers(cli_root, capsys):
    """#742: the printed summary, not just FetchResult, must differ under --limit."""
    corpus(cli_root, "PMID:2", "PMID:3")
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--limit", "1"]) == 0
    assert "2 PMIDs and 0 DOIs lack a cache; this run covers 1 and 0" in capsys.readouterr().out


def test_cli_refuses_a_json_destination_that_is_a_directory(cli_root):
    """#743: refused at parse time, before any network work or cache write."""
    (cli_root / "out").mkdir()
    with pytest.raises(SystemExit) as raised:
        fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply", "--json", str(cli_root / "out")])
    assert raised.value.code == 2
    assert not (cli_root / "references_cache").exists()


def test_cli_reports_an_unwritable_json_destination_without_a_traceback(cli_root, monkeypatch, capsys):
    """#743: the result write is guarded even when the path looked writable."""
    def refuse(self, *args, **kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr(fetcher.Path, "write_text", refuse)
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--json", str(cli_root / "out.json")]) == 2
    assert "could not write" in capsys.readouterr().err


def test_a_non_string_search_id_is_malformed(tmp_path):
    """#743: an integer id must not escape as a TypeError."""
    report = corpus(tmp_path, "doi:10.1000/x")
    with pytest.raises(fetcher.FetchError):
        run(tmp_path, report, lambda url, params: b'{"esearchresult": {"idlist": [7]}}')


class _Locks:
    """A LockManager stand-in that knows whether the repository lock is held now."""

    held_now = False
    taken: list[tuple[str, str]] = []

    def lock(self, resource, operation):
        import contextlib

        @contextlib.contextmanager
        def hold():
            _Locks.taken.append((resource, operation))
            _Locks.held_now = True
            try:
                yield
            finally:
                _Locks.held_now = False
        return hold()


def _watch_lock(monkeypatch):
    """Record, for the plan and every cache write, whether the lock was held."""
    _Locks.held_now, _Locks.taken = False, []
    seen: dict[str, list[bool]] = {"plan": [], "write": []}
    monkeypatch.setattr(fetcher, "LockManager", _Locks)
    validate, write = fetcher.validate_corpus, fetcher._write_new

    def watched_validate(*args, **kwargs):
        seen["plan"].append(_Locks.held_now)
        return validate(*args, **kwargs)

    def watched_write(*args, **kwargs):
        seen["write"].append(_Locks.held_now)
        return write(*args, **kwargs)
    monkeypatch.setattr(fetcher, "validate_corpus", watched_validate)
    monkeypatch.setattr(fetcher, "_write_new", watched_write)
    return seen


def test_cli_holds_the_repository_lock_only_while_applying(cli_root, monkeypatch):
    """#746/#748/#749: the plan and every write happen inside one hold; dry runs take none."""
    seen = _watch_lock(monkeypatch)
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root)]) == 0
    assert _Locks.taken == [] and seen == {"plan": [False], "write": []}
    seen = _watch_lock(monkeypatch)
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply"]) == 0
    assert _Locks.taken == [("habitatmech", "evidence-fetch")]
    assert seen == {"plan": [True], "write": [True]}
    assert not _Locks.held_now


def test_cli_reports_a_held_lock_without_a_traceback(cli_root, monkeypatch, capsys):
    class Busy:
        def lock(self, resource, operation):
            raise RuntimeError(f"Failed to acquire lock on {resource}")
    monkeypatch.setattr(fetcher, "LockManager", Busy)
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply"]) == 2
    assert "Failed to acquire lock" in capsys.readouterr().err
    assert not (cli_root / "references_cache").exists()


# --- third review on #730 (#750, #751) ---------------------------------------

def test_a_dry_run_fails_where_the_lock_setup_would(cli_root, monkeypatch, tmp_path_factory):
    """#750: --apply refuses a symlinked lock workspace, so the dry run must too."""
    real = tmp_path_factory.mktemp("real-workspace")
    link = tmp_path_factory.mktemp("links") / "workspace"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(link))
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root)]) == 2
    assert fetcher.main(["--mech", "habitatmech", "--root", str(cli_root), "--apply"]) == 2
    assert not (cli_root / "references_cache").exists()


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_refused(tmp_path, limit):
    """#751: with both kinds pending, a zero limit once planned almost everything."""
    report = corpus(tmp_path, "PMID:2", "PMID:3", "doi:10.1000/x", "doi:10.1000/y")
    with pytest.raises(ValueError, match="at least 1"):
        fetcher.fetch_missing(tmp_path, CONFIG, report, limit=limit)
