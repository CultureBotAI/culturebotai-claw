"""Execute the sync skill's actual shell under isolated Git/GitHub stubs."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

STUB = r"""import json, os, sys
from pathlib import Path
args=sys.argv[1:]
tool=Path(sys.argv[0]).name
state_path=Path(os.environ['FAKE_STATE'])
state=json.loads(state_path.read_text())
with Path(os.environ['FAKE_LOG']).open('a') as stream:
    stream.write(json.dumps([tool,*args])+'\n')
sha='a'*40
def save():state_path.write_text(json.dumps(state))
if tool=='gh':
    if args[0]=='api':
        if state.get('api_error'):sys.exit(1)
        print('true' if state['queue'] else 'false')
    elif args[:2]==['pr','checks']:
        sys.exit(0)
    elif args[:2]==['pr','merge']:
        state['merge_called']=True
        if '--delete-branch' in args:state['deleted']=True
        save()
    elif args[:2]==['pr','view']:
        fields=args[args.index('--json')+1]
        head='b'*40 if state.get('wrong_pr_head') else sha
        if fields.startswith('state,'):
            print('\t'.join([state.get('merge_state','MERGED'),'main','feature',head,'CultureBotAI/example']))
        else:
            print('\t'.join(['main','feature',head,'CultureBotAI/example',
                             state.get('mergeable','MERGEABLE'),'CLEAN']))
    else:raise AssertionError(args)
elif tool=='git':
    if args[:1]==['-C']:args=args[2:]
    if args[0]=='fetch':pass
    elif args[0]=='merge-base':sys.exit(0 if state['ancestor'] else 1)
    elif args[0]=='rev-parse':print(sha)
    elif args[0]=='ls-remote':
        if state.get('deleted'):
            if '--exit-code' in args:sys.exit(2)
        else:
            head='b'*40 if state.get('changed_remote') and state.get('merge_called') else sha
            print(head+'\trefs/heads/feature')
    elif args[0]=='push':
        assert '--force-with-lease=refs/heads/feature:'+sha in args
        assert ':refs/heads/feature' in args
        if state.get('push_race'):sys.exit(1)
        state['deleted']=True;save()
    elif args[0]=='status':pass
    elif args[:2]==['worktree','remove']:
        path=Path(args[2]);assert path.is_relative_to(state_path.parent)
        path.rmdir()
    elif args[:2]==['update-ref','-d']:pass
    else:raise AssertionError(args)
else:raise AssertionError(tool)
"""


@pytest.mark.parametrize("queue,ancestor,state,code,merge,clean", [
    (True, False, {}, 0, True, True),
    (False, False, {}, 2, False, False),
    (False, True, {}, 0, True, True),
    (True, False, {"merge_state": "OPEN"}, 1, True, False),
    (True, True, {"changed_remote": True}, 1, True, False),
    (False, True, {"changed_remote": True}, 1, True, False),
    (True, True, {"push_race": True}, 1, True, False),
    (False, True, {"push_race": True}, 1, True, False),
    (True, True, {"wrong_pr_head": True}, 1, False, False),
    (True, True, {"mergeable": "CONFLICTING"}, 1, False, False),
    (True, True, {"api_error": True}, 1, False, False),
])
def test_actual_merge_and_cleanup_guards(tmp_path, queue, ancestor, state, code, merge, clean):
    skill = Path(__file__).parents[1] / ".claude/skills/cross-mech-sync/SKILL.md"
    text = skill.read_text()
    verify = "# Query effective rules now;" + text.split("# Query effective rules now;", 1)[1].split("```", 1)[0]
    cleanup = text.split("### F. Merge + clean up", 1)[1].split("```bash\n", 1)[1].split("```", 1)[0]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("git", "gh"):
        script = bindir / tool
        script.write_text("#!" + sys.executable + "\n" + STUB)
        script.chmod(0o755)
    statefile = tmp_path / "state.json"
    statefile.write_text(json.dumps(dict(state, queue=queue, ancestor=ancestor)))
    logfile = tmp_path / "calls.jsonl"
    sync = tmp_path / "sync"
    sync.mkdir()
    wt = sync / "worktree"
    wt.mkdir()
    operation = sync / "operation.sh"
    operation.write_text("fixture")
    body = sync / "pr.md"
    body.write_text("fixture")
    env = {**os.environ, "PATH": str(bindir) + ":" + os.environ["PATH"],
           "FAKE_STATE": str(statefile), "FAKE_LOG": str(logfile),
           "TARGET_KEY": "example", "TARGET_GITHUB": "CultureBotAI/example",
           "WT": str(wt), "REPO": str(wt), "BRANCH": "feature", "PR_NUMBER": "1",
           "OPERATION_SCRIPT": str(operation), "PR_BODY_FILE": str(body), "SYNC_DIR": str(sync)}
    script = 'set -euo pipefail\nrun_with_repo_lock() { shift 2; "$@"; }\n' + verify + "\n" + cleanup
    run = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True, timeout=20)
    calls = [json.loads(line) for line in logfile.read_text().splitlines()]
    merges = [call for call in calls if call[:3] == ["gh", "pr", "merge"]]
    cleaned = any("worktree" in call and "remove" in call for call in calls)
    assert run.returncode == code, (run.stderr, calls)
    assert bool(merges) == merge
    assert cleaned == clean
    assert all("--delete-branch" not in call and "--admin" not in call for call in merges)
    if merges:
        assert ("--squash" in merges[0]) is not queue
    if not clean:
        assert wt.exists() and operation.exists() and body.exists()
        assert not json.loads(statefile.read_text()).get("deleted")
