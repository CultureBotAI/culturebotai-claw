#!/bin/bash
#
# Run the maintained coordination-hook integration suite.
#
# The former manual diagnostic hard-coded three sibling checkouts and inspected
# copied files without proving Claude Code registered or executed them. The
# pytest suite builds manifest-scoped temporary targets and exercises the actual
# settings commands, lock exits, target validation, and status updates.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec uv run --offline --frozen --project "$SCRIPT_DIR" \
    pytest -q "$SCRIPT_DIR/tests/test_hook_templates.py"
