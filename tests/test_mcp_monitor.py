import asyncio
import json
from unittest.mock import MagicMock

from wechat_auto.mcp_server import create_server
from wechat_auto.version import (
    CONTACT_ACTION_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION,
    __version__,
)


class _ConversationBackend:
    def __init__(self):
        self.since_sequences = []

    def poll(self, username, since_seq, limit=200):
        self.since_sequences.append(since_seq)
        messages = [] if since_seq >= 11 else [{
            "local_id": 7,
            "server_id": "server-7",
            "sort_seq": 11,
            "sender_id": "1",
            "sender_username": "wxid_test_friend",
            "content": "new",
            "create_time": 1788192000,
        }]
        return {"username": username, "messages": messages,
                "all_messages": messages, "watermark": 11}

    def get_context(self, username, limit):
        return [{"sort_seq": 11, "sender_username": "wxid_test_friend",
                 "content": "new", "create_time": 1788192000}]


def _call(server, name, arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    return result.structured_content or json.loads(result.content[0].text)


def test_compact_window_and_navigation_tools_delegate_only_to_basic_skill(tmp_path):
    basic = MagicMock()
    basic.inspect_windows.return_value = []
    basic.resolve_target_window.return_value = {'ok': False, 'error': 'target_page_not_found'}
    basic.navigate_page.return_value = {'success': False, 'stop_reason': 'navigation_postcondition_failed'}
    basic.restore_main_window.return_value = {'success': True, 'sent': False}
    server = create_server(memory_db=str(tmp_path / 'memory.sqlite3'),
                           memory_root=str(tmp_path / 'memory'), basic_skill=basic)
    try:
        _call(server, 'vision.inspect_windows', {})
        basic.inspect_windows.assert_called_once_with(include_ocr=True)
        assert _call(server, 'vision.resolve_window', {'page': 'moments_person'})['ok'] is False
        basic.resolve_target_window.assert_called_once_with('moments_person', presentation=None, hwnd=None)
        assert _call(server, 'actions.navigate_page', {'page': 'moments_feed'})['success'] is False
        basic.navigate_page.assert_called_once_with('moments_feed', max_steps=6)
        assert _call(server, 'actions.restore_main_window', {})['sent'] is False
        basic.restore_main_window.assert_called_once_with(max_steps=6)
    finally:
        server._wechat_auto_store.close()


def test_monitor_uses_persistent_cursor_and_only_dirties_delta_once(tmp_path):
    backend = _ConversationBackend()
    server = create_server(
        memory_db=str(tmp_path / "memory.sqlite3"),
        memory_root=str(tmp_path / "memory"),
        conversation_backend=backend,
    )
    try:
        first = _call(server, "monitor.run_once", {"username": "wxid_test_friend"})
        second = _call(server, "monitor.run_once", {"username": "wxid_test_friend"})
        store = server._wechat_auto_store
        conversation_id = first["conversation_id"]

        assert backend.since_sequences == [0, 11]
        assert first["watermark"] == second["watermark"] == 11
        assert len(first["new_messages"]) == 1
        assert second["new_messages"] == []
        assert store.get_sync_cursor("reply_monitor", "wxid_test_friend") == "11"
        jobs = store.next_jobs(10)
        assert [(job["job_type"], job["scope_id"], job["period"]) for job in jobs] == [
            ("monthly_analysis", conversation_id, "2026-09")
        ]
    finally:
        server._wechat_auto_store.close()


def test_status_exposes_contract_versions(tmp_path):
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"),
                           memory_root=str(tmp_path / "memory"))
    try:
        result = _call(server, "status.summary", {})
        assert result["versions"] == {
            "application": __version__, "memory_schema": 3,
            "mcp_protocol": MCP_PROTOCOL_VERSION,
            "contact_action_protocol": CONTACT_ACTION_PROTOCOL_VERSION,
        }
    finally:
        server._wechat_auto_store.close()


def test_contact_state_tools_roundtrip_and_known_block_prevents_dispatch(tmp_path):
    from unittest.mock import MagicMock
    basic = MagicMock()
    basic.execute.return_value = {'sent': True}
    server = create_server(memory_db=str(tmp_path / 'memory.sqlite3'),
                           memory_root=str(tmp_path / 'memory'), basic_skill=basic)
    store = server._wechat_auto_store
    try:
        person = store.ensure_person('wxid_test_test')
        conversation = store.ensure_conversation('wxid_test_test', conversation_type='direct')
        store._connection.execute('INSERT INTO conversation_members VALUES(?,?,?,NULL,NULL)',
                                  (conversation, person, 'member'))
        store._connection.commit()
        _call(server, 'entities.record_contact_state',
              {'person_id': person, 'relation': 'peer_block', 'value': 'blocked',
               'source': 'user_confirmation', 'evidence_ref': 'review',
               'observation_key': 'one', 'confirmed': True})
        state = _call(server, 'entities.contact_state', {'person_id': person})
        assert state['current']['peer_block'] == 'blocked'
        assert state['current']['local_block'] == 'unknown'
        draft = store.create_reply_draft(conversation, 'trigger', 'draft text', 'context')
        confirmation = store.confirm_reply_draft(draft)
        try:
            _call(server, 'reply.send_confirmed', {'confirmation_id': confirmation,
                  'conversation_id': conversation, 'contact': 'test', 'text': 'draft text'})
        except Exception as exc:
            # MCP SDK masks unexpected exception text at the transport boundary.
            assert isinstance(exc.__cause__, PermissionError)
            assert 'blocks dispatch' in str(exc.__cause__)
        basic.execute.assert_not_called()
        row = store._connection.execute('SELECT status FROM reply_drafts WHERE draft_id=?', (draft,)).fetchone()
        assert row[0] == 'confirmed'
    finally:
        store.close()
