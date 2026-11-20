import json
from types import SimpleNamespace
import validate_changed_skins as changed


def test_large_mirror_diff_checks_each_release_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(changed.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout=''))
    monkeypatch.setattr(changed, 'validate_entry', lambda e: [])
    calls = []
    def release(*args):
        calls.append(args)
        return {'draft': False}
    monkeypatch.setattr(changed, 'http_get_json', release)
    monkeypatch.setattr(changed, 'list_release_assets', lambda *a: [
        {'name': f'{i}.manicskin', 'state': 'uploaded', 'size': 10} for i in range(2000)])
    paths = []
    for i in range(2000):
        path = f'{i}.json'
        with open(path, 'w') as f:
            json.dump({'downloadURL': f'https://github.com/Provenance-Emu/skins/releases/download/mirror/{i}.manicskin'}, f)
        paths.append(path)
    assert changed.validate('base', paths, check=lambda u: False)
    assert len(calls) == 1
    with open(paths[-1], 'w') as f:
        json.dump({'downloadURL': 'https://github.com/Provenance-Emu/skins/releases/download/mirror/missing.manicskin'}, f)
    assert not changed.validate('base', [paths[-1]])


def test_unchanged_bad_link_is_schema_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    entry = {'downloadURL': 'https://example.com/broken.deltaskin'}
    (tmp_path / 'skin.json').write_text(json.dumps(entry))
    monkeypatch.setattr(changed.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(entry)))
    monkeypatch.setattr(changed, 'validate_entry', lambda e: [])
    assert changed.validate('base', ['skin.json'], check=lambda u: (_ for _ in ()).throw(AssertionError('Must not fetch')))
