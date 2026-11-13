import sqlite3

import pytest

from tests.test_reply_memory_context import setup_context


@pytest.mark.parametrize('field,value', [('version', 2), ('source_ref', 'new-source'),
                                       ('audio_sha256', 'different-audio'), ('segments', [{'start': 1, 'end': 2}])])
def test_current_same_text_new_transcription_version_changes_fingerprint(tmp_path, field, value):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        message = {'chat': 'friend', 'id': 'voice', 'transcription': {
            'text': 'same words', 'engine': 'local_asr', 'status': 'transcribed_unreviewed',
            'version': 1, 'source_ref': 'fixture', 'audio_sha256': 'audio'}}
        first = builder.reply_context(cv, [message])
        message['transcription'][field] = value
        second = builder.reply_context(cv, [message])
        assert first['text'] == second['text']
        assert first['fingerprint'] != second['fingerprint']
    finally:
        store.close()


def test_transcription_dictionary_key_order_does_not_invalidate_context(tmp_path):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        transcript = {'text': 'words', 'engine': 'local_asr', 'status': 'transcribed_unreviewed', 'version': 1}
        first = builder.reply_context(cv, [{'chat': 'friend', 'transcription': transcript}])
        second = builder.reply_context(cv, [{'chat': 'friend', 'transcription': dict(reversed(list(transcript.items())))}])
        assert first['fingerprint'] == second['fingerprint']
    finally:
        store.close()


def test_pending_transcription_preserves_version_and_source(tmp_path):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        with sqlite3.connect(builder.history_path) as db:
            db.execute('CREATE TABLE voice_transcriptions(message_id TEXT,version INTEGER,text TEXT,engine TEXT,status TEXT,source_ref TEXT,audio_sha256 TEXT)')
            db.execute('INSERT INTO voice_transcriptions VALUES(?,?,?,?,?,?,?)',
                       ('new', 1, 'same words', 'local_asr', 'transcribed_unreviewed', 'fixture', 'audio'))
        first = builder.reply_context(cv, [])
        transcript = next(m['transcription'] for m in first['pending_messages'] if m['id'] == 'new')
        assert transcript['version'] == 1 and transcript['source_ref'] == 'fixture'
        with sqlite3.connect(builder.history_path) as db:
            db.execute('UPDATE voice_transcriptions SET version=2,source_ref=?', ('fixture-updated',))
        second = builder.reply_context(cv, [])
        assert first['fingerprint'] != second['fingerprint']
    finally:
        store.close()
