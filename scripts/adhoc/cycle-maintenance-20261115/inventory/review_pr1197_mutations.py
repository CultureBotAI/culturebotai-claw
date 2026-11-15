#!/usr/bin/env python3
"""Read-only PR 1197 mutation review, 2026-11-15; related issues 1198/1199.
Inputs: exact review worktree; outputs: per-mutation pytest logs and JSON.
Source is changed in memory only. Each test runs in a fresh Python process.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

CASES = {
    'descending-order': ('-len(data["issues"].get(repo, []))', 'len(data["issues"].get(repo, []))', 'test_backlog_order_is_descending_with_stable_ties_and_errors_last'),
    'stale-overlay': ('if value.get("updated_at") != current[key]["updatedAt"]:', 'if False:', 'test_invalid_or_stale_annotations_are_refused'),
    'closed-window': ('if start <= closed_at <= end:', 'if True:', 'test_closed_window_includes_both_boundaries_excludes_prs_and_reopened'),
    'markdown-metrics': ('fields.extend(["pr_open", "pr_conflicts", "pr_drafts"])', 'fields.extend([])', 'test_markdown_preserves_backlog_and_optional_pr_metrics'),
}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worktree',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mutation',choices=CASES)
    args=parser.parse_args()
    source=args.worktree/'scripts/fleet_issue_status.py'
    original=source.read_bytes()
    if args.mutation:
        sys.path[:0]=[str(args.worktree/'scripts'),str(args.worktree/'src'),str(args.worktree)]
        before,after,test=CASES[args.mutation]
        code=original.decode()
        assert code.count(before)==1
        spec=importlib.util.spec_from_file_location('fleet_issue_status',source)
        module=importlib.util.module_from_spec(spec)
        sys.modules['fleet_issue_status']=module
        exec(compile(code.replace(before,after),str(source),'exec'),module.__dict__)
        import pytest
        return pytest.main(['-q',str(args.worktree/'tests/test_fleet_issue_status.py'),'-k',test])
    args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for name in CASES:
        env=os.environ.copy()
        env['PYTHONPYCACHEPREFIX']=str(args.output/f'cache-{name}')
        command=[sys.executable,__file__,'--worktree',str(args.worktree),'--output',str(args.output),'--mutation',name]
        result=subprocess.run(command,env=env,cwd=args.worktree,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (args.output/f'{name}.log').write_text(result.stdout)
        results.append({'mutation':name,'exit_code':result.returncode,'killed':result.returncode==1,'source_sha256':hashlib.sha256(original).hexdigest()})
    assert source.read_bytes()==original, 'source changed'
    (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))
    return 0 if all(row['killed'] for row in results) else 1

if __name__=='__main__':
    raise SystemExit(main())
