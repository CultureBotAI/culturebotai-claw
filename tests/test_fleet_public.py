"""Public membership is a projection; it never changes internal inventory."""
from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import FleetManifestError, load_fleet_manifest, parse_fleet_manifest
from kg_microbe_fleet.__main__ import main


def document():
    return yaml.safe_load(load_fleet_manifest().source.read_text())


@pytest.mark.parametrize('tags', [None, 'exclude-from-public', [1], [''], ['Upper'],
                                   ['two words'], ['x_y'], ['x', 'x'], [' x']])
def test_invalid_tags_refused(tags):
    raw = document()
    raw['mechs']['culturemech']['tags'] = tags
    with pytest.raises(FleetManifestError, match='tags'):
        parse_fleet_manifest(raw, Path('fixture.yaml'))


def test_public_projection_preserves_internal_inventory():
    raw = document()
    raw['mechs']['culturemech']['tags'] = ['exclude-from-public', 'research']
    raw['mechs']['traitmech']['tags'] = ['research']
    fleet = parse_fleet_manifest(raw, Path('fixture.yaml'))
    public = fleet.public()
    assert 'culturemech' in fleet.keys
    assert fleet.get('culturemech').tags == ('exclude-from-public', 'research')
    assert 'culturemech' not in public.keys
    assert 'traitmech' in public.keys
    assert public.public().keys == public.keys
    assert public.capability_names == fleet.capability_names
    assert set(public.environment_variables()) == set(public.keys)
    assert 'culturemech' not in public.with_capability('vendored_sync')


def test_all_excluded_yields_empty_public_fleet():
    raw = document()
    for mech in raw['mechs'].values():
        mech['tags'] = ['exclude-from-public']
    fleet = parse_fleet_manifest(raw, Path('fixture.yaml'))
    assert fleet.keys
    assert fleet.public().keys == ()


def test_cli_public_filter_precedes_serialization(tmp_path, monkeypatch, capsys):
    import json
    raw = document()
    raw['mechs']['culturemech']['tags'] = ['exclude-from-public']
    path = tmp_path / 'fleet.yaml'
    path.write_text(yaml.safe_dump(raw))
    monkeypatch.setenv('KG_MICROBE_FLEET_MANIFEST', str(path))
    assert main(['list', '--format', 'json']) == 0
    assert any(row['key'] == 'culturemech' for row in json.loads(capsys.readouterr().out))
    assert main(['list', '--public', '--format', 'json']) == 0
    output = capsys.readouterr().out
    assert 'CultureBotAI/CultureMech' not in output
    assert 'CULTUREMECH_ROOT' not in output
    assert 'traitmech' in output
