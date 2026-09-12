"""Compare real API defaults without concealing changes to review protection."""
from copy import deepcopy

import pytest

from kg_microbe_merge_queue import canonical_ruleset, desired_ruleset


def actual_ruleset():
    result = desired_ruleset({".github/workflows/ci.yml": ["qc"]})
    params = result["rules"][0]["parameters"]
    params.update(
        required_reviewers=[], allowed_merge_methods=["merge", "squash", "rebase"],
        dismissal_restriction={"enabled": False, "allowed_actors": []},
        require_extra_approval_for_unattributed_changes=True,
    )
    return result


def test_observed_api_defaults_equal_omitted_request_defaults():
    request = desired_ruleset({".github/workflows/ci.yml": ["qc"]})
    assert canonical_ruleset(actual_ruleset()) == canonical_ruleset(request)


@pytest.mark.parametrize("changes", [
    {"dismissal_restriction": {"enabled": True, "allowed_actors": []}},
    {"dismissal_restriction": {"enabled": False, "allowed_actors": [{"id": 1, "type": "User"}]}},
    {"require_extra_approval_for_unattributed_changes": False},
    {"required_approving_review_count": 1},
    {"future_unknown_parameter": True},
])
def test_nondefault_review_parameters_remain_drift(changes):
    before = actual_ruleset()
    changed = deepcopy(before)
    changed["rules"][0]["parameters"].update(changes)
    assert canonical_ruleset(changed) != canonical_ruleset(before)
