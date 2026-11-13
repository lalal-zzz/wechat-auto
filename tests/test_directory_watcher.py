"""Verify real Windows notifications using project-independent temporary files."""

import sys
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from scripts import monitor_until_new_message as monitor
from wechat_auto.backends.watcher import WindowsDirectoryWatcher


def test_real_directory_event_rearms_and_closes(tmp_path):
    watcher = WindowsDirectoryWatcher(tmp_path)
    try:
        watcher.start()
        handle = watcher._handle
        watcher.start()
        assert watcher._handle is handle
        assert watcher.wait(timeout_ms=0) is False
        (tmp_path / "first.txt").write_text("first", encoding="utf-8")
        assert watcher.wait(timeout_ms=3000) is True
        (tmp_path / "second.txt").write_text("second", encoding="utf-8")
        assert watcher.wait(timeout_ms=3000) is True
    finally:
        watcher.close()
        watcher.close()
    assert watcher._handle is None


def test_wait_failure_is_not_reported_as_timeout(tmp_path):
    watcher = WindowsDirectoryWatcher(tmp_path)
    watcher.start()
    try:
        with patch("win32event.WaitForSingleObject", return_value=0xFFFFFFFF), pytest.raises(OSError):
            watcher.wait(timeout_ms=0)
    finally:
        watcher.close()


def test_monitor_drains_a_full_outgoing_batch_after_one_event(tmp_path, monkeypatch):
    database = MagicMock()
    database._db_files = [("fixture", str(tmp_path / "message" / "message_0.db"), 0)]
    database.get_messages.return_value = [{"sort_seq": 1}]
    watcher = MagicMock()
    watcher.wait.side_effect = [False, True]
    backend = MagicMock()
    backend.resolve_chat.return_value = {"username": "wxid_test_monitor"}
    backend.sync_when_notified.side_effect = [
        {"messages_read": 100, "watermark": 101, "new_inbound": 0, "rows_added": 100},
        {"messages_read": 1, "watermark": 102, "new_inbound": 1, "rows_added": 1},
    ]
    order = MagicMock()
    for name, method in (("start", watcher.start), ("baseline", database.get_messages),
                         ("wait", watcher.wait), ("sync", backend.sync_when_notified)):
        order.attach_mock(method, name)
    monkeypatch.setattr(sys, "argv", ["monitor", "wxid_test_monitor", "--store", str(tmp_path / "archive.sqlite3")])
    monkeypatch.setattr(monitor, "open_dpapi_wechat_db", lambda *args, **kwargs: nullcontext(database))
    monkeypatch.setattr(monitor, "DatabaseConversationBackend", lambda _database: backend)
    monkeypatch.setattr(monitor, "WindowsDirectoryWatcher", lambda *args, **kwargs: watcher)
    monkeypatch.setattr(monitor.time, "sleep", lambda _seconds: None)

    monitor.main()

    assert [call[0] for call in order.mock_calls] == ["start", "baseline", "wait", "wait", "sync", "sync"]
    watcher.close.assert_called_once_with()
