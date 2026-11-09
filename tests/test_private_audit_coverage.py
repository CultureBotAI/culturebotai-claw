"""Private obligations preserve exact coverage without manufacturing a Git root."""

from datetime import timedelta

import pytest
import test_private_scaleup_audit as fixtures
from test_automatic_private_audit import packaged, verify
from test_private_scaleup_audit import NOW

from kg_microbe_governance import GovernanceError
from kg_microbe_governance import private_audit_coverage as coverage
from kg_microbe_governance import private_scaleup_audit as manual
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import Consumer


@pytest.fixture
def source():
    return fixtures.source.__wrapped__()


def manifest(source):
    return manual.parse_manifest(source[1][manual.CANONICAL_MANIFEST_PATH])


def test_deferred_private_obligation_is_incomplete_not_a_fake_root(source):
    model = manifest(source)
    item = coverage.obligation(model, source[0])
    coverage.exact_coverage(model.consumers, {}, {"scaleupmech": item})
    row = coverage.deferred_row(item)
    assert row["state"] == "private_verification_required"
    assert row["root"] is None and row["head"] is None and row["checked_artifacts"] == 0
    assert row["installation_verified"] is False


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "unknown", "wrong_identity"]
)
def test_exact_coverage_has_no_missing_root_escape(source, change):
    model = manifest(source)
    item = coverage.obligation(model, source[0])
    consumers = dict(model.consumers)
    roots, private = {}, {"scaleupmech": item}
    if change == "missing":
        consumers["other"] = Consumer("other", "CultureBotAI/OtherMech", "src/other")
    elif change == "duplicate":
        roots["scaleupmech"] = "/not-a-real-root"
    elif change == "unknown":
        private["other"] = private.pop("scaleupmech")
    else:
        consumers["scaleupmech"] = Consumer(
            "scaleupmech", "attacker/ScaleupMech", "src/scaleupmech"
        )
    with pytest.raises(GovernanceError):
        coverage.exact_coverage(consumers, roots, private)


def test_private_obligation_cannot_narrow_expected_artifacts(source):
    model = manifest(source)
    policy = source[0]
    policy["artifacts"].pop()
    with pytest.raises(GovernanceError):
        coverage.obligation(model, policy)


def test_verified_evidence_completes_only_exact_private_coverage(source):
    public, _, _ = packaged(source)
    evidence = verify(public, source)
    model = manifest(source)
    rows = coverage.complete_rows(
        model.consumers,
        [],
        {"scaleupmech": evidence},
        model,
        now=NOW + timedelta(seconds=2),
        policy=source[0],
    )
    assert len(rows) == 1 and rows[0]["checked_artifacts"] == 22
    assert rows[0]["installation_verified"] is True
    assert rows[0]["root"] is None


@pytest.mark.parametrize(
    "change", ["missing", "raw_json", "extra_public", "duplicate_public", "expired"]
)
def test_full_verdict_refuses_missing_unverified_or_replayed_coverage(source, change):
    public, _, _ = packaged(source)
    evidence = verify(public, source)
    model = manifest(source)
    private, rows, now = {"scaleupmech": evidence}, [], NOW + timedelta(seconds=2)
    if change == "missing":
        private = {}
    elif change == "raw_json":
        private["scaleupmech"] = evidence.receipt
    elif change == "extra_public":
        rows = [{"key": "unknown", "issues": [], "state": "retained"}]
    elif change == "duplicate_public":
        rows = [{"key": "scaleupmech", "issues": [], "state": "retained"}]
    else:
        now = NOW + timedelta(seconds=122)
    with pytest.raises((GovernanceError, manual.AuditError)):
        coverage.complete_rows(
            model.consumers, rows, private, model, now=now, policy=source[0]
        )
