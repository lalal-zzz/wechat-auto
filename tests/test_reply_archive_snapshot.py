import sqlite3
from contextlib import closing

import pytest

from tests.test_reply_memory_context import setup_context


def test_pending_counts_messages_and_transcription_share_read_snapshot(tmp_path, monkeypatch):
    store, _, cv, builder = setup_context(tmp_path)
    connect = sqlite3.connect
    try:
        with closing(connect(builder.history_path)) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE voice_transcriptions(message_id TEXT,version INTEGER,text TEXT,engine TEXT,status TEXT,source_ref TEXT,audio_sha256 TEXT)')
            db.execute('INSERT INTO voice_transcriptions VALUES(?,?,?,?,?,?,?)',
                       ('new', 1, 'before words', 'local_asr', 'transcribed_unreviewed', 'fixture', 'audio'))
        updated = False

        def commit_new_generation():
            nonlocal updated
            if updated:
                return
            updated = True
            with closing(connect(builder.history_path)) as writer, writer:
                writer.execute('UPDATE messages SET content=? WHERE id=?', ('updated body', 'new'))
                writer.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',
                               ('added', 'friend', 'A', 'added body', 'unknown', 'in'))
                writer.execute('INSERT INTO voice_transcriptions VALUES(?,?,?,?,?,?,?)',
                               ('new', 2, 'after words', 'local_asr', 'transcribed_unreviewed', 'fixture', 'audio'))

        class CountCursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def fetchone(self):
                result = self.cursor.fetchone()
                commit_new_generation()
                return result

        class Reader(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                cursor = super().execute(sql, *args, **kwargs)
                if sql.startswith('SELECT count(*) FROM messages WHERE chat=? AND rowid>'):
                    return CountCursor(cursor)
                return cursor

        def intercepted_connect(path, *args, **kwargs):
            if kwargs.get('uri') and str(path).startswith(builder.history_path.as_uri()):
                kwargs['factory'] = Reader
            return connect(path, *args, **kwargs)

        monkeypatch.setattr('wechat_auto.memory.context.sqlite3.connect', intercepted_connect)
        first = builder.reply_context(cv, [])
        assert updated
        assert first['pending_coverage']['count'] == 2
        assert first['pending_coverage']['remaining_count'] == 0
        assert first['pending_coverage']['unknown_time_count'] == 0
        message = next(m for m in first['pending_messages'] if m['id'] == 'new')
        assert message['content'] == 'cancelled plan'
        assert message['transcription']['version'] == 1
        second = builder.reply_context(cv, [])
        assert second['pending_coverage']['count'] == 3
        assert second['pending_coverage']['unknown_time_count'] == 1
        assert next(m for m in second['pending_messages'] if m['id'] == 'new')['transcription']['version'] == 2
        assert first['fingerprint'] != second['fingerprint']
    finally:
        store.close()


@pytest.mark.parametrize('journal', ['DELETE', 'WAL'])
def test_failed_snapshot_read_closes_transaction_and_releases_locks(tmp_path, monkeypatch, journal):
    store, _, cv, builder = setup_context(tmp_path)
    connect = sqlite3.connect
    readers = []
    try:
        with closing(connect(builder.history_path)) as db:
            db.execute('PRAGMA journal_mode=' + journal)

        def tracked_connect(path, *args, **kwargs):
            db = connect(path, *args, **kwargs)
            if kwargs.get('uri') and str(path).startswith(builder.history_path.as_uri()):
                readers.append(db)
            return db

        monkeypatch.setattr('wechat_auto.memory.context.sqlite3.connect', tracked_connect)
        with pytest.raises(ValueError, match='cursor'):
            builder.reply_context(cv, [], pending_after_id='other')
        assert readers
        for reader in readers:
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                reader.execute('SELECT 1')
        with closing(connect(builder.history_path, timeout=0)) as writer, writer:
            writer.execute('UPDATE messages SET content=? WHERE id=?', ('after failure', 'new'))
    finally:
        store.close()
