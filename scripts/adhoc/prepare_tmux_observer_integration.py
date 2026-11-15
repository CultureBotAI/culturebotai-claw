#!/usr/bin/env python3
"""Prepare a private passive-observer integration proposal, issue 1238, 2026-11-15.

Inputs: exact hash-pinned legacy observer source. Outputs: candidate source and
unified diff in an ignored operator-selected directory. No live configuration,
monitor process, session, native store, or repository other than outputs is changed.
The legacy observer remains private; no host identities are embedded here.
"""
import argparse
import difflib
import hashlib
from pathlib import Path

HELPERS = '''
# Optional read-only tmux transport; the dependency is pinned independently.
TMUX_ADAPTER = None

def load_tmux_adapter(path, expected_sha256):
    global TMUX_ADAPTER
    require(path is not None and path.is_absolute() and not path.is_symlink(), 'Explicit tmux adapter path required')
    require(isinstance(expected_sha256,str) and re.fullmatch(r'[0-9a-f]{64}',expected_sha256), 'Explicit tmux source digest required')
    require(file_digest(path)==expected_sha256, 'Tmux adapter source digest differs')
    spec=importlib.util.spec_from_file_location('pinned_mech_session_tmux',path)
    require(spec is not None and spec.loader is not None, 'Tmux adapter cannot be loaded')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(file_digest(path)==expected_sha256, 'Tmux adapter changed while loading')
    TMUX_ADAPTER=(module,path,expected_sha256)

def checked_tmux_adapter():
    require(TMUX_ADAPTER is not None, 'Tmux targets need a reviewed adapter')
    module,path,expected_sha256=TMUX_ADAPTER
    require(file_digest(path)==expected_sha256, 'Tmux adapter changed; observation held')
    return module

'''
VALIDATE = '''        require(t.get('transport','terminal') in ('terminal','tmux'), 'Unsupported observer transport')
        if t.get('transport') == 'tmux':
            require(t.get('binding_status')=='pinned', 'Explicit tmux binding required')
            binding=checked_tmux_adapter().validate_binding(t.get('tmux_observation'))
            require(t.get('key')==binding['key'] and t.get('root')==binding['root']
                    and t.get('pid')==binding['native_process']['pid']
                    and t.get('tty')==binding['native_process']['tty'], 'Legacy/native tmux descriptor differs')
            endpoint=(binding['tmux']['socket'],binding['pane']['pane_id'])
            require(t['pid'] not in pids and t['tty'] not in ttys and endpoint not in tmux_panes, 'Duplicate tmux process or endpoint')
            pids.add(t['pid']);ttys.add(t['tty']);tmux_panes.add(endpoint)
            continue
'''
OBSERVE = '''    if target.get('transport') == 'tmux':
        observation=checked_tmux_adapter().observe_binding(target['tmux_observation'])
        return {**observation,'observed_at':now(),'publication_scope':target['publication_scope'],
                'expected_pid':target['pid'],'tty':target['tty'],'root':target['root'],
                'process_live':observation['binding']=='live',
                'authority':'observation_only_no_input_or_adoption'}
'''


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Legacy source no longer uniquely matches an integration anchor")
    return source.replace(old, new)


def proposed_source(source):
    source = replace_once(source, "import hashlib\n", "import hashlib\nimport importlib.util\n")
    source = replace_once(source, "def validate_registry(data):\n", HELPERS + "def validate_registry(data):\n")
    source = replace_once(source, "keys=set();pids=set();ttys=set();windows=set()",
                          "keys=set();pids=set();ttys=set();windows=set();tmux_panes=set()")
    source = replace_once(source, "        require(t.get('binding_status') == 'pinned', 'Explicit binding status required')",
                          VALIDATE + "        require(t.get('binding_status') == 'pinned', 'Explicit binding status required')")
    source = replace_once(source, "    row={'key':target['key'],'observed_at':now(),'publication_scope':target['publication_scope'],",
                          OBSERVE + "    row={'key':target['key'],'observed_at':now(),'publication_scope':target['publication_scope'],")
    source = replace_once(source, "    args=p.parse_args(argv);state=safe_state(args.state_dir)",
                          "    p.add_argument('--tmux-adapter',type=Path);p.add_argument('--tmux-reviewed-sha256')\n"
                          "    args=p.parse_args(argv);state=safe_state(args.state_dir)\n"
                          "    require(bool(args.tmux_adapter)==bool(args.tmux_reviewed_sha256), 'Tmux adapter and digest must be supplied together')\n"
                          "    if args.tmux_adapter:load_tmux_adapter(args.tmux_adapter,args.tmux_reviewed_sha256)")
    source = replace_once(source, "'registry_path':str(args.registry),'registry_sha256':registry_sha,'interval':args.interval})",
                          "'registry_path':str(args.registry),'registry_sha256':registry_sha,'interval':args.interval,\n"
                          "                                     'tmux_adapter':str(args.tmux_adapter) if args.tmux_adapter else None,\n"
                          "                                     'tmux_adapter_sha256':args.tmux_reviewed_sha256})")
    source = replace_once(source, "            snapshot(registry,registry_sha,state)\n",
                          "            if args.tmux_adapter:checked_tmux_adapter()\n            snapshot(registry,registry_sha,state)\n")
    source = replace_once(source, "            require(current['owner']['source_sha256']==args.reviewed_sha256",
                          "            require(current['owner'].get('tmux_adapter')==(str(args.tmux_adapter) if args.tmux_adapter else None)\n"
                          "                    and current['owner'].get('tmux_adapter_sha256')==args.tmux_reviewed_sha256, 'Existing observer has different tmux adapter; no rebind')\n"
                          "            require(current['owner']['source_sha256']==args.reviewed_sha256")
    source = replace_once(source, "'--reviewed-sha256',args.reviewed_sha256],cwd=str(BASE)",
                          "'--reviewed-sha256',args.reviewed_sha256]+(['--tmux-adapter',str(args.tmux_adapter),\n"
                          "                  '--tmux-reviewed-sha256',args.tmux_reviewed_sha256] if args.tmux_adapter else []),cwd=str(BASE)")
    compile(source, "codex_observer.proposed.py", "exec")
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original = args.source.read_bytes()
    if hashlib.sha256(original).hexdigest() != args.source_sha256:
        raise SystemExit("Original private observer source changed")
    text = original.decode()
    candidate = proposed_source(text)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "codex_observer.proposed.py").open("x") as stream:
        stream.write(candidate)
    diff = difflib.unified_diff(text.splitlines(True), candidate.splitlines(True),
                               fromfile="codex_observer.original.py", tofile="codex_observer.proposed.py")
    with (args.output / "integration.patch").open("x") as stream:
        stream.writelines(diff)
    print("Private proposal prepared; no deployment or registry change performed")


if __name__ == "__main__":
    main()
