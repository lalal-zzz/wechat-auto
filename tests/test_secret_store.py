"""Exercise DPAPI using synthetic values, never real account credentials."""

from unittest.mock import patch

import pytest

from wechat_auto.storage.secret_store import LocalSecretStore


def test_real_dpapi_roundtrip_and_replacement(tmp_path):
    store = LocalSecretStore(tmp_path / '.secrets')
    assert store.load('synthetic') is None
    value = {'synthetic_token': 'fixture-only', 'label': '合成数据'}
    path = store.save('synthetic', value)
    assert b'fixture-only' not in path.read_bytes()
    assert store.load('synthetic') == value
    store.save('synthetic', {'synthetic_token': 'replacement'})
    assert store.load('synthetic') == {'synthetic_token': 'replacement'}


@pytest.mark.parametrize('name', ['../escape', '..\\escape', 'C:\\escape', '/escape',
                                  '', '.', 'CON', 'nul.data', 'LPT1', 'name:stream'])
def test_secret_names_cannot_escape_or_use_windows_devices(tmp_path, name):
    store = LocalSecretStore(tmp_path / '.secrets')
    with pytest.raises(ValueError):
        store.save(name, {'synthetic': True})
    with pytest.raises(ValueError):
        store.load(name)
    assert list(store.directory.iterdir()) == []


def test_failed_atomic_replace_preserves_previous_secret(tmp_path):
    store = LocalSecretStore(tmp_path / '.secrets')
    path = store.save('synthetic', {'version': 1})
    original = path.read_bytes()
    with patch('wechat_auto.storage.secret_store.os.replace', side_effect=OSError('simulated')), pytest.raises(OSError):
        store.save('synthetic', {'version': 2})
    assert path.read_bytes() == original
    assert store.load('synthetic') == {'version': 1}
    assert list(store.directory.iterdir()) == [path]


def test_corrupted_protected_blob_is_rejected_without_replacement(tmp_path):
    import pywintypes

    store = LocalSecretStore(tmp_path / '.secrets')
    path = store.save('synthetic', {'version': 1})
    path.write_bytes(b'synthetic-corruption')
    with pytest.raises(pywintypes.error):
        store.load('synthetic')
    assert path.read_bytes() == b'synthetic-corruption'
