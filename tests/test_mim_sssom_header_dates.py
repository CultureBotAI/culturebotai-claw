"""MIM Rule G dates the mapping set by its rows, never the build clock (#681)."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    'mim_builder_header_dates', SCRIPTS / 'build_mim_ingredient_sssom.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def run_builder(tmp_path, monkeypatch, rows, output):
    """Exercise the real CLI/write path with offline row inputs."""
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'fixture.yaml').write_text('{}\n')
    class BuildClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2031, 1, 2, tzinfo=tz)

    monkeypatch.setattr(builder, 'datetime', BuildClock)
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


def test_missing_row_date_is_not_hidden_by_a_valid_one(tmp_path, monkeypatch):
    path = tmp_path / 'mapping.tsv'
    with pytest.raises(ValueError, match='mapping_date'):
        run_builder(tmp_path, monkeypatch,
                    [{'mapping_date': '2026-10-15'}, {'mapping_date': ''}], path)
    assert not path.exists()
