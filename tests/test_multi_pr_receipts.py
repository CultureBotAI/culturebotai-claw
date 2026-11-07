"""Ordered closures: sanitized DUF c3s5 split and independent adversarial inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_mech_session_supervisor import (  # noqa: F401 -- shared pytest fixtures
    HEAD,
    CycleGitHubFixture,
    cycle_instance,
    cycle_setup,
    setup,
    supervisor,
    write_goal_evidence,
)

import kg_microbe_progress as progress
from kg_microbe_progress import prs
from kg_microbe_workflows import evidence_directory
from kg_microbe_workflows.closure import multi_pr_members

SOURCE = json.loads((Path(__file__).parent / "fixtures/duf_c3s5_multi_pr.json").read_text())
FIRST, LAST = SOURCE["prs"]
EARLY_FIX = FIRST["fix_commits"]["361"]
LATER_FIX = FIRST["fix_commits"]["366"]
ZERO = "0" * 40


class OrderedRemote:
    """Synthetic offline Git/GitHub state; any unexpected command is refused."""
    def __init__(self, state):
        self.state = state
        self.calls = []
        self.prs = {}
        self.commits = {}
        self.checks = {}
        self.raw_changes = {}
        self.parents = {}
        self.ancestry_fail = set()
        self.remote_fail = set()
        self.local_fail = set()
        self.page_headers = {}
        self.trees = {}
        self.modes = {}
        self.current_tree = {str(path.relative_to(state.repo)): self.blob(path.read_bytes())
                             for path in state.repo.rglob("*") if path.is_file()}
        for source in SOURCE["prs"]:
            number = source["number"]
            shas = sorted(set(source["fix_commits"].values()) | {source["head_sha"]})
            self.commits[number] = [{"sha": sha, "commit": {"committer": {"date": source["created_at"]}}} for sha in shas]
            self.prs[number] = {"number": number, "merged": True, "merged_at": source["merged_at"],
                "created_at": source["created_at"], "merge_commit_sha": source["merge_commit_sha"], "commits": len(shas),
                "base": {"ref": source["base"], "repo": {"full_name": SOURCE["repository"]}},
                "head": {"ref": source["branch"], "sha": source["head_sha"], "repo": {"full_name": SOURCE["repository"]}}}
            self.checks[number] = [{"name": "tests", "bucket": "pass", "state": "SUCCESS"}]
            self.trees[source["head_sha"]] = dict(self.current_tree)
            for sha in shas:
                self.parents[sha] = [HEAD]
                self.raw_changes[sha] = ""
        for item in state.receipt["evidence_attributions"]:
            self.add_change(item["commit_sha"], item["path"], ZERO, self.current_tree[item["path"]])
        for fix in set(FIRST["fix_commits"].values()):
            self.add_change(fix, "src/fixed.py", ZERO, self.blob(b"correct code\n"))
            for tree in self.trees.values():
                tree["src/fixed.py"] = self.blob(b"correct code\n")
        for path in SOURCE["overlapping_review_paths"]:
            earlier = self.blob((path + " original reviewed fix\n").encode())
            later = self.blob((path + " successor issue-fix review\n").encode())
            self.add_change(EARLY_FIX, path, ZERO, earlier)
            self.add_change(LATER_FIX, path, earlier, later)
            for tree in self.trees.values():
                tree[path] = later
        # The first PR contains the old manifest bytes, so the final manifest
        # cannot truthfully be attributed to it even though most outputs persist.
        manifest = state.receipt["goal_outputs"]["goal_evidence"]["path"]
        self.trees[FIRST["head_sha"]][manifest] = self.blob(b"old evidence kind\n")

    blob = staticmethod(CycleGitHubFixture.blob)

    def add_change(self, sha, path, old, new):
        mode = "000000" if old == ZERO else "100644"
        status = "A" if old == ZERO else "M"
        self.raw_changes[sha] += f":{mode} 100644 {old} {new} {status}\0{path}\0"

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        code = 0
        if args[0] == "git":
            command = args[3:]
            if command == ["remote", "get-url", "origin"]:
                out = f"https://github.com/{SOURCE['repository']}.git\n"
            elif command[:1] == ["status"]:
                out = ""
            elif command[:1] == ["symbolic-ref"]:
                out = "main"
            elif command == ["rev-parse", "HEAD"]:
                out = LAST["merge_commit_sha"]
            elif command[:1] == ["rev-parse"] and ":" in command[-1]:
                head, path = command[-1].split(":", 1)
                out = self.trees[head].get(path, "")
            elif command[:1] == ["hash-object"]:
                out = self.blob((self.state.repo / command[-1]).read_bytes())
            elif command[:1] == ["cat-file"]:
                out = "commit"
            elif command[:1] == ["merge-base"]:
                code, out = int(tuple(command[-2:]) in self.ancestry_fail), ""
            elif command[:1] == ["ls-remote"]:
                code, out = (0 if command[-1] in self.remote_fail else 2), ""
            elif command[:1] == ["show-ref"]:
                code, out = (0 if command[-1] in self.local_fail else 1), ""
            elif command[:1] == ["rev-list"]:
                out = " ".join([command[-1], *self.parents[command[-1]]])
            elif command[:1] == ["diff-tree"]:
                out = self.raw_changes[command[-1]]
            elif command[:1] == ["ls-tree"]:
                head, path = command[2], command[-1]
                blob = self.trees[head].get(path)
                out = f"{self.modes.get((head, path), '100644')} blob {blob}\t{path}\0" if blob else ""
            else:
                raise AssertionError(args)
        elif args[:3] == ["gh", "pr", "checks"]:
            out = json.dumps(self.checks[int(args[5])])
        elif args[:2] == ["gh", "api"]:
            endpoint = args[-1]
            if "/commits?" in endpoint:
                number = int(endpoint.split("/pulls/")[1].split("/")[0])
                out = self.page_headers.get(number, "HTTP/2.0 200 OK\n") + "\n" + json.dumps(self.commits[number])
            elif "/pulls/" in endpoint:
                out = json.dumps(self.prs[int(endpoint.rsplit("/", 1)[-1])])
            elif "/issues/" in endpoint:
                assert int(endpoint.rsplit("/", 1)[-1]) in {361, 362, 363, 364, 366}
                out = json.dumps({"state": "closed"})
            else:
                raise AssertionError(args)
        else:
            raise AssertionError(args)
        return SimpleNamespace(stdout=out, stderr="", returncode=code)


def write_registry(state, records=None):
    if records is None:
        records = [{**prs._context(state.ledger), "schema_version": 1, "pr_number": number,
                    "reported_at": "2026-10-25T19:10:00Z"} for number in (365, 367)]
    state.session.mkdir(parents=True, exist_ok=True)
    (state.session / prs.REGISTRY_NAME).write_text("".join(json.dumps(row) + "\n" for row in records))


@pytest.fixture
def duf(cycle_setup, monkeypatch):  # noqa: F811 -- imported pytest fixture
    """Synthetic authority/registry, actual public PR split; no live runtime IO."""
    state = cycle_setup
    profile_path = Path(state.target["workflow_profile_path"])
    profile = json.loads(profile_path.read_text())
    profile.update(repository_key="dufmech", github_repository=SOURCE["repository"], profile_id="dufmech-test")
    profile_path.write_text(json.dumps(profile))
    state.target.update(repository_key="dufmech", github_repository=SOURCE["repository"])
    effective = supervisor.load_effective(state.config, state.target)
    state.target.update(_workflow=effective, stages=effective["stages"])
    state.ledger = supervisor.new_ledger(state.config, state.target)
    goal = {"conversation_id": "synthetic-duf-native-goal", "started_at": "2026-10-25T17:00:00Z", "start_step_index": 20}
    state.receipt.update(repository_key="dufmech")
    state.instance = cycle_instance(state, monkeypatch)
    # Retain a real immutable review lineage through cycle 3. These are
    # synthetic already-verified historical closures, not inferred completions.
    for cycle in (1, 2, 3):
        state.ledger.update(cycle=cycle, stage=4, adopted_goal={**goal, "start_step_index": cycle},
                            baseline_status="", baseline_head=HEAD)
        findings = ([{"finding_id": "synthetic-finding", "status": "open", "summary": "Synthetic grouped defect"}]
                    if cycle == 3 else [])
        reviewed = write_goal_evidence(state, state.ledger, findings=findings)
        reviewed.update(status="no_changes", pr=None, issues=[])
        state.ledger = state.instance.advance(state.target, state.ledger, reviewed,
            {"status": "no_changes", "verified_at": "2026-10-25T16:59:00Z"}, "native_completed")
    state.ledger.update(adopted_goal=goal, awaiting_goal=False, last_observed_at=supervisor.now())
    directory = evidence_directory(state.ledger["run_id"], 3, 5, 1)
    group = {"group_id": "synthetic-group", "summary": "Synthetic grouped defect", "finding_ids": ["synthetic-finding"],
             "issue_url": "https://github.com/CultureBotAI/DUFMech/issues/361", "status": "resolved",
             "resolution_evidence": [directory + "/validation.md"]}
    finding = {"finding_id": "synthetic-finding", "status": "resolved", "summary": "Synthetic fix",
               "carried_from": "synthetic-finding", "group_id": group["group_id"], "issue_url": group["issue_url"]}
    state.receipt = write_goal_evidence(state, state.ledger, findings=[finding], groups=[group])
    members = []
    for source in SOURCE["prs"]:
        artifact = state.repo / f"synthetic-review-{source['number']}.txt"
        artifact.write_text(f"Synthetic independent review and validation at {source['head_sha']}\n")
        descriptor = {"artifact": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
        member = {key: source[key] for key in ("number", "head_sha", "branch", "base", "merge_commit_sha")}
        member.update(review={**descriptor, "status": "complete", "head_sha": source["head_sha"], "remaining_findings": 0},
                      validation=[{**descriptor, "command": "synthetic pytest", "status": "passed", "head_sha": source["head_sha"]}],
                      cleanup={"checkout_ready": True, "local_branch_deleted": True, "remote_branch_deleted": True})
        members.append(member)
    state.receipt.update(prs=members, pr={key: members[-1][key] for key in ("number", "head_sha", "branch", "base")},
                         **{key: copy.deepcopy(members[-1][key]) for key in ("review", "validation", "cleanup")})
    state.receipt["issues"] = [{"number": int(number), "disposition": "addressed", "fix_commit_sha": sha, "pr_number": 365}
                               for number, sha in FIRST["fix_commits"].items()]
    for issue in state.receipt["issues"]:
        if issue["fix_commit_sha"] == EARLY_FIX:
            issue["superseded_paths"] = [{"path": path, "pr_number": 365, "commit_sha": LATER_FIX}
                                         for path in SOURCE["overlapping_review_paths"]]
    evidence = supervisor.goal_output_data(state.receipt, state.ledger, state.target)
    state.receipt["evidence_attributions"] = [
        {**state.receipt["goal_outputs"]["goal_evidence"], "pr_number": 367, "commit_sha": LAST["head_sha"]},
        *[{"path": item["path"], "sha256": item["sha256"], "pr_number": 365, "commit_sha": FIRST["head_sha"]}
          for item in evidence["artifacts"]]]
    state.remote = OrderedRemote(state)
    state.instance.runner = state.remote
    state.session = state.instance.directory(state.target)
    state.observation.update(goal_identity=goal, goal_state="completed")
    state.observation["native"].update(conversation_id=goal["conversation_id"], current_goal={**goal, "state": "completed"})
    write_registry(state)
    return state


def verify(state):
    return supervisor.verify_remote_receipt(state.receipt, state.ledger, state.target, state.remote, runtime=state.session)


def test_duf_c3s5_closes_to_infrastructure_and_counts_both_prs(duf):
    assert supervisor.validate_receipt(duf.receipt, duf.ledger, duf.target, duf.session) == []
    # Native completion is a separate authoritative prerequisite, not a claim
    # conferred by the new receipt or its registry records.
    authority = supervisor.completion_authority(duf.target, duf.ledger, duf.observation)
    proof = verify(duf)
    assert [item["pr_number"] for item in proof["prs"]] == [365, 367]
    assert proof["pr_number"] == 367
    advanced = duf.instance.advance(duf.target, duf.ledger, duf.receipt, proof, authority)
    assert (advanced["cycle"], advanced["stage"]) == (3, 6)
    assert supervisor.workflow_stage_key(advanced) == "infrastructure"
    assert advanced["infra_scope"] and advanced["awaiting_goal"]
    duf.instance.save(duf.target, advanced)
    supervisor.atomic_json(duf.runtime / "config.json", duf.config)
    history, snapshot = progress.collect_progress([duf.runtime])
    assert snapshot["totals"]["unique_prs"] == snapshot["totals"]["merged_prs"] == 2
    assert snapshot["totals"]["completed_goals"] == 4  # three retained stage 4 reviews + new stage 5
    assert len(history["pr_events"]) == len(history["associations"]) == 2
    assert progress.collect_progress([duf.runtime], history)[0] == history


@pytest.mark.parametrize("change", [
    lambda r: r.update(prs=None), lambda r: r.update(prs=[]), lambda r: r.update(prs={}),
    lambda r: r["prs"].append(copy.deepcopy(r["prs"][0])),
    lambda r: r["prs"][0].update(number=True), lambda r: r["prs"][0].update(unknown=True),
    lambda r: r["prs"][0]["review"].update(head_sha=HEAD),
    lambda r: r["prs"][0]["validation"][0].update(status="failed"),
    lambda r: r["prs"][0]["cleanup"].update(local_branch_deleted=False),
    lambda r: r["issues"][0].pop("pr_number"), lambda r: r["issues"][0].update(pr_number=True),
    lambda r: r["evidence_attributions"].append(copy.deepcopy(r["evidence_attributions"][0])),
    lambda r: r["evidence_attributions"][0].update(path="../escape"),
    lambda r: r["pr"].update(number=365),
])
def test_malformed_multi_never_falls_back_to_single(duf, change):
    change(duf.receipt)
    assert supervisor.validate_receipt(duf.receipt, duf.ledger, duf.target, duf.session)
    with pytest.raises((ValueError, supervisor.SupervisorError)):
        multi_pr_members(duf.receipt)


@pytest.mark.parametrize("change,message", [
    (lambda s: s.remote.prs[365].update(merged=False), "not actually merged"),
    (lambda s: s.remote.prs[365].update(created_at="2026-10-24T00:00:00Z"), "closure window"),
    (lambda s: s.remote.prs[367].update(merged_at="2026-10-25T18:00:00Z"), "closure window"),
    (lambda s: s.remote.prs[365].update(merge_commit_sha=HEAD), "merge commit differs"),
    (lambda s: s.remote.checks[365][0].update(bucket="fail"), "CI evidence"),
    (lambda s: s.remote.prs[365].update(commits=251), "inventory"),
    (lambda s: s.remote.prs[365].update(commits=2), "inventory"),
    (lambda s: s.remote.commits[365].append(s.remote.commits[365][0]), "inventory"),
    (lambda s: s.remote.page_headers.update({365: 'HTTP/2.0 200 OK\nLink: <https://evil.invalid/data?page=2>; rel="next"\n'}), "next-page"),
    (lambda s: s.remote.remote_fail.add("refs/heads/" + FIRST["branch"]), "remote branch"),
    (lambda s: s.remote.local_fail.add("refs/heads/" + FIRST["branch"]), "local branch"),
    (lambda s: s.remote.ancestry_fail.add((FIRST["merge_commit_sha"], LAST["head_sha"])), "unordered"),
    (lambda s: s.remote.ancestry_fail.add((next(iter(FIRST["fix_commits"].values())), FIRST["head_sha"])), "reviewed head"),
    (lambda s: s.receipt["issues"][0].update(pr_number=367, superseded_paths=[]), "superseded paths"),
    (lambda s: s.receipt["evidence_attributions"].pop(), "attribution set"),
    (lambda s: s.receipt["evidence_attributions"][0].update(sha256="a" * 64), "attribution set"),
    (lambda s: s.receipt["evidence_attributions"][0].update(pr_number=365), "producer is not"),
    (lambda s: s.remote.raw_changes.update({LAST["head_sha"]: ""}), "not produced"),
    (lambda s: s.remote.parents[LAST["head_sha"]].append("b" * 40), "non-merge"),
    (lambda s: s.remote.trees[LAST["head_sha"]].update({"src/fixed.py": "d" * 40}), "earlier reviewed fix"),
    (lambda s: s.remote.trees[LAST["head_sha"]].pop(s.receipt["goal_outputs"]["goal_evidence"]["path"]), "not versioned"),
])
def test_independent_multi_remote_gates_fail_closed(duf, change, message):
    change(duf)
    with pytest.raises(supervisor.SupervisorError, match=message):
        verify(duf)


def test_inherited_matching_blob_is_not_production(duf):
    item = duf.receipt["evidence_attributions"][0]
    blob = duf.remote.current_tree[item["path"]]
    duf.remote.raw_changes[item["commit_sha"]] = ""
    duf.remote.add_change(item["commit_sha"], item["path"], blob, blob)
    with pytest.raises(supervisor.SupervisorError, match="not produced"):
        verify(duf)


def test_extra_attribution_cannot_hide_lost_code_fix(duf):
    duf.receipt["evidence_attributions"].append({"path": "src/fixed.py", "sha256": "a" * 64,
                                               "pr_number": 367, "commit_sha": LAST["head_sha"]})
    with pytest.raises(supervisor.SupervisorError, match="attribution set"):
        verify(duf)


@pytest.mark.parametrize("attack", ["missing", "prior_stage", "orphan", "truncated", "duplicate_key", "symlink", "fifo"])
def test_registry_is_required_and_safe_not_receipt_self_assertion(duf, attack):
    path = duf.session / prs.REGISTRY_NAME
    records = [json.loads(line) for line in path.read_text().splitlines()]
    if attack == "missing":
        write_registry(duf, records[:1])
    elif attack in {"prior_stage", "orphan"}:
        records[0]["stage"] = 4 if attack == "prior_stage" else 5
        records[0]["goal_identity"]["start_step_index"] = 10 if attack == "prior_stage" else 999
        write_registry(duf, records)
    elif attack == "truncated":
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
    elif attack == "duplicate_key":
        path.write_bytes(path.read_bytes().replace(b'"pr_number": 365', b'"pr_number": 365, "pr_number": 365'))
    else:
        path.unlink()
        if attack == "symlink":
            path.symlink_to(duf.repo / "review.txt")
        else:
            __import__("os").mkfifo(path)
    with pytest.raises(supervisor.SupervisorError):
        verify(duf)


def test_completion_candidates_report_all_members_but_grant_no_closure(duf):
    supervisor.atomic_json(duf.runtime / "config.json", duf.config)
    duf.instance.save(duf.target, duf.ledger)
    supervisor.atomic_json(duf.session / "completion.json", duf.receipt)
    (duf.session / prs.REGISTRY_NAME).unlink()
    records = prs.collect_associations([duf.runtime]).records
    assert [item["pr_number"] for item in records] == [365, 367]
    assert len(duf.ledger["completed_stages"]) == 3  # only retained stage 4 reviews
    duf.receipt["prs"][0]["number"] = True
    supervisor.atomic_json(duf.session / "completion.json", duf.receipt)
    assert prs.collect_associations([duf.runtime]).records == []


@pytest.mark.parametrize("attack", ["missing", "reordered", "head", "merge", "extra"])
def test_public_closure_requires_exact_verified_member_list(duf, attack):
    proof = verify(duf)
    if attack == "missing":
        proof.pop("prs")
    elif attack == "reordered":
        proof["prs"].reverse()
    elif attack in {"head", "merge"}:
        proof["prs"][0]["head_sha" if attack == "head" else "merge_commit_sha"] = HEAD
    else:
        proof["prs"].append(copy.deepcopy(proof["prs"][0]))
    advanced = duf.instance.advance(duf.target, duf.ledger, duf.receipt, proof, "native_completed")
    duf.instance.save(duf.target, advanced)
    supervisor.atomic_json(duf.runtime / "config.json", duf.config)
    with pytest.raises(progress.ProgressError, match="ordered"):
        progress.collect_progress([duf.runtime])


def test_commit_change_parser_uses_real_git_and_refuses_rename_and_merge(tmp_path):
    repo = tmp_path / "git"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-b", "main")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "synthetic@example.invalid")
    (repo / "a.txt").write_text("real blob\n")
    git("add", "a.txt")
    git("commit", "-m", "test root")
    first = git("rev-parse", "HEAD")
    changes = supervisor.commit_changes(str(repo), first, supervisor.command)
    assert changes == {"a.txt": (None, ("100644", git("rev-parse", "HEAD:a.txt")))}
    git("mv", "a.txt", "b.txt")
    git("commit", "-m", "test rename")
    with pytest.raises(supervisor.SupervisorError, match="inventory|ambiguous"):
        supervisor.commit_changes(str(repo), git("rev-parse", "HEAD"), supervisor.command)
    git("checkout", "-b", "side", first)
    (repo / "side.txt").write_text("side\n")
    git("add", "side.txt")
    git("commit", "-m", "test side")
    git("checkout", "main")
    git("merge", "--no-ff", "side", "-m", "test merge")
    with pytest.raises(supervisor.SupervisorError, match="non-merge"):
        supervisor.commit_changes(str(repo), git("rev-parse", "HEAD"), supervisor.command)


def test_current_registry_binding_wins_over_same_stage_orphan(duf):
    path = duf.session / prs.REGISTRY_NAME
    records = [json.loads(line) for line in path.read_text().splitlines()]
    orphan = copy.deepcopy(records[0])
    orphan["goal_identity"]["start_step_index"] = 999
    write_registry(duf, [orphan, *records])
    assert verify(duf)["pr_number"] == 367


def test_prior_stage_orphan_cannot_be_borrowed_with_a_new_self_claim(duf):
    path = duf.session / prs.REGISTRY_NAME
    records = [json.loads(line) for line in path.read_text().splitlines()]
    orphan = copy.deepcopy(records[0])
    orphan.update(stage=2)
    orphan["goal_identity"]["start_step_index"] = 999
    write_registry(duf, [orphan, *records])
    with pytest.raises(supervisor.SupervisorError, match="another retained goal or stage"):
        verify(duf)


def test_missing_manifest_attribution_is_not_replaced_by_final_blob_presence(duf):
    duf.receipt["evidence_attributions"].pop(0)
    with pytest.raises(supervisor.SupervisorError, match="attribution set"):
        verify(duf)


def test_fix_bytes_must_survive_at_final_head(duf):
    duf.remote.trees[LAST["head_sha"]]["src/fixed.py"] = "e" * 40
    with pytest.raises(supervisor.SupervisorError, match="earlier reviewed fix"):
        verify(duf)


def test_pr_creation_before_goal_cannot_be_relabelled_by_registry(duf):
    duf.remote.prs[365]["created_at"] = "2026-10-24T00:00:00Z"
    with pytest.raises(supervisor.SupervisorError, match="closure window"):
        verify(duf)


def test_unintegrated_previous_merge_fails_despite_valid_member_proofs(duf):
    duf.remote.ancestry_fail.add((FIRST["merge_commit_sha"], LAST["head_sha"]))
    with pytest.raises(supervisor.SupervisorError, match="unordered"):
        verify(duf)


def test_fix_reverted_before_member_review_is_rejected(duf):
    bad = duf.remote.blob(b"old unfixed code\n")
    for head in (FIRST["head_sha"], LAST["head_sha"]):
        duf.remote.trees[head]["src/fixed.py"] = bad
    with pytest.raises(supervisor.SupervisorError, match="member reviewed head"):
        verify(duf)


def test_mixed_fix_executable_mode_must_survive(duf):
    for fix in (EARLY_FIX, LATER_FIX):
        duf.remote.raw_changes[fix] = duf.remote.raw_changes[fix].replace(
            f" 100644 {ZERO} {duf.remote.blob(b'correct code' + bytes([10]))}",
            f" 100755 {ZERO} {duf.remote.blob(b'correct code' + bytes([10]))}")
    duf.remote.modes[(FIRST["head_sha"], "src/fixed.py")] = "100755"
    with pytest.raises(supervisor.SupervisorError, match="final integration head"):
        verify(duf)
    duf.remote.modes[(LAST["head_sha"], "src/fixed.py")] = "100755"
    assert verify(duf)["pr_number"] == 367


def test_member_already_lost_executable_fix_is_rejected(duf):
    for fix in (EARLY_FIX, LATER_FIX):
        before = f":000000 100644 {ZERO} {duf.remote.blob(b'correct code' + bytes([10]))} A"
        after = before.replace("100644", "100755")
        duf.remote.raw_changes[fix] = duf.remote.raw_changes[fix].replace(before, after)
    with pytest.raises(supervisor.SupervisorError, match="member reviewed head"):
        verify(duf)


def test_real_duf_eight_path_supersession_is_explicit_and_necessary(duf):
    assert len(SOURCE["overlapping_review_paths"]) == 8
    assert verify(duf)["pr_number"] == 367
    duf.receipt["issues"][0]["superseded_paths"].pop()
    with pytest.raises(supervisor.SupervisorError, match="member reviewed head"):
        verify(duf)


@pytest.mark.parametrize("attack", ["unrelated_commit", "wrong_pr", "not_descendant", "not_changed", "reverted",
                                    "deleted", "mode", "unknown_path", "unchanged", "self", "redundant"])
def test_fix_supersession_never_grants_a_blanket_waiver(duf, attack):
    item = duf.receipt["issues"][0]["superseded_paths"][0]
    path = item["path"]
    if attack == "unrelated_commit":
        item["commit_sha"] = FIRST["head_sha"]
    elif attack == "wrong_pr":
        item["pr_number"] = 367
    elif attack == "not_descendant":
        duf.remote.ancestry_fail.add((EARLY_FIX, LATER_FIX))
    elif attack == "not_changed":
        duf.remote.raw_changes[LATER_FIX] = ""
        duf.remote.add_change(LATER_FIX, "src/fixed.py", ZERO, duf.remote.blob(b"correct code\n"))
    elif attack in {"reverted", "deleted", "mode"}:
        if attack == "reverted":
            duf.remote.trees[LAST["head_sha"]][path] = duf.remote.blob(b"reverted review\n")
        elif attack == "deleted":
            duf.remote.trees[LAST["head_sha"]].pop(path)
        else:
            duf.remote.modes[(LAST["head_sha"], path)] = "100755"
    elif attack == "unknown_path":
        item["path"] = "not-changed.txt"
    elif attack == "self":
        item["commit_sha"] = EARLY_FIX
    else:
        changes = supervisor.commit_changes(str(duf.repo), LATER_FIX, duf.remote)
        old, new = changes[path]
        replacement = new if attack == "unchanged" else old
        assert replacement is not None
        duf.remote.raw_changes[LATER_FIX] = duf.remote.raw_changes[LATER_FIX].replace(
            f"{old[1]} {new[1]} M\0{path}\0", f"{replacement[1]} {replacement[1]} M\0{path}\0")
    with pytest.raises(supervisor.SupervisorError):
        verify(duf)


def test_evidence_override_must_descend_from_the_affected_fix(duf):
    attribution = duf.receipt["evidence_attributions"][0]
    path = attribution["path"]
    duf.remote.add_change(EARLY_FIX, path, ZERO, duf.remote.blob(b"original manifest\n"))
    producer = "9" * 40
    attribution["commit_sha"] = producer
    duf.remote.parents[producer] = [HEAD]
    duf.remote.raw_changes[producer] = ""
    duf.remote.add_change(producer, path, ZERO, duf.remote.current_tree[path])
    duf.remote.commits[367].append({"sha": producer, "commit": {"committer": {"date": LAST["created_at"]}}})
    duf.remote.prs[367]["commits"] += 1
    duf.remote.ancestry_fail.add((FIRST["merge_commit_sha"], producer))
    with pytest.raises(supervisor.SupervisorError, match="does not descend"):
        verify(duf)


def test_same_pr_evidence_override_requires_actual_later_producer(duf):
    attribution = duf.receipt["evidence_attributions"][1]
    path = attribution["path"]
    duf.remote.add_change(EARLY_FIX, path, ZERO, duf.remote.blob(b"original payload\n"))
    producer = "8" * 40
    attribution["commit_sha"] = producer
    duf.remote.parents[producer] = [HEAD]
    duf.remote.raw_changes[producer] = ""
    duf.remote.add_change(producer, path, ZERO, duf.remote.current_tree[path])
    duf.remote.commits[365].append({"sha": producer, "commit": {"committer": {"date": FIRST["created_at"]}}})
    duf.remote.prs[365]["commits"] += 1
    duf.remote.ancestry_fail.add((EARLY_FIX, producer))
    with pytest.raises(supervisor.SupervisorError, match="does not descend"):
        verify(duf)


def test_issue_fix_cannot_be_assigned_to_the_evidence_repair_pr(duf):
    duf.receipt["issues"][-1]["pr_number"] = 367
    with pytest.raises(supervisor.SupervisorError, match="not closed with a fix"):
        verify(duf)


def test_fix_deletion_requires_exact_absence_at_both_reviewed_heads(duf):
    path = "src/obsolete.py"
    old = duf.remote.blob(b"obsolete unsafe content\n")
    duf.remote.raw_changes[EARLY_FIX] += f":100644 000000 {old} {ZERO} D\0{path}\0"
    assert verify(duf)["pr_number"] == 367
    duf.remote.trees[LAST["head_sha"]][path] = old
    with pytest.raises(supervisor.SupervisorError, match="earlier reviewed fix"):
        verify(duf)


def test_evidence_supersession_cannot_also_claim_issue_path_override(duf):
    item = duf.receipt["evidence_attributions"][0]
    duf.remote.add_change(EARLY_FIX, item["path"], ZERO, duf.remote.blob(b"original evidence\n"))
    duf.receipt["issues"][0]["superseded_paths"].append(
        {"path": item["path"], "pr_number": 365, "commit_sha": LATER_FIX})
    with pytest.raises(supervisor.SupervisorError, match="non-evidence changed paths"):
        verify(duf)


def test_successor_that_changes_path_still_needs_its_own_verified_issue_fix(duf):
    item = duf.receipt["issues"][0]["superseded_paths"][0]
    path = item["path"]
    old, new = supervisor.commit_changes(str(duf.repo), LATER_FIX, duf.remote)[path]
    assert old is not None and new is not None
    item["commit_sha"] = FIRST["head_sha"]
    duf.remote.add_change(FIRST["head_sha"], path, old[1], new[1])
    with pytest.raises(supervisor.SupervisorError, match="another descendant attributed fix"):
        verify(duf)


def test_unnecessary_supersession_cannot_hide_an_unchanged_original_claim(duf):
    duf.receipt["issues"][0]["superseded_paths"].append(
        {"path": "src/fixed.py", "pr_number": 365, "commit_sha": LATER_FIX})
    with pytest.raises(supervisor.SupervisorError, match="unnecessary"):
        verify(duf)
