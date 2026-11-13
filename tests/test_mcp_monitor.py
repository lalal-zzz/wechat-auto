import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.mcp_server import create_server
from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.storage import HistoryStore, make_message_id
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


def _active_direct_conversation(store, target):
    conversation = store.ensure_conversation(target, conversation_type="direct")
    store.link_conversation_person(conversation, store.ensure_person(target), role="other")
    return conversation


def test_confirmed_reply_binds_stable_target_and_does_not_certify_unknown_result(tmp_path):
    basic = MagicMock()
    basic.execute.return_value = {'sent': False, 'success': False, 'dispatched': True}
    backend = MagicMock()
    backend.get_context.return_value = [{"local_id": 7, "sort_seq": 11}]
    server = create_server(memory_db=str(tmp_path / 'memory.sqlite3'),
                           memory_root=str(tmp_path / 'memory'), basic_skill=basic, conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        conversation = _active_direct_conversation(store, 'wxid_test_target')
        draft = store.create_reply_draft(conversation, make_message_id('wxid_test_target', 7, 11),
                                         'draft text', 'context')
        confirmation = store.confirm_reply_draft(draft)
        arguments = {'confirmation_id': confirmation, 'conversation_id': conversation,
                     'contact': 'wxid_test_other', 'text': 'draft text'}
        try:
            _call(server, 'reply.send_confirmed', arguments)
        except Exception as exc:
            assert isinstance(exc.__cause__, PermissionError)
        basic.execute.assert_not_called()
        assert store._connection.execute(
            'SELECT status FROM reply_drafts WHERE draft_id=?', (draft,)
        ).fetchone()[0] == 'confirmed'
        arguments['contact'] = 'wxid_test_target'
        result = _call(server, 'reply.send_confirmed', arguments)
        assert result['result']['sent'] is False
        assert store._connection.execute(
            'SELECT status FROM reply_drafts WHERE draft_id=?', (draft,)
        ).fetchone()[0] == 'unknown'
        assert basic.execute.call_count == 1
        try:
            _call(server, 'reply.send_confirmed', arguments)
        except Exception as exc:
            assert isinstance(exc.__cause__, PermissionError)
        assert basic.execute.call_count == 1
    finally:
        store.close()


@pytest.mark.parametrize("latest", [[], [{"local_id": 8, "sort_seq": 12}]])
def test_confirmed_reply_stops_before_ui_when_live_trigger_is_missing_or_changed(tmp_path, latest):
    basic = MagicMock()
    backend = MagicMock()
    backend.get_context.return_value = latest
    target = "wxid_test_friend"
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"), memory_root=str(tmp_path / "memory"),
                           basic_skill=basic, conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        conversation = _active_direct_conversation(store, target)
        draft = store.create_reply_draft(conversation, make_message_id(target, 7, 11), "draft", "context")
        with pytest.raises(Exception) as rejected_confirmation:
            _call(server, "reply.confirm", {"draft_id": draft})
        assert isinstance(rejected_confirmation.value.__cause__, PermissionError)
        assert store._connection.execute("SELECT confirmation_id FROM reply_drafts WHERE draft_id=?",
                                         (draft,)).fetchone()[0] is None
        confirmation = store.confirm_reply_draft(draft)
        with pytest.raises(Exception) as failure:
            _call(server, "reply.send_confirmed", {"confirmation_id": confirmation, "conversation_id": conversation,
                                                   "contact": target, "text": "draft"})
        assert isinstance(failure.value.__cause__, PermissionError)
        basic.execute.assert_not_called()
        assert store._connection.execute("SELECT status FROM reply_drafts WHERE draft_id=?",
                                         (draft,)).fetchone()[0] == "confirmed"
    finally:
        store.close()


def test_reply_draft_rejects_memory_version_change_before_confirm_or_send(tmp_path):
    basic = MagicMock()
    backend = MagicMock()
    backend.get_context.return_value = [{"local_id": 7, "sort_seq": 11}]
    target = "wxid_test_friend"
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"), memory_root=str(tmp_path / "memory"),
                           basic_skill=basic, conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        conversation = _active_direct_conversation(store, target)
        context_args = {"conversation_id": conversation, "current_messages": []}
        fingerprint = _call(server, "reply.build_context", context_args)["memory_version_fingerprint"]
        draft_args = {"conversation_id": conversation, "trigger_evidence_id": make_message_id(target, 7, 11),
                      "text": "synthetic draft", "context_fingerprint": "fixture",
                      "expected_memory_version_fingerprint": fingerprint}
        pending = _call(server, "reply.create_draft", draft_args)["draft_id"]
        confirmed = _call(server, "reply.create_draft", draft_args)["draft_id"]
        token = _call(server, "reply.confirm", {"draft_id": confirmed})["confirmation_id"]
        _call(server, "analysis.submit", {"scope_type": "conversation", "scope_id": conversation,
                                         "markdown_text": "# Updated Memory", "evidence_ids": [],
                                         "template_version": "synthetic"})
        with pytest.raises(Exception) as failure:
            _call(server, "reply.create_draft", draft_args)
        assert isinstance(failure.value.__cause__, PermissionError)
        assert store._connection.execute("SELECT count(*) FROM reply_drafts").fetchone()[0] == 2
        refreshed = _call(server, "reply.build_context", context_args)["memory_version_fingerprint"]
        assert refreshed != fingerprint
        assert _call(server, "reply.create_draft", {
            **draft_args, "expected_memory_version_fingerprint": refreshed,
        })["draft_id"]
        for name, args in [
            ("reply.confirm", {"draft_id": pending}),
            ("reply.send_confirmed", {"confirmation_id": token, "conversation_id": conversation,
                                      "contact": target, "text": draft_args["text"]}),
        ]:
            with pytest.raises(Exception) as failure:
                _call(server, name, args)
            assert isinstance(failure.value.__cause__, PermissionError)
            assert "Reply Memory changed" in str(failure.value.__cause__)
        basic.execute.assert_not_called()
    finally:
        store.close()


def test_confirmed_reply_rechecks_new_messages_during_preparation(tmp_path):
    basic = MagicMock()
    basic.execute.side_effect = lambda **kwargs: kwargs["before_dispatch"]()
    backend = MagicMock()
    backend.get_context.side_effect = [[{"local_id": 7, "sort_seq": 11}], [{"local_id": 8, "sort_seq": 12}]]
    target = "wxid_test_friend"
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"), memory_root=str(tmp_path / "memory"),
                           basic_skill=basic, conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        conversation = _active_direct_conversation(store, target)
        draft = store.create_reply_draft(conversation, make_message_id(target, 7, 11), "draft", "context")
        confirmation = store.confirm_reply_draft(draft)
        with pytest.raises(Exception) as failure:
            _call(server, "reply.send_confirmed", {"confirmation_id": confirmation, "conversation_id": conversation,
                                                   "contact": target, "text": "draft"})
        assert "Conversation changed during preparation" in str(failure.value.__cause__)
        assert backend.get_context.call_count == 2
        assert store._connection.execute("SELECT status FROM reply_drafts WHERE draft_id=?",
                                         (draft,)).fetchone()[0] == "failed"
    finally:
        store.close()


@pytest.mark.parametrize("linked", [False, True])
def test_confirmed_reply_rejects_missing_or_unknown_contact_state(tmp_path, linked):
    basic = MagicMock()
    backend = MagicMock()
    target = "wxid_test_friend"
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"), memory_root=str(tmp_path / "memory"),
                           basic_skill=basic, conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        conversation = store.ensure_conversation(target, conversation_type="direct")
        if linked:
            store.link_conversation_person(conversation, store.ensure_person(target, mark_active=False), role="other")
        draft = store.create_reply_draft(conversation, make_message_id(target, 7, 11), "draft", "context")
        token = store.confirm_reply_draft(draft)
        with pytest.raises(Exception) as failure:
            _call(server, "reply.send_confirmed", {"confirmation_id": token, "conversation_id": conversation,
                                                   "contact": target, "text": "draft"})
        assert isinstance(failure.value.__cause__, PermissionError)
        backend.get_context.assert_not_called()
        basic.execute.assert_not_called()
        assert store._connection.execute("SELECT status FROM reply_drafts WHERE draft_id=?",
                                         (draft,)).fetchone()[0] == "confirmed"
    finally:
        store.close()


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


def test_scope_status_compares_live_head_without_mutating_archive(tmp_path):
    target = "wxid_test_friend"
    archive_path = tmp_path / "history.sqlite3"
    backend = MagicMock()
    backend.get_context.return_value = [{"local_id": 7, "sort_seq": 11, "create_time": "2026-09-01",
                                         "content": "synthetic text"}]
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"), memory_root=str(tmp_path / "memory"),
                           history_db=str(archive_path), conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        conversation = store.ensure_conversation(target, conversation_type="direct")
        args = {"scope_type": "conversation", "scope_id": conversation, "check_live_head": True}
        with HistoryStore(archive_path) as archive:
            assert _call(server, "analysis.scope_status", args)["live_head_archive_comparison"] == "missing"
            archive.save_messages([{"id": "older-source-id", "chat": target, "content": "synthetic text",
                                    "time": "2026-09-01", "raw": {"sort_seq": 11}}])
            status = _call(server, "analysis.scope_status", args)
            assert status["live_head_archive_comparison"] == "fingerprint_matches"
            assert status["source_freshness"] == "unknown"
            assert _call(server, "analysis.scope_status", {**args, "period": "2026-10"})[
                "live_head_archive_comparison"] == "outside_period"
            backend.get_context.return_value = []
            assert _call(server, "analysis.scope_status", args)["live_head_archive_comparison"] == "unknown"
            assert len(archive.fetch_messages(target)) == 1
    finally:
        store.close()


def test_context_failure_does_not_advance_monitor_cursor(tmp_path):
    backend = _ConversationBackend()
    server = create_server(memory_db=str(tmp_path / 'memory.sqlite3'),
                           memory_root=str(tmp_path / 'memory'), conversation_backend=backend)
    try:
        with (
            patch('wechat_auto.memory.context.ContextBuilder.reply_context', side_effect=RuntimeError('simulated')),
            pytest.raises(Exception) as failure,
        ):
            _call(server, 'monitor.run_once', {'username': 'wxid_test_friend'})
        assert isinstance(failure.value.__cause__, RuntimeError)
        assert server._wechat_auto_store.get_sync_cursor('reply_monitor', 'wxid_test_friend') == ''
        assert server._wechat_auto_store.next_jobs() == []
        captured = {}

        def context(conversation_id, messages):
            captured['messages'] = messages
            return {'message_count': len(messages)}

        with patch('wechat_auto.memory.context.ContextBuilder.reply_context', side_effect=context):
            result = _call(server, 'monitor.run_once', {'username': 'wxid_test_friend'})
        assert len(result['new_messages']) == 1
        assert backend.since_sequences == [0, 0]
        assert captured['messages'][0]['id'] == 'wxid_test_friend::11::'
        assert server._wechat_auto_store.get_sync_cursor('reply_monitor', 'wxid_test_friend') == '11'
    finally:
        server._wechat_auto_store.close()


def test_monitor_keeps_followup_batch_and_ignores_replayed_delta(tmp_path):
    username = "wxid_test_friend"
    backend = _ConversationBackend()
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"),
                           memory_root=str(tmp_path / "memory"), conversation_backend=backend)
    store = server._wechat_auto_store
    try:
        _call(server, "monitor.run_once", {"username": username})
        running = store.claim_next_job()
        items = [{"local_id": seq, "sort_seq": seq, "create_time": 1788192000} for seq in (12, 13)]
        update = {"messages": items, "all_messages": items, "watermark": 13}
        with patch.object(backend, "poll", return_value=update):
            assert len(_call(server, "monitor.run_once", {"username": username})["new_messages"]) == 2
            assert _call(server, "monitor.run_once", {"username": username})["new_messages"] == []
        pending, = store.next_jobs()
        assert pending["job_id"] != running["job_id"]
        assert store.claim_next_job() is None
        store.complete_job(running["job_id"], success=True)
        assert store.claim_next_job()["job_id"] == pending["job_id"]
        assert store.get_sync_cursor("reply_monitor", username) == "13"
    finally:
        store.close()


@pytest.mark.parametrize("index_first", [True, False])
def test_monitor_and_archive_index_share_message_registration(tmp_path, index_first):
    username = "wxid_test_friend"
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"), memory_root=str(tmp_path / "memory"),
                           conversation_backend=_ConversationBackend())
    store = server._wechat_auto_store
    try:
        indexer = ArchiveIndexer(store)
        path = tmp_path / "history.sqlite3"
        with HistoryStore(path) as history:
            history.save_messages([{"id": "baseline", "chat": username, "time": "2026-08-01"}])
            indexer.index_history(path)
            message_id = make_message_id(username, 7, 11, "server-7")
            history.save_messages([{"id": message_id, "chat": username, "time": "2026-09-01"}])
            if index_first:
                indexer.index_history(path)
            _call(server, "monitor.run_once", {"username": username})
            if not index_first:
                indexer.index_history(path)
        job, = store.next_jobs()
        assert job["period"] == "2026-09"
    finally:
        store.close()


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
                  'conversation_id': conversation, 'contact': 'wxid_test_test', 'text': 'draft text'})
        except Exception as exc:
            # MCP SDK masks unexpected exception text at the transport boundary.
            assert isinstance(exc.__cause__, PermissionError)
            assert 'blocks dispatch' in str(exc.__cause__)
        basic.execute.assert_not_called()
        row = store._connection.execute('SELECT status FROM reply_drafts WHERE draft_id=?', (draft,)).fetchone()
        assert row[0] == 'confirmed'
    finally:
        store.close()
