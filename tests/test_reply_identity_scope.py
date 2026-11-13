import pytest

from tests.test_reply_memory_context import setup_context
from wechat_auto.memory.context import ContextBuilder


def test_multiple_unbound_self_accounts_are_explicitly_incomplete(tmp_path):
    store, markdown, cv, builder = setup_context(tmp_path)
    try:
        other = store.ensure_person('other-account', person_type='self')
        markdown.write('person', other, '# OTHER-ACCOUNT BACKGROUND', input_fingerprint='other')
        result = builder.reply_context(cv, [])
        assert result['requires_more_data'] and result['requires_identity_review']
        assert result['identity_scope']['self_status'] == 'ambiguous'
        assert 'OTHER-ACCOUNT BACKGROUND' not in result['text']
    finally:
        store.close()


def test_inactive_self_account_is_not_silently_treated_as_ready(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        store._connection.execute("UPDATE people SET status='unknown' WHERE person_type='self'")
        store._connection.commit()
        result = builder.reply_context(cv, [])
        assert result['requires_more_data'] and result['requires_identity_review']
        assert result['identity_scope']['self_status'] == 'missing_active_self'
    finally:
        store.close()


def test_wrong_linked_peer_memory_cannot_enter_direct_chat_context(tmp_path):
    store, markdown, cv, builder = setup_context(tmp_path)
    try:
        wrong = store.ensure_person('different-peer')
        markdown.write('person', wrong, '# FOREIGN PEER BACKGROUND', input_fingerprint='wrong')
        store._connection.execute('DELETE FROM conversation_members WHERE conversation_id=?', (cv,))
        store._connection.commit()
        store.link_conversation_person(cv, wrong)
        result = builder.reply_context(cv, [])
        assert 'FOREIGN PEER BACKGROUND' not in result['text']
        assert result['requires_identity_review']
    finally:
        store.close()


def test_member_validation_is_not_disabled_without_markdown(tmp_path):
    store, _markdown, cv, _builder = setup_context(tmp_path)
    try:
        outsider = store.ensure_person('outsider')
        with pytest.raises(ValueError, match='active member'):
            ContextBuilder(store).reply_context(cv, [], person_id=outsider)
    finally:
        store.close()


def test_linked_self_account_wins_over_unrelated_global_self(tmp_path):
    store, markdown, cv, builder = setup_context(tmp_path)
    try:
        current = store._connection.execute("SELECT person_id FROM people WHERE person_type='self'").fetchone()[0]
        store.link_conversation_person(cv, current, role='self')
        other = store.ensure_person('other-account', person_type='self')
        markdown.write('person', other, '# OTHER-ACCOUNT BACKGROUND', input_fingerprint='other')
        result = builder.reply_context(cv, [])
        assert result['identity_scope']['self_status'] == 'conversation_linked_self'
        assert result['identity_scope']['self_person_id'] == current
        assert not result['identity_scope']['current_account_verified']
        assert 'OTHER-ACCOUNT BACKGROUND' not in result['text']
        assert not result['requires_more_data']
    finally:
        store.close()


def test_inactive_linked_self_does_not_fall_back_to_other_active_account(tmp_path):
    store, markdown, cv, builder = setup_context(tmp_path)
    try:
        current = store._connection.execute("SELECT person_id FROM people WHERE person_type='self'").fetchone()[0]
        store.link_conversation_person(cv, current, role='self')
        store._connection.execute("UPDATE people SET status='unknown' WHERE person_id=?", (current,))
        store._connection.commit()
        other = store.ensure_person('other-account', person_type='self')
        markdown.write('person', other, '# OTHER-ACCOUNT BACKGROUND', input_fingerprint='other')
        result = builder.reply_context(cv, [])
        assert result['identity_scope']['self_status'] == 'inactive_linked_self'
        assert result['requires_identity_review']
        assert 'OTHER-ACCOUNT BACKGROUND' not in result['text']
    finally:
        store.close()


def test_peer_that_is_another_own_account_is_not_selected_as_current_self(tmp_path):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        current = store._connection.execute("SELECT person_id FROM people WHERE person_type='self'").fetchone()[0]
        store.link_conversation_person(cv, current, role='self')
        peer = store.ensure_person('friend', person_type='self')
        result = builder.reply_context(cv, [])
        assert result['identity_scope']['self_person_id'] == current
        assert result['identity_scope']['peer_person_id'] == peer
        assert not result['requires_identity_review']
    finally:
        store.close()


def test_extra_linked_peer_is_reported_but_its_memory_is_excluded(tmp_path):
    store, markdown, cv, builder = setup_context(tmp_path)
    try:
        extra = store.ensure_person('extra-peer')
        store.link_conversation_person(cv, extra)
        markdown.write('person', extra, '# EXTRA PEER BACKGROUND', input_fingerprint='extra')
        result = builder.reply_context(cv, [])
        assert result['identity_scope']['unexpected_member_count'] == 1
        assert result['requires_identity_review']
        assert 'EXTRA PEER BACKGROUND' not in result['text']
    finally:
        store.close()


def test_account_scope_changes_fingerprint_without_markdown(tmp_path):
    store, _markdown, cv, _builder = setup_context(tmp_path)
    try:
        current = store._connection.execute("SELECT person_id FROM people WHERE person_type='self'").fetchone()[0]
        store.link_conversation_person(cv, current, role='self')
        builder = ContextBuilder(store)
        first = builder.reply_context(cv, [])
        other = store.ensure_person('other-account', person_type='self')
        store._connection.execute('DELETE FROM conversation_members WHERE conversation_id=? AND person_id=?', (cv, current))
        store._connection.commit()
        store.link_conversation_person(cv, other, role='self')
        second = builder.reply_context(cv, [])
        assert first['identity_scope']['self_status'] == second['identity_scope']['self_status'] == 'conversation_linked_self'
        assert first['fingerprint'] != second['fingerprint']
        assert not second['identity_scope']['current_account_verified']
    finally:
        store.close()


@pytest.mark.parametrize('current_active', [True, False])
def test_peer_own_account_is_never_a_global_self_fallback(tmp_path, current_active):
    store, _markdown, cv, builder = setup_context(tmp_path)
    try:
        current = store._connection.execute("SELECT person_id FROM people WHERE person_type='self'").fetchone()[0]
        peer = store.ensure_person('friend', person_type='self')
        if not current_active:
            store._connection.execute("UPDATE people SET status='unknown' WHERE person_id=?", (current,))
            store._connection.commit()
        result = builder.reply_context(cv, [])
        assert result['identity_scope']['peer_person_id'] == peer
        assert result['identity_scope']['self_person_id'] == (current if current_active else None)
        assert result['requires_identity_review'] is (not current_active)
        assert not result['identity_scope']['current_account_verified']
    finally:
        store.close()


def test_unbound_inactive_self_and_other_active_self_are_still_ambiguous(tmp_path):
    store, markdown, cv, builder = setup_context(tmp_path)
    try:
        store._connection.execute("UPDATE people SET status='unknown' WHERE person_type='self'")
        store._connection.commit()
        other = store.ensure_person('other-account', person_type='self')
        markdown.write('person', other, '# UNBOUND OTHER BACKGROUND', input_fingerprint='other')
        result = builder.reply_context(cv, [])
        assert result['identity_scope']['self_status'] == 'ambiguous'
        assert result['requires_identity_review']
        assert 'UNBOUND OTHER BACKGROUND' not in result['text']
    finally:
        store.close()
