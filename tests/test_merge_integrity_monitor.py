"""Real Git histories distinguish lost concurrent content from valid squashes."""
import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).parents[1] / "src/kg_microbe_governance/artifacts/scripts"
          / "verify_merge_integrity.py")
spec = importlib.util.spec_from_file_location("merge_integrity_monitor", SCRIPT)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
REPO = "CultureBotAI/example"


def git(root, *args, input_text=None):
    return subprocess.run(["git", "-C", str(root), *args], input=input_text,
                          check=True, capture_output=True, text=True).stdout.strip()


def commit(root, name, text):
    (root / name).write_text(text)
    git(root, "add", name)
    git(root, "commit", "-m", "Fixture change")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original = monitor.Git.run

    def offline(self, *args, check=True):
        if args[0] == "fetch":
            return subprocess.CompletedProcess(args, 128, "", "offline fixture")
        return original(self, *args, check=check)

    monkeypatch.setattr(monitor.Git, "run", offline)


@pytest.fixture
def history(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "fixture@example.org")
    git(root, "config", "user.name", "Fixture")
    git(root, "remote", "add", "origin", f"https://github.com/{REPO}.git")
    initial = commit(root, "base.txt", "base\n")
    git(root, "checkout", "-b", "feature")
    head = commit(root, "feature.txt", "feature\n")
    git(root, "checkout", "main")
    before = commit(root, "concurrent.txt", "concurrent main change\n")
    git(root, "merge", "--squash", "feature")
    git(root, "commit", "-m", "A valid squash without PR number")
    after = git(root, "rev-parse", "HEAD")
    return root, initial, before, head, after


def pr(head, after, number=7):
    return {"number": number, "state": "closed", "merged": True,
            "merged_at": "2026-09-30T10:00:00Z", "merge_commit_sha": after,
            "head": {"sha": head, "repo": None},
            "base": {"ref": "main", "repo": {"full_name": REPO}}}


class API(monitor.GitHub):
    def __init__(self, mappings=None):
        self.mappings = mappings or {}
        self.calls, self.issues, self.comments = [], [], []

    def request(self, endpoint, method="GET", body=None):
        self.calls.append((endpoint, method, copy.deepcopy(body)))
        if endpoint == f"repos/{REPO}":
            return {"full_name": REPO, "default_branch": "main"}
        if "/commits/" in endpoint:
            sha = endpoint.split("/commits/", 1)[1].split("/")[0]
            return copy.deepcopy(self.mappings.get(sha, []))
        if "/pulls/" in endpoint:
            number = int(endpoint.rsplit("/", 1)[-1])
            return copy.deepcopy(next(row for values in self.mappings.values()
                                      for row in values if row["number"] == number))
        if endpoint == f"repos/{REPO}/issues" and method == "POST":
            issue = dict(body, number=42, html_url=f"https://github.com/{REPO}/issues/42")
            self.issues.append(issue)
            return issue
        if "/comments" in endpoint:
            if method == "POST":
                self.comments.append(body)
                return body
            return copy.deepcopy(self.comments)
        if "/issues?" in endpoint:
            return copy.deepcopy(self.issues)
        raise AssertionError((endpoint, method, body))


def run(history, **kwargs):
    root, _, before, head, after = history
    return monitor.verify(REPO, root, before, after, API({after: [pr(head, after)]}), **kwargs)


def corrupt(history):
    root, _, before, head, _ = history
    # Silently lose a file that reached main after the PR branched.
    return git(root, "commit-tree", git(root, "rev-parse", f"{head}^{{tree}}"),
               "-p", before, input_text="Broken squash\n")


def test_concurrent_main_content_is_preserved_by_valid_squash(history):
    root, _, before, head, after = history
    assert git(root, "rev-parse", f"{head}^{{tree}}") != git(root, "rev-parse", f"{after}^{{tree}}")
    result = run(history)
    assert result["exit_code"] == 0
    assert result["counts"] == {"verified": 1}
    assert result["commits"][0]["parent"] == before
    assert result["commits"][0]["expected_tree"] == git(root, "rev-parse", f"{after}^{{tree}}")


def test_real_lost_concurrent_content_is_a_mismatch(history):
    root, _, before, head, _ = history
    broken = corrupt(history)
    api = API({broken: [pr(head, broken)]})
    result = monitor.verify(REPO, root, before, broken, api)
    assert result["exit_code"] == 1
    assert result["complete"] and result["mismatch"]
    assert result["commits"][0]["changed_paths"] == ["concurrent.txt"]
    assert all(method == "GET" for _, method, _ in api.calls)


@pytest.mark.parametrize("boundary", ["0" * 40, "f" * 40, "main", "--upload-pack=evil"])
def test_missing_or_mutable_before_never_passes(history, boundary):
    root, _, _, _, after = history
    result = monitor.verify(REPO, root, boundary, after, API(), report_issues=True)
    assert result["exit_code"] == 2
    assert result["errors"] and not result["mismatch"]


def test_nonancestor_and_empty_ranges_fail(history):
    root, _, before, head, after = history
    for start, end in [(head, after), (after, before), (after, after)]:
        result = monitor.verify(REPO, root, start, end, API())
        assert result["exit_code"] == 2
        assert not result["commits"]


def test_identity_failure_prevents_all_network(history):
    root, _, before, _, after = history
    git(root, "remote", "set-url", "origin", "https://github.com/other/wrong.git")
    api = API()
    result = monitor.verify(REPO, root, before, after, api)
    assert result["exit_code"] == 2
    assert "origin" in result["errors"][0]
    assert api.calls == []


@pytest.mark.parametrize("change", [
    lambda row: row.update(state="open"),
    lambda row: row.update(merged_at=None),
    lambda row: row.update(merged=False),
    lambda row: row["base"].update(ref="other"),
    lambda row: row["base"]["repo"].update(full_name="other/wrong"),
    lambda row: row["head"].update(sha="bad"),
])
def test_exact_pr_identity_is_required(history, change):
    root, _, before, head, after = history
    mapping = pr(head, after)
    change(mapping)
    result = monitor.verify(REPO, root, before, after, API({after: [mapping]}), report_issues=True)
    assert result["exit_code"] == 2
    assert result["counts"] == {"incomplete": 1}
    assert not result["mismatch"]


def test_ambiguous_mapping_never_files_corruption_issue(history):
    root, _, before, head, after = history
    api = API({after: [pr(head, after), pr(head, after, 8)]})
    result = monitor.verify(REPO, root, before, after, api, report_issues=True)
    assert result["exit_code"] == 2
    assert "multiple PRs" in result["commits"][0]["detail"]
    assert all(method == "GET" for _, method, _ in api.calls)


def test_lookup_failure_does_not_become_a_corruption_issue(history, monkeypatch):
    root, _, before, head, after = history
    api = API({after: [pr(head, after)]})
    monkeypatch.setattr(api, "pages", lambda _: (_ for _ in ()).throw(monitor.Incomplete("rate limit")))
    result = monitor.verify(REPO, root, before, after, api, report_issues=True)
    assert result["exit_code"] == 2
    assert not result["mismatch"] and not api.issues


def test_whole_range_in_oldest_first_order_and_partial_error_fails(history):
    root, _, before, head, first = history
    git(root, "checkout", "-b", "second-feature")
    second_head = commit(root, "second.txt", "second feature\n")
    git(root, "checkout", "main")
    git(root, "merge", "--squash", "second-feature")
    git(root, "commit", "-m", "Second squash")
    second = git(root, "rev-parse", "HEAD")
    mappings = {first: [pr(head, first)], second: [pr(second_head, second, 8)]}
    result = monitor.verify(REPO, root, before, second, API(mappings))
    assert result["counts"] == {"verified": 2}
    assert [row["commit"] for row in result["commits"]] == [first, second]
    mappings[second][0]["head"]["sha"] = "f" * 40
    partial = monitor.verify(REPO, root, before, second, API(mappings), report_issues=True)
    assert partial["exit_code"] == 2
    assert partial["counts"] == {"verified": 1, "incomplete": 1}


def test_conflicts_are_incomplete_not_mismatches(history):
    root, initial, before, _, after = history
    git(root, "checkout", "-b", "conflicting", initial)
    head = commit(root, "concurrent.txt", "incompatible independently added content\n")
    api = API({after: [pr(head, after)]})
    result = monitor.verify(REPO, root, before, after, api, report_issues=True)
    assert result["counts"] == {"incomplete": 1}
    assert not result["mismatch"] and not api.issues


def test_mutating_head_snapshot_is_incomplete(history, monkeypatch):
    root, _, before, head, after = history
    api = API({after: [pr(head, after)]})
    original, lookups = api.request, []

    def request(endpoint, method="GET", body=None):
        row = original(endpoint, method, body)
        if "/pulls/" in endpoint:
            lookups.append(endpoint)
            if len(lookups) == 2:
                row["head"]["sha"] = before
        return row

    monkeypatch.setattr(api, "request", request)
    result = monitor.verify(REPO, root, before, after, api)
    assert result["counts"] == {"incomplete": 1}
    assert "changed" in result["commits"][0]["detail"]


def test_unmapped_single_parent_fails_and_multiparent_is_explicitly_unverified(history):
    root, _, before, head, after = history
    direct = monitor.verify(REPO, root, before, after, API())
    assert direct["counts"] == {"incomplete": 1}
    assert direct["exit_code"] == 2
    merge = git(root, "commit-tree", git(root, "rev-parse", f"{after}^{{tree}}"),
                "-p", before, "-p", head, input_text="Ordinary merge\n")
    merged = monitor.verify(REPO, root, before, merge, API())
    assert merged["counts"] == {"skipped_merge_commit": 1}
    assert merged["exit_code"] == 0
    side = monitor.verify(REPO, root, head, merge, API())
    assert side["exit_code"] == 2


def test_deleted_branch_fallback_fetches_exact_retained_head(history, monkeypatch):
    root, _, _, head, _ = history
    with monitor.tempfile.TemporaryDirectory() as temporary:
        repository = monitor.Git(root, REPO, Path(temporary) / "verify.git")
        (repository.path / "objects/info/alternates").unlink()
        calls, original = [], repository.run

        def fetch(*args, check=True):
            if args[0] != "fetch":
                return original(*args, check=check)
            calls.append(args)
            if args[-1] == "refs/pull/7/head":
                subprocess.run(["git", "--git-dir", str(repository.path), "fetch", "--no-tags",
                                "--no-write-fetch-head", str(root), head], check=True,
                               capture_output=True)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(repository, "run", fetch)
        repository.ensure_commit(head, 7)
        assert [call[-1] for call in calls] == [head, "refs/pull/7/head"]
        assert repository.have_commit(head)
        assert not (repository.path / "FETCH_HEAD").exists()


def test_fallback_does_not_substitute_a_different_head(history, monkeypatch):
    root = history[0]
    with monitor.tempfile.TemporaryDirectory() as temporary:
        repository = monitor.Git(root, REPO, Path(temporary) / "verify.git")
        calls, original = [], repository.run

        def fetch(*args, check=True):
            if args[0] == "fetch":
                calls.append(args[-1])
                return subprocess.CompletedProcess(args, 0, "", "")
            return original(*args, check=check)

        monkeypatch.setattr(repository, "run", fetch)
        with pytest.raises(monitor.Incomplete, match="unavailable"):
            repository.ensure_commit("f" * 40, 7)
        assert calls == ["f" * 40, "refs/pull/7/head"]


def test_local_hooks_drivers_index_and_worktree_are_untouched(history, tmp_path):
    root = history[0]
    marker = tmp_path / "executed"
    git(root, "config", "merge.hostile.driver", f"touch {marker}")
    git(root, "config", "merge.default", "hostile")
    hook = root / ".git/hooks/post-merge"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    (root / "base.txt").write_text("uncommitted user data\n")
    git(root, "add", "base.txt")
    (root / "untracked.txt").write_text("preserve me\n")
    index = (root / ".git/index").read_bytes()
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    result = run(history)
    assert result["exit_code"] == 0
    assert not marker.exists()
    assert (root / ".git/index").read_bytes() == index
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == status


def test_paginated_api_includes_later_pages(monkeypatch):
    api, pages = monitor.GitHub(), []

    def request(endpoint):
        pages.append(endpoint)
        return [{"number": i} for i in range(100)] if endpoint.endswith("&page=1") else [{"number": 101}]

    monkeypatch.setattr(api, "request", request)
    assert len(api.pages("repos/example/repo/issues?state=open")) == 101
    assert pages[-1].endswith("&per_page=100&page=2")


def test_confirmed_incidents_are_opt_in_and_deduplicated(history):
    root, _, before, head, _ = history
    broken = corrupt(history)
    api = API({broken: [pr(head, broken)]})
    first = monitor.verify(REPO, root, before, broken, api, report_issues=True)
    second = monitor.verify(REPO, root, before, broken, api, report_issues=True)
    assert first["exit_code"] == second["exit_code"] == 1
    assert len(api.issues) == 1 and api.comments == []
    assert api.issues[0]["body"].startswith(monitor.ISSUE_MARKER)
    assert first["issue_url"].endswith("/42")


def test_api_mutation_body_is_json_stdin_not_shell_interpolation(monkeypatch):
    calls = []

    def capture(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, '{}', '')

    monkeypatch.setattr(monitor, "command", capture)
    body = {"body": "literal `backticks`, $(touch /tmp/do-not-run), new\nline"}
    monitor.GitHub().request("repos/example/repo/issues", "POST", body)
    assert calls[0][0][-2:] == ["--input", "-"]
    assert json.loads(calls[0][1]["input_text"]) == body
    assert body["body"] not in calls[0][0]


def test_subprocesses_have_bounded_timeouts(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 120
        assert kwargs["check"] is False
        raise subprocess.TimeoutExpired(args[0], 120)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(monitor.Incomplete, match="TimeoutExpired"):
        monitor.command(["gh", "api", "repos/example/repo"])


def test_cli_writes_incomplete_evidence_and_exits_nonzero(history, tmp_path):
    root, _, _, _, after = history
    report = tmp_path / "report.json"
    code = monitor.main(["--repository", REPO, "--repo-root", str(root),
                         "--before", "0" * 40, "--after", after, "--report", str(report)])
    assert code == 2
    assert json.loads(report.read_text())["complete"] is False


def test_repository_merge_driver_cannot_execute(history, tmp_path):
    root = history[0]
    git(root, "checkout", "-b", "driver-base")
    base = commit(root, "shared.txt", "first\n" + "middle\n" * 20 + "last\n")
    git(root, "checkout", "-b", "driver-feature")
    head = commit(root, "shared.txt", "FEATURE\n" + "middle\n" * 20 + "last\n")
    git(root, "checkout", "driver-base")
    parent = commit(root, "shared.txt", "first\n" + "middle\n" * 20 + "MAIN\n")
    git(root, "merge", "--squash", "driver-feature")
    git(root, "commit", "-m", "Clean content merge")
    after = git(root, "rev-parse", "HEAD")
    assert base != head != parent
    # Prove this fixture invokes the configured driver in an unsafe source
    # repository merge-tree, then check the isolated verifier never invokes it.
    marker = tmp_path / "driver-executed"
    git(root, "config", "merge.hostile.driver", f"touch {marker}; exit 1")
    git(root, "config", "merge.default", "hostile")
    unsafe = subprocess.run(["git", "-C", str(root), "merge-tree", "--write-tree", parent, head],
                            capture_output=True, text=True)
    assert unsafe.returncode and marker.exists()
    marker.unlink()
    result = monitor.verify(REPO, root, parent, after, API({after: [pr(head, after)]}))
    assert result["counts"] == {"verified": 1}
    assert not marker.exists()


def test_malformed_associated_api_response_is_incomplete(history):
    root, _, before, _, after = history
    result = monitor.verify(REPO, root, before, after, API({after: [{"number": 7}]}))
    assert result["counts"] == {"incomplete": 1}
    assert result["exit_code"] == 2


def test_issue_reporting_failure_remains_failure_with_mismatch_evidence(history, monkeypatch):
    root, _, before, head, _ = history
    broken = corrupt(history)
    api = API({broken: [pr(head, broken)]})
    original = api.request

    def request(endpoint, method="GET", body=None):
        if method != "GET":
            raise monitor.Incomplete("issue write denied")
        return original(endpoint, method, body)

    monkeypatch.setattr(api, "request", request)
    report = monitor.verify(REPO, root, before, broken, api, report_issues=True)
    assert report["exit_code"] == 2 and report["mismatch"]
    assert report["errors"] == ["issue write denied"]


def test_corrupted_squash_without_api_mapping_never_turns_integrity_green(history):
    root, _, before, _, _ = history
    broken = corrupt(history)
    report = monitor.verify(REPO, root, before, broken, API(), report_issues=True)
    assert report["exit_code"] == 2
    assert report["counts"] == {"incomplete": 1}
    assert not report["mismatch"]


@pytest.mark.parametrize("fetch_succeeds", [True, False])
def test_missing_blob_fetches_only_immutable_object_to_isolated_store(history, monkeypatch, fetch_succeeds):
    root = history[0]
    git(root, "checkout", "-b", "blob-base")
    commit(root, "shared.txt", "first\n" + "middle\n" * 20 + "last\n")
    git(root, "checkout", "-b", "blob-feature")
    head = commit(root, "shared.txt", "FEATURE\n" + "middle\n" * 20 + "last\n")
    git(root, "checkout", "blob-base")
    parent = commit(root, "shared.txt", "first\n" + "middle\n" * 20 + "MAIN\n")
    git(root, "merge", "--squash", "blob-feature")
    git(root, "commit", "-m", "Clean content merge")
    after = git(root, "rev-parse", "HEAD")
    blob = git(root, "rev-parse", f"{head}:shared.txt")
    source_object = root / ".git/objects" / blob[:2] / blob[2:]
    content = source_object.read_bytes()
    source_object.unlink()
    original, fetched = monitor.Git.run, []

    def transport(self, *args, check=True):
        if args[0] == "fetch":
            fetched.append(args)
            assert args[-2] == f"https://github.com/{REPO}.git"
            assert args[-1] == blob
            if not fetch_succeeds:
                return subprocess.CompletedProcess(args, 128, "", "object unavailable")
            target = self.path / "objects" / blob[:2] / blob[2:]
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(content)
            return subprocess.CompletedProcess(args, 0, "", "")
        return original(self, *args, check=check)

    monkeypatch.setattr(monitor.Git, "run", transport)
    report = monitor.verify(REPO, root, parent, after, API({after: [pr(head, after)]}))
    assert report["counts"] == ({"verified": 1} if fetch_succeeds else {"incomplete": 1})
    assert report["exit_code"] == (0 if fetch_succeeds else 2)
    assert not report["mismatch"]
    assert len(fetched) == 1
    assert not source_object.exists()
