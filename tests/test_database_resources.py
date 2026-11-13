"""Database owners close their own DPAPI context, never an injected connection."""

import gc
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.backends import DatabaseConversationBackend, DatabaseMomentsBackend


@pytest.mark.parametrize('backend_type', [DatabaseConversationBackend, DatabaseMomentsBackend])
def test_default_backend_owns_dpapi_context_and_rejects_use_after_close(tmp_path, backend_type):
    db = MagicMock()
    events = []

    @contextmanager
    def database(*args, **kwargs):
        events.append(('open', kwargs))
        try:
            yield db
        finally:
            events.append(('close', None))

    module = SimpleNamespace(MomentDB=MagicMock(), WeChatDB=MagicMock(side_effect=AssertionError('forbidden constructor')))
    with (
        patch('wechat_auto.backends.database_resource.open_dpapi_wechat_db', side_effect=database) as opened,
        patch('wechat_auto.backends.wechat_moments_db.replica_module', return_value=module),
        backend_type(secret_dir=tmp_path / '.secrets') as backend,
    ):
        assert backend._db is db
        assert events[0][0] == 'open' and len(events) == 1
        opened.assert_called_once()
    backend.close()
    assert [event[0] for event in events] == ['open', 'close']
    db.close.assert_not_called()
    module.WeChatDB.assert_not_called()
    with pytest.raises(RuntimeError, match='closed'):
        _ = backend._db


@pytest.mark.parametrize('backend_type', [DatabaseConversationBackend, DatabaseMomentsBackend])
def test_injected_database_lifetime_remains_with_caller(backend_type):
    db = MagicMock()
    with (
        patch('wechat_auto.backends.database_resource.open_dpapi_wechat_db') as opened,
        patch('wechat_auto.backends.wechat_moments_db.replica_module'),
    ):
        with backend_type(db) as backend:
            assert backend._db is db
        backend.close()
    opened.assert_not_called()
    db.close.assert_not_called()


def test_moments_initialization_failure_releases_owned_context():
    context = MagicMock()
    with (
        patch('wechat_auto.backends.database_resource.open_dpapi_wechat_db', return_value=context),
        patch('wechat_auto.backends.wechat_moments_db.replica_module') as module,
    ):
        module.return_value.MomentDB.side_effect = RuntimeError('synthetic initialization failure')
        with pytest.raises(RuntimeError, match='synthetic initialization failure'):
            DatabaseMomentsBackend()
    context.__exit__.assert_called_once()


def test_unclosed_owned_backend_has_final_cleanup():
    context = MagicMock()
    with patch('wechat_auto.backends.database_resource.open_dpapi_wechat_db', return_value=context):
        backend = DatabaseConversationBackend()
    del backend
    gc.collect()
    context.__exit__.assert_called_once()
