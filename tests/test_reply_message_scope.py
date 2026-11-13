import sqlite3
from datetime import datetime

import pytest

from tests.test_reply_memory_context import setup_context


@pytest.mark.parametrize('field', ['chat', 'source_chat_id', 'conversation_id'])
def test_explicit_foreign_current_message_is_rejected(tmp_path, field):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        with pytest.raises(ValueError, match='scope'):
            builder.reply_context(cv, [{field: 'different-conversation', 'content': 'foreign-body'}])
    finally:
        store.close()


def test_malformed_current_message_is_rejected_before_rendering(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        with pytest.raises(TypeError, match='message'):
            builder.reply_context(cv, [None])
    finally:
        store.close()


def test_millisecond_messages_are_filtered_by_analysis_boundary(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        old = int(datetime.fromisoformat('2026-09-11T10:00:00+08:00').timestamp()*1000)
        new = int(datetime.fromisoformat('2026-09-14T10:00:00+08:00').timestamp()*1000)
        with sqlite3.connect(builder.history_path) as history:
            history.executemany('INSERT INTO messages VALUES(?,?,?,?,?,?)', [
                ('old-ms', 'friend', 'A', 'old-ms-body', str(old), 'in'),
                ('new-ms', 'friend', 'A', 'new-ms-body', str(new), 'in')])
        result = builder.reply_context(cv, [])
        ids = {item['id'] for item in result['pending_messages']}
        assert 'old-ms' not in ids and 'new-ms' in ids
    finally:
        store.close()


def test_unknown_message_time_is_not_a_complete_temporal_range(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        with sqlite3.connect(builder.history_path) as history:
            history.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', ('unknown-time', 'friend', 'A', 'unknown-time-body', 'unparseable', 'in'))
        result = builder.reply_context(cv, [])
        assert result['requires_more_data'] and result['requires_time_review']
        assert result['pending_coverage']['unknown_time_count'] == 1
        assert any(item['id'] == 'unknown-time' for item in result['pending_messages'])
    finally:
        store.close()


def test_matching_declared_message_scope_is_reported_without_claiming_current_account(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'chat': 'friend', 'conversation_id': cv, 'content': 'current'}])
        assert result['current_message_scope']['status'] == 'declared_conversation_match'
        assert not result['requires_message_scope_review']
        assert not result['identity_scope']['current_account_verified']
        assert not result['requires_more_data']
    finally:
        store.close()


def test_unscoped_input_is_preserved_but_requires_review(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'content': 'unscoped-current'}])
        assert 'unscoped-current' in result['text']
        assert '未定范围消息' in result['text']
        assert '当前消息（优先依据）' not in result['text']
        assert result['requires_message_scope_review'] and result['requires_more_data']
        scoped = builder.reply_context(cv, [{'chat': 'friend', 'content': 'unscoped-current'}])
        assert result['fingerprint'] != scoped['fingerprint']
    finally:
        store.close()


def test_unknown_time_review_remains_after_pagination_finishes(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        with sqlite3.connect(builder.history_path) as history:
            history.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', ('unknown-time', 'friend', 'A', 'unknown-time-body', 'unparseable', 'in'))
        page = builder.reply_context(cv, [], pending_limit=1)
        while page['pending_coverage']['remaining_count']:
            page = builder.reply_context(cv, [], pending_limit=1, pending_after_id=page['pending_coverage']['next_after_id'])
        assert page['pending_coverage']['unknown_time_count'] == 1
        assert page['requires_time_review'] and page['requires_more_data']
        assert page['pending_coverage']['next_after_id'] == ''
    finally:
        store.close()
