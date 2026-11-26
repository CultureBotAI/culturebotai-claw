"""Run one authorized, repository-bound GitHub metadata command under its lease."""
import argparse
import subprocess
from pathlib import Path

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositorySettings, merged_repository_environment

VALUE_FLAGS = {
    'create': {'--title', '-t', '--body', '-b', '--body-file', '-F', '--label', '-l'},
    'close': {'--reason', '-r', '--comment', '-c'},
    'comment': {'--body', '-b', '--body-file', '-F'},
    'edit': {'--title', '-t', '--body', '-b', '--body-file', '-F',
             '--add-label', '--remove-label'},
}


def validated_command(command, expected_repository):
    """Reject destination overrides and interactive/destructive flags before use."""
    command = list(command)
    if command and command[0] == '--':
        command = command[1:]
    if len(command) < 2 or command[0] not in ('issue', 'pr'):
        raise ValueError('only explicit issue/pr metadata commands are accepted')
    operation = command[1]
    if operation not in VALUE_FLAGS or (command[0] == 'pr' and operation == 'create'):
        raise ValueError('unsupported metadata operation; no new PRs')
    repositories = []
    targets = []
    supplied_flags = set()
    index = 2
    while index < len(command):
        token = command[index]
        if token in ('--repo', '-R'):
            if index + 1 == len(command):
                raise ValueError('repository flag requires a value')
            repositories.append(command[index + 1])
            index += 2
            continue
        if token.startswith('--repo=') or (token.startswith('-R') and len(token) > 2):
            repositories.append(token.split('=', 1)[1] if '=' in token else token[2:])
            index += 1
            continue
        flag = token.split('=', 1)[0]
        if flag in VALUE_FLAGS[operation]:
            supplied_flags.add(flag)
            if '=' not in token:
                if index + 1 == len(command):
                    raise ValueError('metadata flag requires a value')
                index += 1
            index += 1
            continue
        if token.startswith('-') or not token.isascii() or not token.isdecimal():
            raise ValueError('only numeric positional targets and allowed metadata flags are accepted')
        targets.append(token)
        index += 1
    if len(repositories) != 1 or repositories[0].casefold() != expected_repository.casefold():
        raise ValueError('exactly one repository flag must match the validated Mech')
    if len(targets) != (0 if operation == 'create' else 1):
        raise ValueError('operation requires exactly one numeric target, or none for issue creation')
    if operation in ('comment', 'create') and not supplied_flags & {'--body', '-b', '--body-file', '-F'}:
        raise ValueError('explicit body required; interactive entry is forbidden')
    if operation == 'create' and not supplied_flags & {'--title', '-t'}:
        raise ValueError('explicit title required; interactive entry is forbidden')
    if operation == 'edit' and not supplied_flags:
        raise ValueError('explicit edit required; interactive entry is forbidden')
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dotenv', type=Path, required=True)
    parser.add_argument('--mech', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    settings = RepositorySettings.from_environment(
        environ=merged_repository_environment(args.dotenv)
    )
    target = settings.get_target(args.mech)
    target.open()
    try:
        command = validated_command(args.command, target.expected_repository)
    except ValueError as exc:
        parser.error(str(exc))
    with LockManager().lock(args.mech, 'fleet_ops_20261126_metadata'):
        raise SystemExit(subprocess.run(['gh', *command], check=False).returncode)


if __name__ == '__main__':
    main()
