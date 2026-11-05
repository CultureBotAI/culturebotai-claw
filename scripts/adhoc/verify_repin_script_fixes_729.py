#!/usr/bin/env python3
"""Verify the fixes to the rollout's two provenance scripts, offline.

Purpose: check the #796 and #804-#808 fixes in
open_repin_prs_evidence_rollout_729.py and repin_fleet_evidence_rollout_729.py
against throwaway git repositories, inside a sandbox that cannot reach GitHub
or any provider:
- ssh is a stand-in that serves only local bare repositories under a fake
  "github" directory, and refuses anything else;
- https goes to a dead proxy;
- `gh` is intercepted in-process, with a failing stub on PATH as a backstop;
- the lease directory is a throwaway OPENCLAW_WORKSPACE;
- gate_counts and the governance sync are stubbed.
Adapted from the PR #803 reviewers' reproductions.

Checks:
  Publish template (#796, #807)
    - The LICENSE and the ledger are read from the recorded commit, not the
      working tree.
    - A hosting policy is stated when present, and staged abstracts are then
      refused.
    - Ledger owners come from the ledger.
    - A missing LICENSE is refused.
  Re-pin adopter path (#804, #808)
    - The commit message reads the ledger owner.
    - Untracked abstracts are refused under a hosting policy; abstracts
      already tracked are not.
    - A missing LICENSE is refused.
    - Only existing prepared paths are staged.
  Publishing (#805, #807)
    - Every origin fetch and push URL must name the manifest's repository.
    - Refusals never echo a raw URL.
    - A dirty worktree is refused.
    - The push holds the lease and pushes the recorded commit, even if HEAD
      moves.

Inputs: argv[1], the claw directory holding scripts/adhoc; argv[2], an empty
scratch directory; argv[3] and argv[4], CellStructureMech's LICENSE and
ledger; argv[5] and argv[6], HabitatMech's LICENSE and ledger. Pass the files
from each Mech's origin/main.
Outputs: one PASS/FAIL line per check; a nonzero exit on any failure.
Serves: culturebotai-claw#796, #804-#808 / PR #803. Written 2026-11-04.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

claw, scratch, csm_licence, csm_ledger, hm_licence, hm_ledger = (Path(a).resolve() for a in sys.argv[1:7])
OLD = "a5d562962c75a2ad9efd8160b548df5944315422"
NEW = "76c1ebeea3fc7f80bf1abe044688f298f390cfac"
REPIN_BRANCH, ADOPT_BRANCH = "feat/729-repin-evidence-rollout", "feat/729-adopt-evidence-gate"
failures = 0

# ---------------------------------------------------------------- sandbox --
sandbox = scratch / "sandbox"
shutil.rmtree(sandbox, ignore_errors=True)
(sandbox / "bin").mkdir(parents=True)
(sandbox / "ws").mkdir()
fake_ssh = sandbox / "fake_ssh.sh"
fake_ssh.write_text(r"""#!/bin/sh
for last in "$@"; do :; done
case "$last" in
  "git-upload-pack '"*|"git-receive-pack '"*) ;;
  *) echo "fake-ssh: refusing: $last" >&2; exit 97 ;;
esac
verb=${last%% *}; path=${last#* \'}; path=${path%\'}; path=${path#/}
lower=$(printf '%s' "$path" | tr 'A-Z' 'a-z'); lower=${lower%.git}
dir="$FAKE_GITHUB_ROOT/$lower.git"
[ -d "$dir" ] || { echo "fake-ssh: no fake repository for $path" >&2; exit 98; }
exec git "${verb#git-}" "$dir"
""")
gh_stub = sandbox / "bin" / "gh"
gh_stub.write_text("#!/bin/sh\necho \"escaped gh $*\" >&2\nexit 99\n")
for script in (fake_ssh, gh_stub):
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
dead = "http://127.0.0.1:9"
os.environ.update({
    "PATH": f"{sandbox / 'bin'}{os.pathsep}{os.environ['PATH']}",
    "GIT_SSH_COMMAND": str(fake_ssh), "GIT_SSH_VARIANT": "simple", "GIT_ALLOW_PROTOCOL": "file:ssh",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
    "https_proxy": dead, "HTTPS_PROXY": dead, "http_proxy": dead, "HTTP_PROXY": dead,
    "no_proxy": "", "NO_PROXY": "", "OPENCLAW_WORKSPACE": str(sandbox / "ws"),
})


def check(name: str, condition: bool, detail: object = "") -> None:
    global failures
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  -- ' + str(detail)[:400]}")
    failures += not condition


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def identify(repo: Path) -> None:
    git(repo, "config", "user.email", "test")
    git(repo, "config", "user.name", "test")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, claw / "scripts/adhoc" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def adopter_repo(path: Path, licence: Path | None, ledger: Path, cache: str | None) -> Path:
    """An adopter-shaped repo; cache is None, 'staged' (on the branch) or 'tracked' (on main)."""
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    identify(path)
    (path / "scripts").mkdir()
    (path / "scripts/.vendored_canon_ref").write_text(OLD + "\n")
    if licence is not None:
        shutil.copyfile(licence, path / "LICENSE")
    if cache == "tracked":
        (path / "references_cache").mkdir()
        (path / "references_cache/PMID_2.md").write_text("# PMID:2\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "base")
    git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(path, "checkout", "-qb", ADOPT_BRANCH)
    (path / "scripts/.vendored_canon_ref").write_text(NEW + "\n")
    (path / "curation").mkdir()
    shutil.copyfile(ledger, path / "curation/evidence_known_findings.tsv")
    if cache == "staged":
        (path / "references_cache").mkdir()
        (path / "references_cache/PMID_1.md").write_text("# PMID:1\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "adopt")
    return path


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


# ------------------------------------------------- publish template --------
publish = load("open_repin_prs_evidence_rollout_729")
publish.gate_counts = lambda key, path: "  - `stub`"
CSM, HM = "CultureBotAI/CellStructureMech", "CultureBotAI/HabitatMech"

repo = adopter_repo(scratch / "csm-nocache", csm_licence, csm_ledger, None)
_, body = publish.body_for("cellstructuremech", repo, NEW, [], CSM, head(repo))
check("template: CSM without caches states the hosting policy",
      "LICENSE has a third-party hosting policy" in body and "no hosting clause" not in body, body)
check("template: CSM owner is read from the ledger (#3065, not #2873)", "owned by #3065" in body and "#2873" not in body, body)
check("template: CSM without caches claims no fetched abstracts", "Fetched anonymously" not in body, body)
# The body describes the recorded commit: an uncommitted owner edit must not reach it.
ledger_file = repo / "curation/evidence_known_findings.tsv"
ledger_file.write_text(ledger_file.read_text().replace("/issues/3065", "/issues/9999"))
(repo / "LICENSE").unlink()
try:
    _, body = publish.body_for("cellstructuremech", repo, NEW, [], CSM, head(repo))
except RuntimeError as exc:
    body = f"RuntimeError: {exc}"
check("template: reads LICENSE and ledger from the commit, not the working tree",
      "owned by #3065" in body and "#9999" not in body and "hosting policy" in body, body)

repo = adopter_repo(scratch / "csm-cache", csm_licence, csm_ledger, "staged")
try:
    publish.body_for("cellstructuremech", repo, NEW, [], CSM, head(repo))
    check("template: CSM with a staged abstract is refused", False, "no RuntimeError")
except RuntimeError as exc:
    check("template: CSM with a staged abstract is refused", "hosting policy" in str(exc), exc)

repo = adopter_repo(scratch / "hm-cache", hm_licence, hm_ledger, "staged")
_, body = publish.body_for("habitatmech", repo, NEW, [], HM, head(repo))
check("template: HM with abstracts states no hosting clause and its own owner",
      "no hosting clause" in body and "owned by #2284" in body, body)

repo = adopter_repo(scratch / "nolicence", None, hm_ledger, None)
try:
    publish.body_for("habitatmech", repo, NEW, [], HM, head(repo))
    check("template: an adopter with no LICENSE is refused", False, "no RuntimeError")
except RuntimeError as exc:
    check("template: an adopter with no LICENSE is refused", "no LICENSE" in str(exc), exc)

# ------------------------------------------------- re-pin adopter path -----
repin = load("repin_fleet_evidence_rollout_729")
repo = adopter_repo(scratch / "csm-msg", csm_licence, csm_ledger, None)
text = repin.message("cellstructuremech", NEW, OLD, ["curation/evidence_known_findings.tsv"], repo)
check("re-pin: message names the ledger owner and claims no abstracts",
      "issues/3065" in text and "#2873" not in text and "cited PubMed abstracts" not in text, text)
check("re-pin: hosting-policy detection separates CSM from HM",
      repin.has_hosting_policy(repo) and not repin.has_hosting_policy(scratch / "hm-cache"))
repin.sync_repository = lambda *args, **kwargs: []  # no network; the staging step is under test


def prepare_for_apply(path: Path, licence: Path | None, cache: str | None) -> Path:
    """Main holds the pin; the ledger, and an abstract when cache='untracked', are untracked."""
    repo = adopter_repo(path, licence, csm_ledger, "tracked" if cache == "tracked" else None)
    git(repo, "reset", "-q", "--hard", "origin/main")
    (repo / "curation").mkdir(exist_ok=True)
    shutil.copyfile(csm_ledger, repo / "curation/evidence_known_findings.tsv")
    if cache == "untracked":
        (repo / "references_cache").mkdir(exist_ok=True)
        (repo / "references_cache/PMID_1.md").write_text("# PMID:1\n")
    return repo


def apply_outcome(repo: Path) -> tuple[str, str]:
    before = head(repo)
    try:
        repin.apply_one("cellstructuremech", repo, NEW, {"old_pin": OLD})
        error = ""
    except Exception as exc:  # the step after staging fails on the stub repo; only the staging is examined
        error = f"{type(exc).__name__}: {exc}"
    staged = git(repo, "log", "--format=%s", f"{before}..HEAD").strip()
    return error, staged


repo = prepare_for_apply(scratch / "apply-untracked", csm_licence, "untracked")
error, staged = apply_outcome(repo)
check("re-pin: untracked abstracts under a hosting policy are refused before staging",
      "hosting policy" in error and not staged, (error, staged))
repo = prepare_for_apply(scratch / "apply-tracked", csm_licence, "tracked")
error, staged = apply_outcome(repo)
check("re-pin: abstracts already on main are not refused; the ledger is staged",
      "hosting policy" not in error and "Stage the quote gate" in staged, (error, staged))
repo = prepare_for_apply(scratch / "apply-ledger-only", csm_licence, None)
error, staged = apply_outcome(repo)
check("re-pin: with no abstracts only the ledger is staged",
      "Stage the quote gate" in staged
      and git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["curation/evidence_known_findings.tsv"],
      (error, staged))
repo = prepare_for_apply(scratch / "apply-nolicence", None, None)
error, staged = apply_outcome(repo)
check("re-pin: an adopter with no LICENSE is refused", "no LICENSE" in error and not staged, (error, staged))

# ------------------------------------------------- publishing --------------
real_run = publish.run
gh_calls: list[list[str]] = []


def guarded_run(*args, cwd=None):
    if args and args[0] == "gh":
        gh_calls.append(list(args[:4]))
        return "https://example.invalid/fake-pr\n"
    return real_run(*args, cwd=cwd)


publish.run = guarded_run
real_require_origin = publish.require_origin


def publish_case(name: str, configure=None, move_head: bool = False, dirty: bool = False):
    case = scratch / f"publish-{name}"
    shutil.rmtree(case, ignore_errors=True)
    fake_root = case / "github"
    os.environ["FAKE_GITHUB_ROOT"] = str(fake_root)
    manifest_repo, foreign = fake_root / "culturebotai/aimech.git", case / "foreign.git"
    for bare in (manifest_repo, foreign):
        bare.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = case / "seed"
    subprocess.run(["git", "clone", "-q", str(manifest_repo), str(seed)], check=True, capture_output=True)
    identify(seed)
    (seed / "scripts").mkdir()
    (seed / "scripts/.vendored_canon_ref").write_text(OLD + "\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "base")
    git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
    work = case / "root/repin/aimech"
    subprocess.run(["git", "clone", "-q", "git@github.com:CultureBotAI/AIMech.git", str(work)],
                   check=True, capture_output=True)
    identify(work)
    git(work, "checkout", "-qb", REPIN_BRANCH)
    (work / "scripts/.vendored_canon_ref").write_text(NEW + "\n")
    git(work, "commit", "-qam", "re-pin")
    recorded = head(work)
    marker = case / "lease.txt"
    hook = work / ".git/hooks/pre-push"
    hook.write_text(f"#!/bin/sh\nif [ -f \"$OPENCLAW_WORKSPACE/locks/aimech.lock\" ]; then echo held; "
                    f"else echo missing; fi > '{marker}'\n")
    hook.chmod(0o755)
    if configure:
        configure(work, foreign)
    if dirty:
        (work / "stray.txt").write_text("uncommitted\n")

    def moving_require_origin(key, worktree, slug):
        real_require_origin(key, worktree, slug)
        if move_head:  # HEAD moves after the commit was recorded
            (worktree / "scripts/later.txt").write_text("later\n")
            git(worktree, "add", "-A")
            git(worktree, "commit", "-qm", "later")

    publish.require_origin = moving_require_origin
    gh_calls.clear()
    sys.argv = ["open_repin", "--ref", NEW, "--root", str(case / "root"), "--mech", "aimech", "--apply"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = publish.main()
    result = json.loads(out.getvalue())[0]

    def branch_at(bare: Path) -> str:
        found = subprocess.run(["git", "--git-dir", str(bare), "rev-parse", "--verify", "-q",
                                f"refs/heads/{REPIN_BRANCH}"], capture_output=True, text=True)
        return found.stdout.strip()

    return {"status": status, "result": result, "recorded": recorded, "head": head(work),
            "manifest_branch": branch_at(manifest_repo), "foreign_branch": branch_at(foreign),
            "lease": marker.read_text().strip() if marker.exists() else "", "gh": list(gh_calls)}


run = publish_case("happy", move_head=True)
check("publish: pushes the recorded commit even after HEAD moves",
      run["status"] == 0 and run["manifest_branch"] == run["recorded"] != run["head"], run)
check("publish: the lease is held during the push", run["lease"] == "held", run)
check("publish: one gh call on success, none escaped", len(run["gh"]) == 1, run)


def second_url(work: Path, foreign: Path) -> None:
    git(work, "config", "--add", "remote.origin.url", str(foreign))


def second_pushurl(work: Path, foreign: Path) -> None:
    git(work, "config", "--add", "remote.origin.pushurl", "git@github.com:CultureBotAI/AIMech.git")
    git(work, "config", "--add", "remote.origin.pushurl", str(foreign))


def foreign_pushurl(work: Path, foreign: Path) -> None:
    git(work, "config", "remote.origin.pushurl", str(foreign))


def token_url(work: Path, foreign: Path) -> None:
    git(work, "config", "remote.origin.url", "https://x-access-token:SECRET-TOKEN@github.com/CultureBotAI/Other.git")


for name, configure in (("second-url", second_url), ("second-pushurl", second_pushurl),
                        ("foreign-pushurl", foreign_pushurl)):
    run = publish_case(name, configure)
    check(f"publish: refuses an origin with a {name}, before any push or gh call",
          run["status"] == 1 and not run["manifest_branch"] and not run["foreign_branch"] and not run["gh"], run)
run = publish_case("token", token_url)
check("publish: a refusal never echoes a token-bearing URL",
      run["status"] == 1 and "SECRET-TOKEN" not in run["result"].get("error", "") and not run["gh"], run)
run = publish_case("dirty", dirty=True)
check("publish: a dirty worktree is refused before any push",
      run["status"] == 1 and "uncommitted" in run["result"].get("error", "") and not run["manifest_branch"], run)

sys.exit(1 if failures else 0)
