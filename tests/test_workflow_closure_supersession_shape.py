"""Strict explicit supersession shape; remote provenance is tested separately."""
import copy

import pytest
from test_workflow_closure_shape import receipt

from kg_microbe_workflows.closure import multi_pr_members


def with_supersession():
    value = receipt()
    value["issues"][0]["fix_commit_sha"] = "a" * 40
    value["issues"][0]["superseded_paths"] = [
        {"path": "reviews/structured/family/review.md", "pr_number": 365, "commit_sha": "d" * 40}
    ]
    return value


def test_explicit_supersession_shape_is_preserved():
    value = with_supersession()
    original = copy.deepcopy(value)
    assert len(multi_pr_members(value)) == 2
    assert value == original


@pytest.mark.parametrize("bad", [None, False, {}, [], [None], ["path"]])
def test_present_supersession_is_never_ignored(bad):
    value = with_supersession()
    value["issues"][0]["superseded_paths"] = bad
    with pytest.raises(ValueError):
        multi_pr_members(value)


@pytest.mark.parametrize("field,bad", [
    ("path", "/absolute"), ("path", "../escape"), ("path", "a/../b"),
    ("path", "a//b"), ("path", "a/./b"), ("path", "a\\b"),
    ("path", "a\x00b"), ("path", ""), ("path", None),
    ("pr_number", 367), ("pr_number", True), ("pr_number", 365.0),
    ("commit_sha", "a" * 40), ("commit_sha", "d" * 39), ("commit_sha", None),
])
def test_supersession_names_safe_path_same_pr_and_distinct_exact_commit(field, bad):
    value = with_supersession()
    value["issues"][0]["superseded_paths"][0][field] = bad
    with pytest.raises(ValueError):
        multi_pr_members(value)


def test_supersession_rejects_duplicate_paths():
    value = with_supersession()
    entries = value["issues"][0]["superseded_paths"]
    entries.append({**entries[0], "commit_sha": "e" * 40})
    with pytest.raises(ValueError):
        multi_pr_members(value)


def test_supersession_rejects_unknown_fields():
    value = with_supersession()
    value["issues"][0]["superseded_paths"][0]["override"] = True
    with pytest.raises(ValueError):
        multi_pr_members(value)


def test_supersession_has_a_real_size_bound():
    value = with_supersession()
    entry = value["issues"][0]["superseded_paths"][0]
    value["issues"][0]["superseded_paths"] = [
        {**entry, "path": f"reviews/structured/{i}.md"} for i in range(257)
    ]
    with pytest.raises(ValueError):
        multi_pr_members(value)
