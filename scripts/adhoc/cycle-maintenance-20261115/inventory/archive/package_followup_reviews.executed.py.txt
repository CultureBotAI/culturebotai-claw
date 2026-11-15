"""Package public source-review summaries/helpers for PRs 1138/1243; 2026-11-15.
Inputs: retained private review root. Outputs: narrow public summaries/helpers and
private Markdown review reports. Existing observations are read; no tests,
network operations, generation, runtime actions or candidate changes are performed.
Related fixes: issues 1252, 1238-1242, 1244-1245 and 1249. Original evidence stays intact.
"""
import argparse,hashlib,json,re
from pathlib import Path

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
def load(path):return json.loads(path.read_text())
def safe(text):
    assert not re.search(r"/(?:Users|home)/[A-Za-z0-9]",text)
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",text)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--reviews-root",required=True,type=Path)
    a=p.parse_args();private=a.reviews_root.resolve();public=Path(__file__).resolve().parent
    for number,subdir,helpers in ((1138,"1138/rereview",["review_closeout.py"]),(1243,"1243",["review_source.py","counterfactuals.py"])):
        root=private/subdir;receipts=root/("verified-receipts" if number==1138 else "receipts")
        proof=load(receipts/"source-head-proof.json");pr=load(receipts/"pr-final.json")
        assert pr["headRefOid"]==proof["head"]
        target=public/str(number);target.mkdir(exist_ok=True)
        copied=[]
        for helper in helpers:
            original=root/helper;text=original.read_text();safe(text)
            (target/helper).write_bytes(original.read_bytes())
            copied.append({"path":str((target/helper).relative_to(public)),"original_sha256":digest(original),"packaged_sha256":digest(target/helper),"packaging_edits":[]})
        summary={"repository":"CultureBotAI/culturebotai-claw","pull_request":number,"reviewed_head":proof["head"],"actual_main":proof["main"],"prospective_merge_tree":proof["prospective_merge_tree"],"source_verdict":"no_verified_blocking_source_finding","findings":[],"runtime_authority_granted":False,"runtime_operations_performed":False,"helpers":copied,"source_proof_sha256":digest(receipts/"source-head-proof.json"),"checks":[{"name":c["name"],"status":c["status"],"conclusion":c["conclusion"],"url":c["detailsUrl"]} for c in pr["statusCheckRollup"]],"validation_artifacts":{name:digest(receipts/name) for name in ("pytest.log","pr-final.json")}}
        if number==1138:
            live=load(receipts/"live-verification.json")
            summary.update(issue=1252,tests={"passed":14,"skipped":0,"included_mutations":2},candidate_sha256=proof["candidate_sha256"],release_source=live["canonical_publication"]["source_commit"],live_verification_sha256=digest(receipts/"live-verification.json"),notes=["All four historical candidate files preserved byte-for-byte; five additions only.","All 1560 original tracked file bytes and modes preserved; all 18 release payloads independently verified.","Public immutable Assay helper reference matched its declared SHA256.","Historical and release fleet manifest hashes differ; loader and candidate payload sources match.","Missing local current-main and historical objects caused initial fail-closed attempts; objects were fetched and fresh verification passed. Earlier evidence retained.","Current hosted public-fleet failure is four obsolete Assay/Cofactor INCOMPLETE_CONSUMERS assertions on the old base; 45 tests passed. Final green gate still required.","No active pin, hook, runtime or candidate-payload change; installed/adopted remain false."])
            body="""# Independent rereview: PR 1138

No new blocking source finding at the exact repaired head. Issue 1252's source acceptance criteria are met: preserved archive bytes, separate dated release context, committed read-only helper, explicit historical/release manifest difference, updated PR description and tested refusal paths.

The four candidate files remain inert and byte-identical. The helper verified all 1,560 original tracked file bytes/modes and 18 audited release payloads. A fresh GET-only verification passed against actual main. The public Assay helper's immutable reference hash was independently checked. All 14 offline tests passed, including two fresh-process guard-removal mutations. A clean prospective merge tree was computed.

Initial live attempts stopped safely on missing current-main/historical objects in this isolated clone; these prerequisite failures and the successful refreshed receipt are retained separately. No generation or payload rewriting was performed.

The current public-fleet gate fails on four obsolete Assay/Cofactor incomplete-consumer assertions inherited from this PR's old base. This is a merge/check blocker, not a new finding in the five added files. Root must refresh/fix through the existing maintenance scope and recheck final head. Aggregate CI still pending where reported.

Ignored-inclusive scoped hygiene inspection found no actual user paths, email addresses or private operations history in the five added files. Regex matches were Python decorators and a generic Git URL template. Original reviewer worktree/evidence was preserved; this rereview used a separate owned worktree. No runtime/adoption authority follows from source acceptance.
"""
        else:
            summary.update(issues=[1238,1239,1240,1241,1242,1244,1245,1249],tests={"passed":227,"subtests_passed":4,"skipped":1,"skip_reason":"Explicit private evidence not selected"},mutation_probes=11,mutation_receipt_sha256=digest(root/"counterfactuals/summary.json"),hosted={"tests_passed":10726,"skipped":544,"subtests_passed":4,"coverage_percent":87.33,"embedding_tests_passed":51,"run":43694905249},notes=["Six observer, two integration, and three independent count/duplicate/retention mutations were killed; tracked source remained unchanged.","Pinned Ruff passed explicitly for changed scripts and tests; scripts are outside the generic CI lint target.","No changed-path overlap with actual main since merge base; prospective merge is clean.","Eight linked issues were read live and their source acceptance criteria checked.","Private saved observations and claimed live deployments/canaries were not reverified; no runtime inspection or interaction was performed.","The 544 aggregate hosted skips are not all individually classified. The one skip in the relevant local suite is optional private evidence, not a missing offline invariant.","Host launcher companion and actual adoption/deployment remain separately owned and authorized."])
            body="""# Independent source review: PR 1243

No verified blocking source finding at the exact reviewed head. The actual three-dot diff contains 16 files: session guidance, a read-only macOS tmux observer, generic preparation/evidence helpers and regression tests. It does not install or activate a runtime, change the supervisor, or re-pin consumer template components.

The observer checks exact socket/server/session/pane/process/cwd identity around capture; native identity is checked across capture, with managed-thread identity deliberately unknown. Nonregular metadata/registry inputs fail without blocking. Proposed integration executes hash-verified source bytes and leaves stop/status independent of adapter availability. The evidence verifier rejects duplicate targets and recomputes exact aggregate counts. The dispatcher retains startup failures before launching and separates inspection from task paste.

227 focused tests and four subtests passed. The only local skip is an explicitly selected private-evidence test; synthetic saved-artifact coverage ran. Eleven mutations were killed: six observer checks, two integration checks, wrong counts, duplicate targets and omitted startup retention. Tracked source was unchanged. Explicit pinned Ruff passed for scripts/tests. Actual-main integration has no changed-path overlap and produces a clean merge tree.

All eight visible head checks were successful at readback. Hosted tests report 10,726 passed, 544 skipped, four subtests and 87.33% coverage; the embedding job reports 51 passed. Aggregate skips are not all individually classified, so the hosted aggregate alone is not treated as complete coverage. CI's general lint excludes scripts; explicit local script lint fills that gap.

Issues 1238, 1239, 1240, 1241, 1242, 1244, 1245 and 1249 were read live, and their source fixes were checked against distinguishing fixtures. No new issue was needed. Private live-canary/deployment claims were not repeated as verified by this review. This is source-only acceptance: no live session inspection/input, installation, monitor lifecycle, adoption or deployment occurred. Companion host-launcher adoption remains separately owned.
"""
        safe(json.dumps(summary));save(root/"review.json",summary)
        body += "\nExact head: `" + proof["head"] + "`\n\nActual main: `" + proof["main"] + "`\n\nProspective merge tree: `" + proof["prospective_merge_tree"] + "`\n"
        (root/"REVIEW.md").write_text(body)
        summary["private_review_sha256"]=digest(root/"REVIEW.md");save(target/"summary.json",summary)
        print(number,digest(target/"summary.json"))
if __name__=="__main__":main()
