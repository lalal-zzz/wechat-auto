"""Exercise complete import with a synthetic adapter export and local media failures."""

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.backends import DatabaseConversationBackend
from wechat_auto.storage import HistoryStore


class ExportDB:
    def export_history(self, path, fmt):
        assert fmt == 'sqlite'
        self.exported = Path(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE chats(username TEXT,name TEXT,message_count INTEGER)')
            db.execute("INSERT INTO chats VALUES('wxid_test_one','synthetic',2)")
            db.execute('CREATE TABLE messages(username TEXT,local_id INTEGER,type INTEGER,'
                       'sender_id INTEGER,sender_name TEXT,create_time INTEGER,content TEXT,sort_seq INTEGER)')
            db.executemany('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)', [
                ('wxid_test_one', 1, 1, 2, 'self', 1788192000, 'text', 10),
                ('wxid_test_one', 2, 3, 7, 'peer', 1788192001, 'image', 11),
            ])


@pytest.mark.parametrize('failure', ['exception', 'empty_result'])
def test_archive_all_preserves_text_when_local_media_is_missing(tmp_path, failure):
    source = ExportDB()
    backend = DatabaseConversationBackend(source)
    downloader = MagicMock()
    if failure == 'exception':
        downloader.download_media.side_effect = FileNotFoundError('synthetic missing cache')
    else:
        downloader.download_media.return_value = None
    path = tmp_path / 'history.sqlite3'
    with patch.dict('sys.modules', {'wechatauto': SimpleNamespace(MediaDownloader=lambda *a, **k: downloader)}):
        first = backend.archive_all_history(str(path))
        second = backend.archive_all_history(str(path))
    assert first['messages_read'] == 2 and first['media_errors'] == 1
    assert first['rows_added'] == 2 and second['rows_added'] == 0
    assert not source.exported.exists()
    with HistoryStore(path) as archive:
        assert len(archive.fetch_messages('wxid_test_one')) == 2
        assert archive.get_cursor('wechat_db', 'wxid_test_one') == 11


def test_archive_failure_closes_export_before_removing_temporary_directory(tmp_path):
    source = ExportDB()

    def interrupted(*args):
        raise RuntimeError('synthetic interruption')

    with (
        patch.dict('sys.modules', {'wechatauto': SimpleNamespace(MediaDownloader=MagicMock())}),
        pytest.raises(RuntimeError, match='synthetic interruption'),
    ):
        DatabaseConversationBackend(source).archive_all_history(
            str(tmp_path / 'history.sqlite3'), progress=interrupted)
    assert not source.exported.exists()
