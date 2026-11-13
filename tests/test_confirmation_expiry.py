from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tests.test_mcp_monitor import _call
from wechat_auto.mcp_server import create_server
from wechat_auto.memory.store import MemoryStore


def _freeze_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime.fromisoformat('2026-10-24T12:00:00.700000+00:00')
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr('wechat_auto.memory.store.datetime', Clock)


@pytest.mark.parametrize('kind', ['reply', 'action'])
@pytest.mark.parametrize('operation', ['confirm', 'consume'])
@pytest.mark.parametrize('expiry,allowed', [
    ('2026-10-24T19:00:00+08:00', False),
    ('2026-10-24T12:00:00Z', False),
    ('2026-10-24T08:00:00-05:00', True),
    ('2026-10-24T23:00:00', False),
    ('not-a-time', False),
    ('2026-10-24T12:00:00.500000+00:00', False),
    ('2026-10-24T12:00:00.700000+00:00', False),
    ('2026-10-24T12:00:00.900000+00:00', True),
])
def test_confirmation_expiry_uses_instants_and_rejects_unknown_time(tmp_path, monkeypatch, kind, operation, expiry, allowed):
    _freeze_clock(monkeypatch)
    with MemoryStore(tmp_path / 'memory.db') as store:
        if kind == 'reply':
            conversation = store.ensure_conversation('u', conversation_type='direct')
            target = store.create_reply_draft(conversation, 'trigger', 'exact text', 'context')
            table, key = 'reply_drafts', 'draft_id'
        else:
            target = store.create_pending_action('like_moment', 'post', {'moment_id': 'post'})
            table, key = 'pending_actions', 'action_id'
        def confirm():
            return store.confirm_reply_draft(target) if kind == 'reply' else store.confirm_pending_action(target)

        token = confirm() if operation == 'consume' else None
        store._connection.execute(f'UPDATE {table} SET expires_at=? WHERE {key}=?', (expiry, target))
        store._connection.commit()

        def attempt():
            if operation == 'confirm':
                return confirm()
            if kind == 'reply':
                return store.consume_confirmation(token, conversation, 'exact text')
            return store.consume_pending_action(target, token)

        if allowed:
            assert attempt()
        else:
            with pytest.raises(PermissionError):
                attempt()
            status = store._connection.execute(f'SELECT status FROM {table} WHERE {key}=?', (target,)).fetchone()[0]
            assert status == ('pending' if operation == 'confirm' else 'confirmed')


@pytest.mark.parametrize('operation', ['confirm', 'send'])
def test_expired_reply_is_rejected_at_mcp_boundary_before_ui(tmp_path, monkeypatch, operation):
    _freeze_clock(monkeypatch)
    basic = MagicMock()
    backend = MagicMock()
    backend.get_context.return_value = [{"local_id": 7, "sort_seq": 11}]
    server = create_server(memory_db=str(tmp_path / 'memory.db'), memory_root=str(tmp_path / 'memory'),
                           basic_skill=basic, conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        cv = store.ensure_conversation('u', conversation_type='direct')
        store.link_conversation_person(cv, store.ensure_person('u'), role='other')
        draft = store.create_reply_draft(cv, 'u:7:11::', 'exact text', 'context')
        token = store.confirm_reply_draft(draft) if operation == 'send' else None
        store._connection.execute('UPDATE reply_drafts SET expires_at=? WHERE draft_id=?',
                                  ('2026-10-24T19:00:00+08:00', draft))
        store._connection.commit()
        name = 'reply.confirm' if operation == 'confirm' else 'reply.send_confirmed'
        arguments = ({'draft_id': draft} if operation == 'confirm' else
                     {'confirmation_id': token, 'conversation_id': cv, 'contact': 'u', 'text': 'exact text'})
        with pytest.raises(Exception) as caught:
            _call(server, name, arguments)
        assert isinstance(caught.value.__cause__, PermissionError)
        basic.execute.assert_not_called()
        status = store._connection.execute('SELECT status FROM reply_drafts WHERE draft_id=?', (draft,)).fetchone()[0]
        assert status == ('pending' if operation == 'confirm' else 'confirmed')
    finally:
        store.close()
