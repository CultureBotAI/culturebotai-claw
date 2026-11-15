"""Real schema validation must survive the documented PyYAML C-loader failure."""

import importlib
import threading

import pytest
import yaml
from test_mim_stable_identity import builder

PREFIX = "https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_"


@pytest.fixture
def schema_runtime(monkeypatch):
    from sssom import constants

    loader_module = importlib.import_module("linkml_runtime.loaders.yaml_loader")
    constants._get_sssom_schema_object.cache_clear()
    monkeypatch.delattr(constants.SSSOMSchemaView, "instance", raising=False)
    try:
        yield constants, loader_module
    finally:
        constants._get_sssom_schema_object.cache_clear()
        if hasattr(constants.SSSOMSchemaView, "instance"):
            del constants.SSSOMSchemaView.instance


def empty_candidate(tmp_path):
    path = tmp_path / "empty.tsv"
    builder._write_sssom([], path, mim_prefix=PREFIX, empty_version="2026-01-01")
    return path


class NullTagLoader(yaml.SafeLoader):
    """Actual broken-loader shape; no SSSOM validator is replaced by a fake."""

    def compose_mapping_node(self, anchor):
        node = super().compose_mapping_node(anchor)
        node.tag = None
        return node


def test_broken_loader_still_runs_all_three_native_validators_and_restores(
    tmp_path, monkeypatch, schema_runtime,
):
    from sssom import validators
    from sssom.constants import SchemaValidationType

    _, module = schema_runtime
    monkeypatch.setattr(module, "DupCheckYamlLoader", NullTagLoader)
    native_validate = validators.validate
    calls = []

    def observed(*args, **kwargs):
        calls.append((args[1], kwargs))
        return native_validate(*args, **kwargs)

    monkeypatch.setattr(validators, "validate", observed)
    path = empty_candidate(tmp_path)
    before = path.read_bytes()
    builder._STABLE_PRODUCER.validate_empty_candidate(path, builder.COLUMNS, PREFIX)
    assert calls == [([
        SchemaValidationType.JsonSchema,
        SchemaValidationType.PrefixMapCompleteness,
        SchemaValidationType.StrictCurieFormat,
    ], {"fail_on_error": True})]
    assert module.DupCheckYamlLoader is NullTagLoader
    assert path.read_bytes() == before


def test_invalid_native_schema_is_not_swallowed_and_loader_is_restored(
    tmp_path, monkeypatch, schema_runtime,
):
    constants, module = schema_runtime
    monkeypatch.setattr(module, "DupCheckYamlLoader", NullTagLoader)
    schema = tmp_path / "duplicate-schema.yaml"
    schema.write_text("id: https://example.invalid/first\nid: https://example.invalid/second\n")
    monkeypatch.setattr(constants, "SCHEMA_YAML", str(schema))
    path = empty_candidate(tmp_path)
    before = path.read_bytes()
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key 'id'"):
        builder._STABLE_PRODUCER.validate_empty_candidate(path, builder.COLUMNS, PREFIX)
    assert module.DupCheckYamlLoader is NullTagLoader
    assert path.read_bytes() == before


@pytest.mark.parametrize("raw", ["outer:\n  key: first\n  key: second\n", "? [a, b]\n: value\n"])
def test_scoped_schema_loader_rejects_duplicate_and_unhashable_keys(schema_runtime, raw):
    _, module = schema_runtime
    original = module.DupCheckYamlLoader
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate|unhashable"):
        with builder._STABLE_PRODUCER._pure_linkml_loader():
            yaml.load(raw, Loader=module.DupCheckYamlLoader)
    assert module.DupCheckYamlLoader is original


def test_loader_scope_reuses_shared_lock_and_restores_nested_state(monkeypatch, schema_runtime):
    _, module = schema_runtime
    original = module.DupCheckYamlLoader
    lock = threading.RLock()
    monkeypatch.setattr(module, "_claw_linkml_loader_lock", lock, raising=False)
    with builder._STABLE_PRODUCER._pure_linkml_loader():
        outer = module.DupCheckYamlLoader
        assert outer is not original
        assert lock._is_owned()
        assert module._claw_linkml_loader_lock is lock
        with builder._STABLE_PRODUCER._pure_linkml_loader():
            assert module.DupCheckYamlLoader is not outer
            assert lock._is_owned()
        assert module.DupCheckYamlLoader is outer
        assert lock._is_owned()
    assert module.DupCheckYamlLoader is original
    assert not lock._is_owned()


def test_other_shared_lock_owner_cannot_observe_temporary_replacement(monkeypatch, schema_runtime):
    _, module = schema_runtime
    original = module.DupCheckYamlLoader
    lock = threading.RLock()
    monkeypatch.setattr(module, "_claw_linkml_loader_lock", lock, raising=False)
    attempted, entered = threading.Event(), threading.Event()
    failures = []

    def worker():
        attempted.set()
        try:
            with builder._STABLE_PRODUCER._pure_linkml_loader():
                assert module.DupCheckYamlLoader is not original
                entered.set()
        except BaseException as exc:
            failures.append(exc)

    with lock:
        thread = threading.Thread(target=worker)
        thread.start()
        assert attempted.wait(2)
        assert not entered.wait(0.2)
        assert module.DupCheckYamlLoader is original
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert not failures
    assert entered.is_set()
    assert module.DupCheckYamlLoader is original
