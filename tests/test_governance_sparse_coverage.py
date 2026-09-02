"""Every blob the fleet audit reads is one the workflow checked out.

#281. The audit clones consumers with `--filter=blob:none`, so any object git
cannot answer locally is fetched over the network under a five-second timeout.
That matters because the audit compares artifact *bytes*: unlike the
completeness guard (#280), it cannot use `ls-tree` alone and legitimately needs
the blob.

It is safe today, and for a structural reason rather than by luck. The
workflow's sparse-checkout set comes from `kg-microbe-governance list`, and the
audit reads `_desired_files` -- both derived from
`manifest.artifacts_for(consumer)` plus `manifest.pin_path`. Identical sets, so
every blob is already materialized and no lazy fetch happens.

Nothing asserted that. If the two ever diverged, the audit would still pass
locally and start making network calls per artifact in CI, with a
five-second timeout and a `head_read` issue when it expired -- an
infrastructure failure wearing the costume of a governance finding, which is
the shape #281 was filed about.
"""

from __future__ import annotations

import json
import subprocess
import sys

from kg_microbe_governance import _desired_files, load_governance_manifest

REF = "0" * 40


def _listed_targets(repository: str) -> set[str]:
    """What the workflow puts in the sparse-checkout set, via the real CLI."""
    result = subprocess.run(
        [sys.executable, "-m", "kg_microbe_governance", "list",
         "--repository", repository, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return {row["target"] for row in json.loads(result.stdout)}


def _audited_targets(repository: str) -> set[str]:
    """What the audit opens blobs for."""
    manifest = load_governance_manifest()
    consumer = manifest.consumer_for(repository)
    return {relative for _id, relative, _bytes, _mode in _desired_files(
        manifest, consumer, REF
    )}


def test_the_audit_reads_only_paths_the_sparse_checkout_materializes():
    manifest = load_governance_manifest()
    assert manifest.consumers, "no consumers declared; this test guards nothing"

    for key, consumer in manifest.consumers.items():
        listed = _listed_targets(consumer.github)
        audited = _audited_targets(consumer.github)

        # The pin is added to the sparse set by the workflow separately, from
        # the same manifest.pin_path the audit appends here.
        assert audited - listed == {manifest.pin_path}, (
            f"{key}: the audit opens blobs the sparse checkout does not "
            f"materialize: {sorted(audited - listed - {manifest.pin_path})}. "
            f"In CI those become lazy network fetches under a 5s timeout."
        )
        assert not listed - audited, (
            f"{key}: the sparse set carries paths the audit never reads: "
            f"{sorted(listed - audited)}"
        )


def test_the_pin_path_is_the_only_extra_and_it_is_named():
    """Stated rather than tolerated: the one path the audit adds beyond the
    artifact list is the pin, and the workflow adds it to the sparse set by
    name. A second unlisted path appearing here is a real divergence."""
    manifest = load_governance_manifest()
    consumer = next(iter(manifest.consumers.values()))

    extra = _audited_targets(consumer.github) - _listed_targets(consumer.github)

    assert extra == {manifest.pin_path}
    assert manifest.pin_path == "scripts/.vendored_canon_ref"
