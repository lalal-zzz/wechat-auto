import asyncio
import json

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
            "application": __version__, "memory_schema": 2,
            "mcp_protocol": MCP_PROTOCOL_VERSION,
            "contact_action_protocol": CONTACT_ACTION_PROTOCOL_VERSION,
        }
    finally:
        server._wechat_auto_store.close()
