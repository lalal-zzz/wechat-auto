"""Evidence expansion must be explicit and conversation scoped."""

import pytest

from wechat_auto.memory.evidence import EvidenceResolver
from wechat_auto.storage import HistoryStore, MomentStore, ProfileStore


@pytest.fixture
def archives(tmp_path):
    history = tmp_path / 'history.sqlite3'
    moments = tmp_path / 'moments.sqlite3'
    profiles = tmp_path / 'profiles.sqlite3'
    with HistoryStore(history) as store:
        store.save_messages([
            {'id': 'm1', 'chat': 'wxid_test_one', 'content': 'before', 'time': '2026-09-01 10:00:00'},
            {'id': 'other', 'chat': 'wxid_test_two', 'content': 'other chat', 'time': '2026-09-01 10:00:01'},
            {'id': 'm2', 'chat': 'wxid_test_one', 'content': 'target', 'time': '2026-09-01 10:00:02'},
            {'id': 'm3', 'chat': 'wxid_test_one', 'content': 'after', 'time': '2026-09-01 10:00:03'},
        ])
    with MomentStore(moments) as store:
        store.save([{'id': 'moment1', 'username': 'wxid_test_one', 'text': 'moment body'}])
    with ProfileStore(profiles) as store:
        snapshot = store.save({'wechat_id': 'wxid_test_one', 'signature': 'profile body'},
                              profile_type='contact')['snapshot_id']
    return EvidenceResolver(history_path=history, moments_path=moments, profiles_path=profiles), snapshot


def test_content_expansion_is_opt_in_for_each_source(archives):
    resolver, snapshot = archives
    for kind, key, body in [('message', 'm2', 'target'), ('moment', 'moment1', 'moment body'),
                            ('profile_snapshot', str(snapshot), 'profile body')]:
        compact = resolver.get(kind, key)
        assert compact is not None
        assert body not in repr(compact)
        expanded = resolver.get(kind, key, include_content=True)
        assert body in repr(expanded)
        assert resolver.get(kind, 'missing') is None


def test_message_context_never_includes_other_conversation(archives):
    resolver, _ = archives
    result = resolver.context('message', 'm2', before=1, after=1)
    assert [item['id'] for item in result] == ['m1', 'm2', 'm3']
    assert resolver.context('message', 'missing') == []
    assert resolver.context('moment', 'moment1') == []


def test_missing_source_does_not_create_a_database(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    resolver = EvidenceResolver(history_path=path, moments_path=path, profiles_path=path)
    for kind in ('message', 'moment', 'profile_snapshot', 'unknown'):
        assert resolver.get(kind, 'missing') is None
    assert resolver.context('message', 'missing') == []
    assert not path.exists()
