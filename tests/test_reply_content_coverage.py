import sqlite3

import pytest

from tests.test_reply_memory_context import setup_context


@pytest.mark.parametrize('content', ['<msg><emoji aeskey="private-key" cdnurl="private-url" /></msg>',
                                   '<msg>broken'])
def test_reply_xml_is_not_raw_transport_text(tmp_path, content):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'id': 'fixture', 'chat': 'friend', 'content': content}])
        assert 'private-key' not in result['text'] and '<msg>' not in result['text']
        assert result['requires_content_review'] and result['requires_more_data']
        assert result['content_gaps'][0]['message_id'] == 'fixture'
    finally:
        store.close()


@pytest.mark.parametrize('message', [
    {'content': '[语音]', 'transcription': None},
    {'content': '', 'raw': {'type': 34}},
    {'content': '', 'transcription': {'text': 'failed words', 'status': 'failed'}},
])
def test_missing_voice_or_failed_record_is_a_content_gap(tmp_path, message):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'chat': 'friend', **message}])
        assert result['requires_content_review'] and result['requires_more_data']
        assert result['content_gaps']
    finally:
        store.close()


def test_plain_text_does_not_require_transcription(tmp_path):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'chat': 'friend', 'content': 'a < b, meet tomorrow', 'transcription': None}])
        assert 'a < b, meet tomorrow' in result['text']
        assert not result['requires_content_review'] and not result['requires_more_data']
    finally:
        store.close()


def test_embedded_voice_is_labelled_in_reply(tmp_path):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'chat': 'friend', 'content': '<msg><voicetrans>candidate</voicetrans></msg>'}])
        assert 'XML内嵌候选' in result['text'] and '未经复核' in result['text']
        assert '<voicetrans>' not in result['text']
    finally:
        store.close()


def test_pending_archive_content_gap_has_separate_scope(tmp_path):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        with sqlite3.connect(builder.history_path) as db:
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',
                       ('broken-xml', 'friend', 'A', '<msg>broken', '2026-09-15T10:00:00+08:00', 'in'))
        result = builder.reply_context(cv, [])
        assert result['pending_coverage']['remaining_count'] == 0
        assert result['requires_content_review'] and result['requires_more_data']
        assert any(g['source'] == 'pending' and g['message_id'] == 'broken-xml' for g in result['content_gaps'])
    finally:
        store.close()


def test_machine_candidate_remains_readable_without_false_missing_data(tmp_path):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'chat': 'friend', 'content': '[语音]',
            'transcription': {'engine': 'local_asr', 'status': 'transcribed_unreviewed', 'text': 'candidate'}}])
        assert '未经复核' in result['text'] and 'candidate' in result['text']
        assert not result['requires_content_review'] and not result['requires_more_data']
    finally:
        store.close()
