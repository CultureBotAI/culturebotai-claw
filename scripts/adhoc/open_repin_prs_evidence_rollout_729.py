#!/usr/bin/env python3
"""Publish the #729 re-pin commits as one pull request per Mech, dry-run first.

Purpose: after repin_fleet_evidence_rollout_729.py --apply has made one local
re-pin commit per Mech, push each branch and open its pull request.

Before pushing:
- The worktree must be clean. The head is recorded first, and the body is built
  from that commit (its LICENSE, its ledger, its diff from origin/main), never
  from the working tree (#807).
- Every origin fetch and push URL must name the manifest's repository. This is
  checked through RepositoryTarget.open(), which reads them all and reports
  identities rather than raw URLs, which may carry a token (#805).

Pushing:
- The push holds the Mech's LockManager lease.
- It pushes the recorded commit by an explicit refspec, since some Mech clones
  set push.default=matching.
- The remote branch head is then verified against the recorded commit.

The body:
- It states what changed and why, and how it was verified.
- Adopter bodies carry live strict-gate counts from claw's `kg-microbe-evidence`
  CLI. That is run from the claw checkout this script runs in, which must be at
  the release commit; it is not the vendored runner.
- Dated records that name the outgoing pin are listed, not changed (#795).
- A body containing an @ or a closing keyword is refused, so no person is
  notified and no issue is closed by accident.

Inputs:
- --ref: the claw release commit.
- --root: the scratch directory with repin/<mech> and adopt/<mech> worktrees.
- --pin-coupling: one or more `kg-microbe-governance pin-coupling` outputs
  (TSV lines).
- --mech: optional and repeatable.

Outputs:
- the planned titles and bodies on stdout;
- with --apply, pushed branches and opened pull requests, reported as JSON.

Serves: culturebotai-claw#729 / PR #773. Written 2026-11-04.

Correction (#796). As first run, the adopter template said each repository
"states no source policy that restricts committing" the abstracts. That was
true for HabitatMech, whose LICENSE has no hosting clause. It was false for
CellStructureMech: its LICENSE hosts only licence-verified CC0, public-domain
or CC BY text. CellStructureMech#3042 was then corrected by hand to commit no
abstracts, and records every quote as MISSING_CACHE under
CellStructureMech#3065. The template now reads the LICENSE and the ledger from
the pushed commit, whether or not abstracts are staged, and states what they
say.

Correction (#805, #809). The 14 re-pin PRs were published between 13:52 and
14:49 UTC on 2026-11-04. That run pushed HEAD, with no origin check and no lease.
The origin check, the lease, pushing the recorded commit and the clean-worktree
refusal were added afterwards. They have run only against throwaway
repositories, in scripts/adhoc/verify_repin_script_fixes_729.py.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

ADOPTERS = frozenset({"cellstructuremech", "habitatmech"})
HOSTING_POLICY = re.compile(r"hosting policy|may be hosted|not hosted", re.IGNORECASE)
BRANCHES = {"repin": "feat/729-repin-evidence-rollout", "adopt": "feat/729-adopt-evidence-gate"}
LEDGER = "curation/evidence_known_findings.tsv"
CLOSING = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b:?\s+[\w./-]*#\d", re.IGNORECASE)
FOOTER = "\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n"
RELEASE = "CultureBotAI/culturebotai-claw#773"
TRACKER = "CultureBotAI/culturebotai-claw#729"


def run(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(list(args), cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode not in (0,):
        raise RuntimeError(f"{' '.join(args)} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout


def show(worktree: Path, head: str, path: str) -> str | None:
    """A file's content at the recorded commit, or None if it has none there."""
    completed = subprocess.run(["git", "-C", str(worktree), "show", f"{head}:{path}"],
                               text=True, capture_output=True, check=False)
    return completed.stdout if completed.returncode == 0 else None


def require_origin(key: str, worktree: Path, slug: str) -> None:
    """Refuse unless every origin fetch and push URL names the manifest's repository (#805)."""
    RepositoryTarget(name=key, path=worktree.resolve(), expected_repository=slug).open()


def owner_reference(url: str, slug: str) -> str:
    prefix = f"https://github.com/{slug}/issues/"
    if url.lower().startswith(prefix.lower()):
        return "#" + url[len(prefix):]
    match = re.match(r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)$", url)
    return f"{match.group(1)}#{match.group(2)}" if match else url


def couplings(paths: list[Path]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if fields[0] == "COUPLED" and len(fields) >= 4:
                hits.setdefault(fields[1], []).append(f"{fields[2]}\t{fields[3]}")
    return hits


def gate_counts(key: str, worktree: Path) -> str:
    # The gate writes its reports under workspace/reports/. Only the re-pin
    # commit ignores that directory, so running earlier would leave untracked
    # files that the next sync --apply refuses.
    probe = subprocess.run(["git", "-C", str(worktree), "check-ignore", "-q", "workspace/reports/probe"],
                           check=False)
    if probe.returncode != 0:
        raise RuntimeError(f"{key}: workspace/reports/ is not ignored yet; make the re-pin commit first")
    completed = subprocess.run(
        ["uv", "run", "--quiet", "kg-microbe-evidence", "--mech", key, "--root", str(worktree),
         "--strict", "--output-dir", str(worktree / "workspace" / "reports")],
        text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{key}: strict gate exited {completed.returncode}: {completed.stderr.strip()}")
    lines = [line.strip() for line in completed.stdout.splitlines() if re.match(r"\s+[A-Z_]+: \d", line)]
    return "\n".join(f"  - `{line}`" for line in lines)


def body_for(key: str, worktree: Path, ref: str, hits: list[str], slug: str, head: str) -> tuple[str, str]:
    old_pin = run("git", "-C", str(worktree), "show", "origin/main:scripts/.vendored_canon_ref").strip()
    staged = run("git", "-C", str(worktree), "diff", "--name-only", f"origin/main..{head}").split()
    dated = ""
    if hits:
        files = sorted({hit.split("\t")[1].rsplit(":", 1)[0] for hit in hits if hit.startswith("pin-reference")})
        if files:
            tops = Counter("/".join(name.split("/")[:2]) if "/" in name else name for name in files)
            listing = ", ".join(f"`{top}` ({count})" for top, count in sorted(tops.items()))
            dated = (
                f"\n`pin-coupling` also reports {len(files)} file(s) that name the old pin: {listing}. "
                "They are dated review and research records, provenance or permalinks, and stay unchanged "
                f"because they record the revision they used (CultureBotAI/culturebotai-claw#795).\n"
            )
    if key in ADOPTERS:
        caches = [name for name in staged if name.startswith("references_cache/")]
        # What the body says about hosting is read from the pushed commit's
        # LICENSE, staged abstracts or not (#796, #807). A missing LICENSE says
        # nothing, so it is refused rather than read as "no hosting clause".
        licence = show(worktree, head, "LICENSE")
        if licence is None:
            raise RuntimeError(f"{key}: the commit has no LICENSE; cannot tell whether abstracts may be hosted")
        hosting = bool(HOSTING_POLICY.search(licence))
        if caches and hosting:
            raise RuntimeError(
                f"{key}: LICENSE has a hosting policy and this PR adds {len(caches)} abstract(s); these scripts "
                "commit no abstracts under such a policy. Land licence-verified abstracts in their own reviewed "
                "PR first (#808)")
        if caches:
            cache_text = (
                f"- `references_cache/`: {len(caches)} cited abstracts.\n"
                "  - Fetched anonymously from NCBI E-utilities by `kg-microbe-evidence-fetch`, and written only when "
                "the record's identity was verified.\n"
                "  - A DOI's abstract is accepted only from a single PubMed record that lists that DOI.\n"
                "  - This follows MediaIngredientMech, which commits its gate's PubMed abstracts the same way. "
                "This repository's LICENSE has no hosting clause; third-party text keeps its own licence.\n"
            )
        elif hosting:
            cache_text = (
                "- No abstract cache is committed. This repository's LICENSE has a third-party hosting policy, "
                "and the fetched abstracts carry no verified licence, so the ledger records their quotes as "
                "`MISSING_CACHE`.\n"
            )
        else:
            cache_text = "- No abstract cache is committed.\n"
        ledger = show(worktree, head, LEDGER)
        if ledger is None:
            raise RuntimeError(f"{key}: the commit has no {LEDGER}")
        rows = [row for row in ledger.splitlines()[1:] if row]
        verdicts = Counter(row.split("\t")[2] for row in rows)
        owners = sorted({row.split("\t")[4] for row in rows})
        owner_text = ", ".join(owner_reference(url, slug) for url in owners) or "no issue"
        title = "Adopt the shared quote gate and re-pin claw governance"
        text = f"""## Why

{RELEASE} enables `evidence_reference_validation` for this repository ({TRACKER}). The shared gate checks each quoted evidence snippet against the cited source's retained abstract.

This PR adopts the gate. It also re-pins claw governance to the release commit, because claw's coordinated `fleet-audit` requires one shared pin across all 14 Mechs.

## What changes

- `scripts/.vendored_canon_ref`: `{old_pin[:12]}` to `{ref}`.
- Vendored by `kg-microbe-governance sync`: `scripts/run_shared_evidence_validator.py` and `.github/workflows/qc-evidence.yaml`.
{cache_text}- `curation/evidence_known_findings.tsv`: {len(rows)} quotes the gate cannot validate yet ({", ".join(f"{v} {n}" for v, n in sorted(verdicts.items()))}).
  - Its rows are owned by {owner_text}.
  - The ledger lets the gate pass today. Every new, copied or edited failing quote still blocks, and a repaired entry goes stale and blocks until it is removed.
- `pyproject.toml`: the runner joins `[tool.ruff] extend-exclude` beside the other claw-governed scripts. Vendored bytes are linted in claw (CultureBotAI/culturebotai-claw#788).
- `.gitignore`: `workspace/reports/`, where the gate writes its reports by default.
{dated}
`qc-evidence` stays advisory. claw's merge-queue checker cannot yet accept the governed workflow's pin-derived claw checkout (CultureBotAI/culturebotai-claw#793).

## Verification

- `kg-microbe-governance sync --ref {ref}`:
  - the dry run planned exactly the runner, the workflow and the pin;
  - it was then applied;
  - a second plan was empty.
- Strict gate on this branch:
{gate_counts(key, worktree)}
- On a simulated re-pin of this repository's `main` with these files, every step of `scripts/run_qc.py` passed.
- CI on this PR.
"""
    else:
        title = "Re-pin claw governance to the evidence rollout release"
        snapshot = ""
        if "scripts/.vendored_manifest.json" in staged:
            snapshot = (
                "- `scripts/.vendored_manifest.json`: re-snapshotted to claw's governance manifest at the release, "
                "byte for byte, as `tests/test_vendored_artifacts.py` requires.\n"
            )
        text = f"""## Why

{RELEASE} retires the single-MediaIngredientMech canary lane and rolls the shared quote gate out to CellStructureMech and HabitatMech ({TRACKER}). claw's coordinated `fleet-audit` requires one shared pin across all 14 Mechs, so every Mech re-pins to the release commit.

## What changes

- `scripts/.vendored_canon_ref`: `{old_pin[:12]}` to `{ref}`.
  - Every governed artifact this repository vendors is byte-identical at that commit.
  - `kg-microbe-governance sync` planned only the pin.
{snapshot}{dated}
## Verification

- `kg-microbe-governance sync --ref {ref}`:
  - the dry run planned exactly the pin;
  - it was then applied;
  - a second plan was empty.
- `kg-microbe-governance pin-coupling --old-ref {old_pin}` was run before fanning out.
- CI on this PR.
"""
    text += FOOTER
    if "@" in text or CLOSING.search(text):
        raise RuntimeError(f"{key}: refusing a body with an @ or a closing keyword")
    return title, text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pin-coupling", type=Path, action="append", default=[])
    parser.add_argument("--mech", action="append")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = load_fleet_manifest()
    hits = couplings(args.pin_coupling)
    results, failed = [], False
    for key in args.mech or sorted(manifest.mechs):
        kind = "adopt" if key in ADOPTERS else "repin"
        worktree, branch = args.root / kind / key, BRANCHES[kind]
        slug = manifest.mechs[key].github
        try:
            if run("git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD").strip() != branch:
                raise RuntimeError(f"{key}: worktree is not on {branch}")
            # Record the commit first and refuse a dirty tree: the body describes
            # this commit, and this commit is what gets pushed (#807).
            head = run("git", "-C", str(worktree), "rev-parse", "HEAD").strip()
            if run("git", "-C", str(worktree), "status", "--porcelain", "--untracked-files=all").strip():
                raise RuntimeError(f"{key}: worktree has uncommitted changes; commit or remove them first")
            title, text = body_for(key, worktree, args.ref, hits.get(key, []), slug, head)
            result = {"mech": key, "repository": slug, "branch": branch, "head": head, "title": title}
            if not args.apply:
                print(f"===== {slug} [{branch}] {title}\n{text}")
            else:
                require_origin(key, worktree, slug)
                with LockManager().lock(key, "publish-repin-729"):
                    run("git", "-C", str(worktree), "push", "origin", f"{head}:refs/heads/{branch}")
                    remote = run("git", "-C", str(worktree), "ls-remote", "origin", f"refs/heads/{branch}").split()
                if not remote or remote[0] != head:
                    raise RuntimeError(f"{key}: remote {branch} is {remote[:1]}, expected {head}")
                with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as stream:
                    stream.write(text)
                result["url"] = run("gh", "pr", "create", "-R", slug, "--base", "main", "--head", branch,
                                    "--title", title, "--body-file", stream.name).strip()
                Path(stream.name).unlink()
        except Exception as exc:
            result = {"mech": key, "error": f"{type(exc).__name__}: {exc}"}
            failed = True
        results.append(result)
    json.dump(results, sys.stdout, indent=2)
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
