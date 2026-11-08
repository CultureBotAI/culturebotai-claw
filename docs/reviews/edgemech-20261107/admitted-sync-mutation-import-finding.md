# Isolate pytest configuration for the admitted-sync mutation proof

The first `consumer` mutation proof for issue 1004 failed during collection,
before reaching its intended negative control. Its explicit import-origin
assertion detected `src/kg_microbe_governance/__init__.py` instead of the
isolated copied package. The repository's pytest `pythonpath` configuration
overrode the child process's intended import order.

The retained failure is
`workspace/admitted-sync-consumer-mutation-20261108/failure.log`. No success
receipt was created and no production source or consumer file changed. This
is a failed harness attempt, not a successful mutation proof.

Run the isolated child pytest with `-c /dev/null`, retaining its explicit
PYTHONPATH, exact imported-module-origin assertion and fresh bytecode directory.
Use new v2 output paths for the corrected proof. Do not weaken the origin check
or change the runtime implementation to make this harness pass.
