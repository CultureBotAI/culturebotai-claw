"""Permanent owner provenance is additive to the unchanged legacy resolver (#1286)."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'unified_owner_reference_builder', ROOT / 'scripts/build_unified_ingredient_mapping.py',
)
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)
NATIVE = ROOT / 'tests/resources/stable_mim/native_stable_ids.py.txt'
CONTRACT = NATIVE.read_bytes()
PIN = hashlib.sha256(CONTRACT).hexdigest()
PREFIX = 'https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_'
OLD_COLUMNS = ['ingredient_name', 'occurrence_count', 'chebi_id', 'cas_rn',
               'kg_microbe_node_id', 'mim_id', 'culturemech_term_id', 'mapping_status',
               'synonyms', 'example_media']


def write(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def owner(number, identifier, label, status='MAPPED', **extra):
    value = dict(mim_id=f'MIM:{number:07d}', identifier=identifier, preferred_term=label,
                 mapping_status=status, legacy_identifiers=[f'MIM:Original_{number}'])
    value.update(extra)
    return value


def install(root, records, *, stable=True, total=None, lifecycle=''):
    for relative, record in records.items():
        data = deepcopy(record)
        if not stable:
            data.pop('mim_id')
            data.pop('legacy_identifiers', None)
        write(root, relative, data)
    if stable:
        total = total if total is not None else len(records)
        ids = root / 'data/ids'
        ids.mkdir(parents=True)
        (ids / 'mim_id_registry.tsv').write_text(
            'mim_id\tlabel_at_minting\tminted_on\tstatus\treplaced_by\n' + ''.join(
                f'MIM:{n:07d}\tOwner {n}\t2026-11-08\tactive\t\n' for n in range(1, total + 1)))
        (ids / 'mim_id_lifecycle.tsv').write_text(
            'mim_id\tstatus\treplaced_by\tchanged_at\treason\n' + lifecycle)
        source = root / 'src/mediaingredientmech/stable_ids.py'
        source.parent.mkdir(parents=True)
        source.write_bytes(CONTRACT)
    return root


def rows(root, observations, *, stable=True, rejections=None):
    indexes = b.load_mim_index(root, native_contract_sha256=PIN if stable else None)
    result = b.build_unified_rows(observations, *indexes, rejections=rejections)
    return result, indexes


def observed(*names):
    return {name: {'term_id': '', 'count': 2 if i == 0 else 1,
                   'example_media': ['CultureMech:1']} for i, name in enumerate(names)}


def projection(items):
    return [{key: row[key] for key in OLD_COLUMNS} for row in items]


def test_old_column_projection_and_row_order_are_identical(tmp_path):
    records = {
        'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha', synonyms=['Old Alpha']),
        'data/ingredients/unmapped/B.yaml': owner(2, 'UNMAPPED_2', 'Unknown', 'UNMAPPED'),
        'data/ingredients/mapped/C.yaml': owner(3, 'CAS-RN:123-45-6', 'Salt'),
    }
    obs = observed('Old Alpha', 'Unknown', 'Salt', 'No owner')
    legacy, _ = rows(install(tmp_path / 'old', records, stable=False), obs, stable=False)
    current, _ = rows(install(tmp_path / 'current', records), obs)
    assert b.COLUMNS == [*OLD_COLUMNS, 'mim_record_id']
    assert projection(current) == projection(legacy)
    assert [r['ingredient_name'] for r in current] == list(obs)
    assert [r['mim_id'] for r in current] == ['CHEBI:1', 'UNMAPPED_2', 'CAS-RN:123-45-6', '']
    assert [r['mim_record_id'] for r in current] == ['MIM:0000001', 'MIM:0000002', 'MIM:0000003', '']
    assert all(r['mim_record_id'] == '' for r in legacy)
    target = tmp_path / 'comparison.tsv'
    b.write_tsv(current, target)
    with target.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        assert reader.fieldnames == [*OLD_COLUMNS, 'mim_record_id']
        saved = list(reader)
    assert saved[0]['mim_id'] == 'CHEBI:1' and saved[0]['mim_record_id'] == 'MIM:0000001'


def test_rename_move_grounding_and_unmapped_state_preserve_selected_owner(tmp_path):
    record = owner(1, 'CHEBI:1', 'Original label', synonyms=['Retained name'])
    root = install(tmp_path, {'data/ingredients/mapped/Original.yaml': record})
    before, _ = rows(root, observed('Retained name'))
    (root / 'data/ingredients/mapped/Original.yaml').unlink()
    record.update(identifier='UNMAPPED_0019', preferred_term='Corrected label', mapping_status='UNMAPPED')
    write(root, 'data/ingredients/unmapped/Renamed.yaml', record)
    after, indexes = rows(root, observed('Retained name'))
    assert before[0]['mim_record_id'] == after[0]['mim_record_id'] == 'MIM:0000001'
    assert after[0]['mim_id'] == 'UNMAPPED_0019' and after[0]['mapping_status'] == 'UNMAPPED'
    assert all(after[0][key] == '' for key in ['chebi_id', 'culturemech_term_id', 'cas_rn'])
    assert indexes[0].owner_inputs.native_prefix == PREFIX


def test_source_hold_and_unresolved_rejection_gain_no_borrowed_reference(tmp_path):
    records = {
        'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha'),
        'data/ingredients/unmapped/R.yaml': owner(2, 'CHEBI:2', 'Rejected name', 'REJECTED'),
    }
    obs = observed('Held source', 'Rejected name', 'Alpha')
    obs['Held source']['term_id'] = 'CHEBI:1'
    result, _ = rows(install(tmp_path, records), obs,
                     rejections={('source_label', 'held source', 'CHEBI:1'): ''})
    by_name = {r['ingredient_name']: r for r in result}
    for name in ('Held source', 'Rejected name'):
        assert all(by_name[name][key] == '' for key in
                   ['mim_record_id', 'mim_id', 'chebi_id', 'culturemech_term_id', 'cas_rn'])
    assert by_name['Alpha']['mim_record_id'] == 'MIM:0000001'
    assert by_name['Held source']['occurrence_count'] == 2


def test_selected_ambiguous_record_reference_does_not_resolve_its_mapping(tmp_path):
    record = owner(1, 'CHEBI:9', 'Ambiguous material', 'AMBIGUOUS',
                   chemical_properties={'cas_rn': '123-45-6'})
    result, _ = rows(install(tmp_path, {'data/ingredients/unmapped/A.yaml': record}),
                     observed('Ambiguous material'))
    assert result[0]['mim_record_id'] == 'MIM:0000001'  # record provenance, no identity claim
    assert result[0]['mapping_status'] == 'AMBIGUOUS'
    assert all(result[0][key] == '' for key in ['mim_id', 'chebi_id', 'cas_rn', 'culturemech_term_id'])


def test_shared_alias_never_supplies_or_reselects_permanent_owner(tmp_path):
    a = owner(1, 'CHEBI:9', 'Alpha', legacy_identifiers=['shared:alias'])
    c = owner(2, 'CHEBI:9', 'Beta', legacy_identifiers=['shared:alias'])
    # The native index permits ambiguous aliases but refuses using one as a lookup.
    result, _ = rows(install(tmp_path, {'data/ingredients/mapped/A.yaml': a,
                                      'data/ingredients/mapped/B.yaml': c}),
                     observed('Alpha', 'Beta', 'shared:alias'))
    assert [r['mim_record_id'] for r in result] == ['MIM:0000001', 'MIM:0000002', '']
    assert result[0]['mim_id'] == result[1]['mim_id'] == 'CHEBI:9'


def test_existing_merge_selection_uses_survivor_not_tombstone_id(tmp_path):
    records = {
        'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Survivor'),
        'data/ingredients/unmapped/R.yaml': owner(2, 'CHEBI:2', 'Old name', 'REJECTED',
                                                representative='CHEBI:1'),
    }
    lifecycle = 'MIM:0000003\tmerged\tMIM:0000001\t2026-11-09T00:00:00Z\tOld record retired\n'
    result, _ = rows(install(tmp_path, records, total=3, lifecycle=lifecycle), observed('Old name'))
    assert result[0]['mim_record_id'] == 'MIM:0000001'
    assert result[0]['mim_id'] == 'CHEBI:1'
    assert result[0]['mapping_status'] == 'MAPPED'


@pytest.mark.parametrize('value', [None, '', 'MIM:1', 'MIM:0000000', 'MIM:0000002',
                                 'mim:0000001', 'MIM:００００００１'])
def test_invalid_current_id_is_never_legacy_blank(tmp_path, value):
    record = owner(1, 'CHEBI:1', 'Alpha')
    record['mim_id'] = value
    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': record})
    with pytest.raises(ValueError):
        b.load_mim_index(root, native_contract_sha256=PIN)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'unregistered', 'retired',
                                     'owner_omitted', 'registry_missing', 'lifecycle_missing'])
def test_complete_native_inventory_and_lifecycle_are_required(tmp_path, mutation):
    a, c = owner(1, 'CHEBI:1', 'Alpha'), owner(2, 'CHEBI:2', 'Beta')
    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': a,
                              'data/ingredients/unmapped/B.yaml': c})
    if mutation in {'missing', 'duplicate', 'unregistered'}:
        if mutation == 'missing':
            c.pop('mim_id')
        else:
            c['mim_id'] = 'MIM:0000001' if mutation == 'duplicate' else 'MIM:0000003'
        write(root, 'data/ingredients/unmapped/B.yaml', c)
    elif mutation == 'retired':
        with (root / 'data/ids/mim_id_lifecycle.tsv').open('a') as stream:
            stream.write('MIM:0000001\tmerged\tMIM:0000002\t2026-11-09T00:00:00Z\tretired\n')
    elif mutation == 'owner_omitted':
        (root / 'data/ingredients/unmapped/B.yaml').unlink()
    else:
        name = 'mim_id_registry.tsv' if mutation == 'registry_missing' else 'mim_id_lifecycle.tsv'
        (root / 'data/ids' / name).unlink()
    with pytest.raises(ValueError):
        b.load_mim_index(root, native_contract_sha256=PIN)


@pytest.mark.parametrize('selection', [None, '0' * 64])
def test_native_source_requires_explicit_matching_digest(tmp_path, selection):
    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha')})
    with pytest.raises(ValueError, match='contract|digest'):
        b.load_mim_index(root, native_contract_sha256=selection)


def test_present_but_null_id_without_ledgers_cannot_fall_back(tmp_path):
    write(tmp_path, 'data/ingredients/mapped/A.yaml', {'mim_id': None, 'preferred_term': 'Alpha'})
    with pytest.raises(ValueError, match='contract'):
        b.load_mim_index(tmp_path)


def test_duplicate_yaml_cannot_hide_current_identity(tmp_path):
    path = write(tmp_path, 'data/ingredients/mapped/A.yaml', {'preferred_term': 'Alpha'})
    path.write_text('preferred_term: Alpha\nmim_id: MIM:0000001\nmim_id: null\n')
    with pytest.raises(ValueError, match='Duplicate YAML key'):
        b.load_mim_index(tmp_path)


@pytest.mark.parametrize('mutation', ['owner', 'native', 'mint', 'lifecycle', 'membership'])
def test_changed_validated_input_refuses_before_rows(tmp_path, mutation):
    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha')})
    indexes = b.load_mim_index(root, native_contract_sha256=PIN)
    paths = {'owner': 'data/ingredients/mapped/A.yaml', 'native': 'src/mediaingredientmech/stable_ids.py',
             'mint': 'data/ids/mim_id_registry.tsv', 'lifecycle': 'data/ids/mim_id_lifecycle.tsv',
             'membership': 'data/ingredients/unmapped/B.yaml'}
    path = root / paths[mutation]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('ab') as stream:
        stream.write(b'\n')
    with pytest.raises(ValueError, match='changed'):
        b.build_unified_rows(observed('Alpha'), *indexes)


def test_current_cli_requires_pin_then_writes_additive_reference(tmp_path, monkeypatch):
    root = install(tmp_path / 'mim', {'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha')})
    cm = tmp_path / 'cm'
    cm.mkdir()
    output = tmp_path / 'result.tsv'
    # Root/recipe fixtures only: native owner validation, resolution and TSV writer are real.
    monkeypatch.setattr(b, 'require_mech_roots', lambda *a, **k: None)
    monkeypatch.setattr(b, 'scan_culturemech', lambda path: observed('Alpha'))
    argv = ['builder', '--mim', str(root), '--culturemech', str(cm), '--output', str(output), '--format', 'tsv']
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(ValueError, match='contract'):
        b.main()
    assert not output.exists()
    monkeypatch.setattr(sys, 'argv', [*argv, '--mim-stable-id-contract-sha256', PIN])
    b.main()
    with output.open() as stream:
        row = next(csv.DictReader(stream, delimiter='\t'))
    assert row['mim_record_id'] == 'MIM:0000001' and row['mim_id'] == 'CHEBI:1'


def test_genuine_contract_and_namespace_compatibility_are_not_reinvented(tmp_path):
    origin = json.loads(NATIVE.with_name('ORIGIN.json').read_text())
    assert origin['sha256'] == PIN
    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha')})
    indexes = b.load_mim_index(root, native_contract_sha256=PIN)
    assert indexes[0].owner_inputs.native_prefix == PREFIX
    # The value is the native MIM CURIE, not a synthesized KG local primary or filename.
    assert indexes[0]['alpha']['mim_record_id'] == 'MIM:0000001'
    assert indexes[0]['alpha']['kg_microbe_node_id'] == ''


def test_native_yaml_shared_sequences_remain_valid(tmp_path):
    shared = [{'source': 'retained evidence'}]
    record = owner(1, 'CHEBI:1', 'Alpha', first=shared, second=shared)
    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': record})
    raw = (root / 'data/ingredients/mapped/A.yaml').read_text()
    assert '&id001' in raw and '*id001' in raw
    result, _ = rows(root, observed('Alpha'))
    assert result[0]['mim_record_id'] == 'MIM:0000001'


@pytest.mark.parametrize('alias_kind', ['symlink', 'hardlink'])
def test_aliased_native_source_is_not_executed(tmp_path, alias_kind):
    import os

    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha')})
    source = root / 'src/mediaingredientmech/stable_ids.py'
    retained = root / 'original.py'
    source.rename(retained)
    if alias_kind == 'symlink':
        source.symlink_to(retained)
    else:
        os.link(retained, source)
    with pytest.raises(ValueError, match='Symlink|unaliased'):
        b.load_mim_index(root, native_contract_sha256=PIN)


def test_changed_native_source_fails_before_executable_side_effect(tmp_path):
    root = install(tmp_path, {'data/ingredients/mapped/A.yaml': owner(1, 'CHEBI:1', 'Alpha')})
    marker = root / 'must-not-exist'
    source = root / 'src/mediaingredientmech/stable_ids.py'
    with source.open('a') as stream:
        stream.write(f'\nPath({str(marker)!r}).write_text("executed")\n')
    with pytest.raises(ValueError, match='digest'):
        b.load_mim_index(root, native_contract_sha256=PIN)
    assert not marker.exists()
