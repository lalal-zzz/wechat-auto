import pytest

from wechat_auto.backends import DatabaseConversationBackend


class _DB:
    def search_contact(self, query):
        return [{"username": "room@chatroom", "nick_name": "群", "remark": ""}]

    def get_messages(self, username, limit):
        return [{"sort_seq": 4, "content": "later"}, {"sort_seq": 2, "content": "earlier"}]

    def get_new_messages(self, username, since, limit):
        return [
            {"sort_seq": 3, "sender_id": 2, "content": "self"},
            {"sort_seq": 4, "sender_id": 7, "content": "inbound"},
        ]


def test_poll_preserves_watermark_and_filters_self_messages():
    backend = DatabaseConversationBackend(_DB())
    result = backend.poll("room@chatroom", 2)
    assert result["watermark"] == 4
    assert [m["content"] for m in result["messages"]] == ["inbound"]


def test_drafts_are_not_sent_without_explicit_confirmation():
    backend = DatabaseConversationBackend(_DB())
    result = backend.build_reply_drafts("room@chatroom", 2, lambda msg, ctx: "draft")
    assert result["drafts"][0]["draft"] == "draft"
    with pytest.raises(PermissionError):
        backend.dispatch_draft("draft", lambda text: text)
    assert backend.dispatch_draft("draft", lambda text: text, confirm=True) == "draft"


def test_sync_when_notified_uses_persisted_cursor(tmp_path):
    backend = DatabaseConversationBackend(_DB())
    result = backend.sync_when_notified("room@chatroom", str(tmp_path / "history.sqlite3"))
    assert result["watermark"] == 4
    assert result["rows_added"] == 2


def test_initial_import_is_bounded_and_sets_cursor(tmp_path):
    backend = DatabaseConversationBackend(_DB())
    result = backend.initial_import("room@chatroom", str(tmp_path / "history.sqlite3"), batch_size=10)
    assert result["messages_read"] == 2
    assert result["complete"] is True
