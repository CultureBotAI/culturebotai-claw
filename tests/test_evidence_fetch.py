"""The cache fetcher adds only what the gate needs, and only what it can verify (#729).

Offline: every request goes to an injected transport that answers from
constructed PubMed XML, so identity, overwrite and failure rules are exercised
without NCBI.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse

import pytest

from kg_microbe_evidence import (
    EvidenceConfig,
    EvidenceValidator,
    cache_file_name,
    validate_corpus,
)
from kg_microbe_evidence import fetch as fetcher

TODAY = dt.date(2026, 11, 3)


def article(pmid, abstract="Growth increased under iron.", doi=None, label=None):
    text = f'<AbstractText Label="{label}">{abstract}</AbstractText>' if label else f"<AbstractText>{abstract}</AbstractText>"
    body = f"<Abstract>{text}</Abstract>" if abstract else ""
    location = f'<ELocationID EIdType="doi">{doi}</ELocationID>' if doi else ""
    return (f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>"
            f"<Journal><Title>J</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>"
            f"<ArticleTitle>Title {pmid}</ArticleTitle>{location}{body}"
            f"<AuthorList><Author><LastName>Doe</LastName><Initials>J</Initials></Author></AuthorList>"
            f"</Article></MedlineCitation></PubmedArticle>")


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
            return json.dumps({"esearchresult": {"idlist": self.search.get(doi, [])}}).encode()
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


def test_retry_recovers_and_rate_limits(tmp_path):
    report = corpus(tmp_path, "PMID:2")
    pauses = []
    result = fetcher.fetch_missing(tmp_path, CONFIG, report, transport=FakeNCBI([article(2)], fail=1),
                                   apply=True, sleep=pauses.append, today=TODAY, api_key="k")
    assert result.written == ["PMID:2"]
    assert pauses and all(p > 0 for p in pauses)


def test_api_key_is_sent_as_a_parameter_and_identity_is_anonymous(tmp_path):
    report = corpus(tmp_path, "PMID:2")
    ncbi = FakeNCBI([article(2)])
    run(tmp_path, report, ncbi, api_key="k")
    assert ncbi.calls[0][1]["api_key"] == "k"
    assert "email" not in ncbi.calls[0][1] and "@" not in fetcher.USER_AGENT


def test_limit_is_a_canary(tmp_path):
    report = corpus(tmp_path, "PMID:2", "PMID:3", "doi:10.1000/x")
    result = fetcher.fetch_missing(tmp_path, CONFIG, report, limit=1)
    assert (result.planned_pmids, result.planned_dois) == (["2"], [])


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
