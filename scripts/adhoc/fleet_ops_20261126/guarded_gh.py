"""Run one authorized GitHub metadata command under the repository lease."""
import argparse
import subprocess
from pathlib import Path

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositorySettings, merged_repository_environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dotenv', type=Path, required=True)
parser.add_argument('--mech', required=True)
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
settings = RepositorySettings.from_environment(
    environ=merged_repository_environment(args.dotenv)
)
settings.get_target(args.mech).open()
command = args.command
if command and command[0] == '--':
    command = command[1:]
if len(command) < 2 or command[0] not in ('issue', 'pr'):
    parser.error('only explicit issue/pr metadata commands are accepted')
if command[1] not in ('create', 'close', 'comment', 'edit'):
    parser.error('only create/close/comment/edit metadata operations are accepted')
if command[0] == 'pr' and command[1] == 'create':
    parser.error('this campaign does not open PRs')
with LockManager().lock(args.mech, 'fleet_ops_20261126_metadata'):
    raise SystemExit(subprocess.run(['gh', *command], check=False).returncode)
