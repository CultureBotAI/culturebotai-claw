"""Read-only public provenance readback, 2026-11-15.

Inputs: explicit root checkout and durable task root. Outputs: public-safe hashes,
copy/JUnit readback counts, and scope boundaries on stdout. No input file writes,
Git operations, network or runtime action. Own packages receive hygiene only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, label):
    if not ok:
        raise ValueError(label)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--task-root",type=Path,required=True)
    args=parser.parse_args()
    base=args.root/"scripts/adhoc/cycle-maintenance-20261115"
    packages={name:base/name for name in ["reviews/dirty-snapshot-plans","reviews/dirty-snapshot-independent","repairs/1197-refresh","reviews/main-refresh"]}
    packages["repairs/1138-refresh"]=args.task_root/"repairs/1138/refresh-after-1112/public"
    hashes={}
    for name,path in packages.items():
        hashes[name]={}
        for item in sorted(path.rglob("*")):
            if not item.is_file():
                continue
            text=item.read_text()
            check(not re.search(r"/Users/|/private/|/var/folders/",text),"Private absolute path")
            emails=set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",text))
            check(emails <= {"git@github.com"},"Unexpected email-like value")
            check(not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}",text),"Credential-like value")
            hashes[name][item.relative_to(path).as_posix()]=digest(item)
        for filename in ["MANIFEST.json","PROVENANCE.json"]:
            if (path/filename).exists():
                doc=json.loads((path/filename).read_bytes())
                for rel,expected in doc.get("files",{}).items():
                    check(digest(path/rel)==expected,"File ledger mismatch")
    capture=packages["reviews/dirty-snapshot-plans"]
    prov=json.loads((capture/"PROVENANCE.json").read_bytes())
    for name,expected in prov["helpers"].items():
        check(digest(capture/name)==expected,"Capture helper mismatch")
    private=args.task_root/"cleanup/dirty-snapshot-preservation-20261115"
    check(digest(private/"RESTORATION-PLAN.json")==prov["private_plan_sha256"],"Plan mismatch")
    for name,expected in prov["private_capture_sha256"].items():
        check(digest(private/name/"capture.json")==expected,"Capture mismatch")
    check(digest(capture/"PREPARATION.json")==prov["public_preparation_sha256"],"Preparation mismatch")
    raw1138=args.task_root/"repairs/1138/refresh-after-1112"
    for name in ["proof.json","merge-prepared.json","metadata_refresh.py.txt"]:
        check((raw1138/name).read_bytes()==(raw1138/"public"/name).read_bytes(),"1138 copy mismatch")
    proof=json.loads((raw1138/"proof.json").read_bytes())
    check(digest(raw1138/"metadata_refresh.py.txt")==proof["metadata_helper_archive_sha256"],"1138 archive mismatch")
    check(digest(raw1138/"focused-pytest.log")==proof["focused_tests"]["log_sha256"],"1138 test log mismatch")
    check(digest(raw1138/"aggregate-failure-original.log")==proof["aggregate_failure"]["original_log_sha256"],"Original failure log mismatch")
    reviews=packages["reviews/main-refresh"]
    prov=json.loads((reviews/"PROVENANCE.json").read_bytes())
    check(digest(reviews/prov["helper"])==prov["helper_sha256"],"Independent helper mismatch")
    for prior in prov["retained_prior_helpers"]:
        check(digest(reviews/prior["path"])==prior["sha256"],"Prior helper changed")
    counts={}
    for number in ["1197","1138"]:
        receipt=reviews/(number+"-review.json")
        evidence=args.task_root/"reviews/main-refresh-independent"/number
        check(receipt.read_bytes()==(evidence/"proof.json").read_bytes(),"Independent receipt copy mismatch")
        doc=json.loads(receipt.read_bytes())
        check(digest(receipt)==prov["public_result_sha256"][receipt.name],"Receipt hash mismatch")
        check(digest(evidence/"pytest.log")==doc["test_log_sha256"]==prov["private_test_log_sha256"][number],"Independent test log mismatch")
        suites=list(ET.fromstring((evidence/"pytest.xml").read_bytes()).iter("testsuite"))
        actual={key:sum(int(s.attrib.get(key,0)) for s in suites) for key in ["tests","failures","errors","skipped"]}
        check(actual==doc["tests"],"JUnit count mismatch")
        check(actual["tests"]>0 and not any(actual[k] for k in ["failures","errors","skipped"]),"Incomplete tests")
        counts[number]=actual
    print(json.dumps({"date":"2026-11-15","verdict":"bounded_pass","files":hashes,
                      "independent_scope":["dirty capture/probe provenance","1138 package source/archive/receipt readback","main-refresh helper/proofs/JUnit readback"],
                      "hygiene_only_own_packages":["reviews/dirty-snapshot-independent","repairs/1197-refresh"],
                      "junit_counts":counts,"ssh_git_url_not_personal_email":True,
                      "helper_sha256":digest(Path(__file__)),"input_writes":False,"github_or_git_writes":False},indent=2,sort_keys=True))

if __name__=="__main__":
    main()
