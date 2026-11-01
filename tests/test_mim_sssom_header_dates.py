"""MIM Rule G dates the mapping set by its rows, never the build clock (#681)."""

import importlib.util
import sys
from contextlib import nullcontext
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    'mim_builder_header_dates', SCRIPTS / 'build_mim_ingredient_sssom.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.fixture(autouse=True)
def offline_publication_inputs(tmp_path, monkeypatch):
    """Keep date tests on the native publisher without live repository inputs."""
    sssom_artifacts = builder._ARTIFACT_PRODUCER

    class FixtureLock:
        def lock(self, *args):
            return nullcontext()

    monkeypatch.setattr(sssom_artifacts, '_load_lock_manager', lambda root: FixtureLock)
    monkeypatch.setattr(builder, 'RESIDUAL_JSON', tmp_path / 'absent-residual.json')
    monkeypatch.setattr(builder, 'KGM_UNIFIED_TSV', tmp_path / 'absent-kgm.tsv.gz')
    monkeypatch.setattr(builder, 'MIM_PUBLISHED_SSSOM', tmp_path / 'absent-canonical.tsv')


def run_builder(tmp_path, monkeypatch, rows, output):
    """Exercise the real CLI/write path with offline row inputs."""
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'fixture.yaml').write_text('{}\n')
    class BuildClock(date):
        @classmethod
        def today(cls):
            return cls(2031, 1, 2)

    monkeypatch.setattr(builder, 'date', BuildClock)
    emitted = [dict(subject_id=f'MIM:record{i}', object_id=f'CHEBI:{i+1}',
                    predicate_id='skos:exactMatch', **row) for i, row in enumerate(rows)]
    monkeypatch.setattr(builder, 'MIM_INGREDIENTS_DIR', inputs)
    monkeypatch.setattr(builder, 'require_mech_roots', lambda *a, **kw: None)
    monkeypatch.setattr(builder, '_load_residual_categorization', lambda: {})
    monkeypatch.setattr(builder, '_load_kgm_source_index', lambda: {})
    monkeypatch.setattr(builder, '_load_kgm_labels', lambda: {})
    monkeypatch.setattr(builder, '_row_from_yaml', lambda *a, **kw: emitted)
    monkeypatch.setattr(sys, 'argv', ['builder', '--no-validate', '--no-preserve-validation',
                                   '--output', str(output)])
    builder.main()


def test_header_dates_follow_newest_row_not_build_date(tmp_path, monkeypatch):
    rows = [{'mapping_date': date} for date in ('2026-10-01', '2026-10-15', '2026-09-30')]
    path = tmp_path / 'mapping.tsv'
    run_builder(tmp_path, monkeypatch, rows, path)
    text = path.read_text()
    assert '# mapping_set_version: "2026-10-15"\n' in text
    assert '# mapping_date: "2026-10-15"\n' in text
    assert [row['mapping_date'] for row in rows] == ['2026-10-01', '2026-10-15', '2026-09-30']


@pytest.mark.parametrize('rows', [[], [{}], [{'mapping_date': ''}],
                                [{'mapping_date': 'not-a-date'}],
                                [{'mapping_date': '2026-02-30'}]])
def test_no_usable_row_date_refuses_to_replace_existing_output(tmp_path, monkeypatch, rows):
    path = tmp_path / 'mapping.tsv'
    path.write_text('previous output\n')
    with pytest.raises(ValueError, match='mapping_date'):
        run_builder(tmp_path, monkeypatch, rows, path)
    assert path.read_text() == 'previous output\n'


def test_missing_row_date_is_preserved_for_rule_f(tmp_path, monkeypatch):
    path = tmp_path / 'mapping.tsv'
    run_builder(tmp_path, monkeypatch,
                [{'mapping_date': '2026-10-15'}, {'mapping_date': ''}], path)
    assert '# mapping_date: "2026-10-15"' in path.read_text()
    assert read_rows(path)[1]['mapping_date'] == ''


def read_rows(path):
    import csv
    return list(csv.DictReader(
        (line for line in path.read_text().splitlines() if not line.startswith('#')),
        delimiter='\t',
    ))


def test_all_dateless_subjects_are_reported_before_replacing_output(tmp_path, monkeypatch):
    path = tmp_path / 'mapping.tsv'
    path.write_text('previous output\n')
    with pytest.raises(ValueError, match='mapping_date') as error:
        run_builder(tmp_path, monkeypatch, [{'mapping_date': ''}, {}], path)
    assert 'MIM:record0' in str(error.value)
    assert 'MIM:record1' in str(error.value)
    assert path.read_text() == 'previous output\n'


def test_all_malformed_row_dates_are_reported_before_replacing_output(tmp_path, monkeypatch):
    path = tmp_path / 'mapping.tsv'
    path.write_text('previous output\n')
    with pytest.raises(ValueError, match='mapping_date') as error:
        run_builder(tmp_path, monkeypatch, [
            {'mapping_date': '2026-10-15'},
            {'mapping_date': '2026-02-30'},
            {'mapping_date': '２０２６-10-15'},
        ], path)
    assert 'MIM:record1' in str(error.value)
    assert 'MIM:record2' in str(error.value)
    assert path.read_text() == 'previous output\n'


@pytest.mark.parametrize('history_date', ['２０２６-10-15', '٢٠٢٦-10-15'])
def test_non_ascii_history_date_cannot_replace_output(tmp_path, monkeypatch, history_date):
    """#682: exercise native row extraction as well as the CLI's write guard."""
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    record = inputs / 'Water.yaml'
    record.write_text(
        'identifier: CHEBI:15377\n'
        'preferred_term: water\n'
        'mapping_status: MAPPED\n'
        'ontology_mapping:\n'
        '  ontology_id: CHEBI:15377\n'
        '  ontology_label: water\n'
        '  mapping_quality: EXACT_MATCH\n'
        'curation_history:\n'
        f'  - timestamp: "{history_date}T00:00:00Z"\n',
        encoding='utf-8',
    )
    assert builder._row_from_yaml(record, {}, {}, {}, {})[0]['mapping_date'] == ''
    output = tmp_path / 'mapping.tsv'
    output.write_text('previous output\n')
    monkeypatch.setattr(builder, 'MIM_INGREDIENTS_DIR', inputs)
    monkeypatch.setattr(builder, 'require_mech_roots', lambda *a, **kw: None)
    monkeypatch.setattr(builder, '_load_residual_categorization', lambda: {})
    monkeypatch.setattr(builder, '_load_kgm_source_index', lambda: {})
    monkeypatch.setattr(builder, '_load_kgm_labels', lambda: {})
    monkeypatch.setattr(builder, '_load_chebi_labels', lambda *a: {'CHEBI:15377': 'water'})
    monkeypatch.setattr(sys, 'argv', ['builder', '--no-validate', '--no-preserve-validation',
                                   '--output', str(output)])
    with pytest.raises(ValueError, match='mapping_date'):
        builder.main()
    assert output.read_text() == 'previous output\n'


def test_dateless_record_reaches_rule_f_as_an_empty_cell(tmp_path, monkeypatch, capsys):
    """Native YAML extraction and CLI output keep every dateless record visible."""
    inputs = tmp_path / 'records'
    inputs.mkdir()
    base = (
        'identifier: CHEBI:15377\n'
        'mapping_status: MAPPED\n'
        'ontology_mapping:\n'
        '  ontology_id: CHEBI:15377\n'
        '  ontology_label: water\n'
        '  mapping_quality: EXACT_MATCH\n'
    )
    (inputs / 'Dated.yaml').write_text(base + 'preferred_term: Dated\n'
        'curation_history:\n  - timestamp: "2026-10-15T00:00:00Z"\n')
    (inputs / 'Dateless.yaml').write_text(base + 'preferred_term: Dateless\n')
    output = tmp_path / 'mapping.tsv'
    monkeypatch.setattr(builder, 'MIM_INGREDIENTS_DIR', inputs)
    monkeypatch.setattr(builder, 'require_mech_roots', lambda *a, **kw: None)
    monkeypatch.setattr(builder, '_load_residual_categorization', lambda: {})
    monkeypatch.setattr(builder, '_load_kgm_source_index', lambda: {})
    monkeypatch.setattr(builder, '_load_kgm_labels', lambda: {})
    monkeypatch.setattr(builder, '_load_chebi_labels', lambda *a: {'CHEBI:15377': 'water'})
    monkeypatch.setattr(sys, 'argv', ['builder', '--no-validate', '--no-preserve-validation',
                                   '--output', str(output)])
    builder.main()
    dates = {row['subject_id']: row['mapping_date'] for row in read_rows(output)}
    assert dates == {'MIM:Dated': '2026-10-15', 'MIM:Dateless': ''}
    assert '# mapping_date: "2026-10-15"' in output.read_text()
    warning = capsys.readouterr().out
    assert 'Dateless.yaml' in warning and 'Rule F' in warning
