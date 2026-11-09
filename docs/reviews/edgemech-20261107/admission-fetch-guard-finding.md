# Explicitly reject invalid data refs before invoking Git

Executable negative controls for the #986 workflow preparation step found that
the local `/bin/bash` continued past a failed standalone
`[[ "$source_ref" =~ ^[0-9a-f]{40}$ ]]` despite `set -euo pipefail`. A fake
selector emitting `main`, or two newline-separated refs, reached the fake Git
fetch command and the step returned success. The isolated workflow suite had
two failures and five passes. No live fetch was performed.

The retained traces are under ignored
`workspace/edgemech-admission-workflow-debug-20261107/`; each shows the actual
arguments passed to the controlled Git stub. The Python selector itself already
requires a protected declaration and one immutable SHA, but the workflow's
defensive check must not depend on implicit shell error-exit behavior.

Use an explicit conditional with a nonzero exit before fetch. Preserve the
existing executable tests for a historical trusted checkout with no declaration,
one valid ref, a mutable ref and multiline output. Require no Git invocation for
invalid selector output, on both local and CI Bash runtimes.
