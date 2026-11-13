"""Synthetic DPAPI payloads and adapter classes; never read real key material."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.backends.dpapi_db import (
    SECRET_NAME,
    _validate_keys,
    migrate_existing_key_cache,
    open_dpapi_wechat_db,
)
from wechat_auto.storage import LocalSecretStore


def test_existing_cache_migration_protects_copy_without_modifying_source(tmp_path):
    cache = tmp_path / 'wechatauto_db/synthetic_account/keys.json'
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({'contact/contact.db': '00' * 32}), encoding='utf-8')
    original = cache.read_bytes()
    secrets = tmp_path / '.secrets'
    with patch('wechat_auto.backends.dpapi_db.tempfile.gettempdir', return_value=str(tmp_path)):
        result = migrate_existing_key_cache(secrets)
        assert migrate_existing_key_cache(secrets) == result
    assert cache.read_bytes() == original
    assert LocalSecretStore(secrets).load(SECRET_NAME) == result
    assert b'contact/contact.db' not in (secrets / f'{SECRET_NAME}.dpapi').read_bytes()


@pytest.mark.parametrize('value', [{}, {'contact.db': ''}, {'../outside.db': '00'},
                                  {'C:\\outside.db': '00'}, {'\\outside.db': '00'}, {'contact.db': 'not-hex'}])
def test_unusable_or_escaped_keys_are_rejected(value):
    with pytest.raises(RuntimeError, match='key cache'):
        _validate_keys(value)


@pytest.mark.parametrize('failure', [None, 'key', 'missing', 'consumer'])
def test_dpapi_opener_never_calls_default_constructor_and_cleans_workdir(tmp_path, failure):
    working = []

    class Adapter:
        def __init__(self):
            pytest.fail('Default database constructor must not run')

        def _collect_db_files(self):
            working.append(Path(self.workdir))
            return [] if failure == 'missing' else [
                ('contact/contact.db', str(tmp_path / 'contact/contact.db'), None),
                ('message/message_0.db', str(tmp_path / 'message/message_0.db'), None),
                ('sns/sns.db', str(tmp_path / 'sns/sns.db'), None),
            ]

        def _key_works(self, relative):
            return relative in self._keys and not (failure == 'key' and relative.startswith('message/'))

    payload = {'account': 'synthetic_account',
               'keys': {'contact/contact.db': '00' * 32, 'message/message_0.db': '00' * 32}}
    module = SimpleNamespace(WeChatDB=Adapter, auto_detect_db_dir=lambda: str(tmp_path))
    with (
        patch('wechat_auto.backends.dpapi_db.replica_module', return_value=module),
        patch('wechat_auto.backends.dpapi_db.LocalSecretStore') as store,
    ):
        store.return_value.load.return_value = payload
        try:
            with open_dpapi_wechat_db(tmp_path / '.secrets', include_message_family=True) as db:
                assert len(db._db_files) == 2
                assert db.keys_file == '<dpapi-managed>'
                if failure == 'consumer':
                    raise RuntimeError('synthetic consumer failure')
        except RuntimeError:
            assert failure is not None
        else:
            assert failure is None
    assert working and all(not path.exists() for path in working)


@pytest.mark.parametrize('account', ['../outside', 'C:\\outside', '..', '.', 'name.'])
def test_account_must_be_a_single_directory_component(tmp_path, account):
    payload = {'account': account, 'keys': {'contact/contact.db': '00' * 32}}
    module = SimpleNamespace(WeChatDB=object, auto_detect_db_dir=lambda: str(tmp_path))
    with (
        patch('wechat_auto.backends.dpapi_db.replica_module', return_value=module),
        patch('wechat_auto.backends.dpapi_db.LocalSecretStore') as store,
    ):
        store.return_value.load.return_value = payload
        with pytest.raises(RuntimeError, match='account configuration'), open_dpapi_wechat_db(tmp_path):
            pytest.fail('Invalid account must not yield a database')


def test_malformed_payload_stops_before_account_discovery(tmp_path):
    discover = MagicMock()
    module = SimpleNamespace(WeChatDB=object, auto_detect_db_dir=discover)
    with (
        patch('wechat_auto.backends.dpapi_db.replica_module', return_value=module),
        patch('wechat_auto.backends.dpapi_db.LocalSecretStore') as store,
    ):
        store.return_value.load.return_value = ['invalid payload']
        with pytest.raises(TypeError, match='account configuration'), open_dpapi_wechat_db(tmp_path):
            pytest.fail('Malformed payload must not yield a database')
    discover.assert_not_called()
