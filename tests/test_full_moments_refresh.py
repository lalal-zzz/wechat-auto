import json
from unittest.mock import MagicMock

import pytest

from wechat_auto.memory import MemoryStore
from wechat_auto.storage import MomentStore, ProfileStore


def test_full_refresh_scopes_current_contacts_preserves_history_and_is_idempotent(tmp_path, monkeypatch):
    from wechat_auto.backends import collection_sync as module
    profile_backend = MagicMock()
    profile_backend.get_all_contact_profiles.return_value = [
        {'wechat_id': 'wxid_test_one', 'nickname': 'one', 'raw': {}},
        {'wechat_id': 'wxid_test_two', 'nickname': 'two', 'raw': {}},
    ]
    moments_backend = MagicMock()
    moments_backend.read_all_available.return_value = [
        {'id': 'post1', 'username': 'wxid_test_one', 'create_time': 1,
         'images': [{'url': 'https://example.invalid/image'}], 'videos': []},
        {'id': 'stranger_post', 'username': 'unknown_author', 'create_time': 2,
         'images': [], 'videos': []},
    ]
    monkeypatch.setattr(module, 'DatabaseProfileBackend', lambda db: profile_backend)
    monkeypatch.setattr(module, 'DatabaseMomentsBackend', lambda db: moments_backend)
    profiles_path = tmp_path / 'profiles.sqlite3'
    moments_path = tmp_path / 'moments.sqlite3'
    memory_path = tmp_path / 'memory.sqlite3'
    with ProfileStore(profiles_path) as store:
        store.save({'wechat_id': 'wxid_test_old', 'nickname': 'old', 'raw': {}}, profile_type='contact')
        store.save({'wechat_id': 'wxid_test_one', 'nickname': 'one', 'raw': {}}, profile_type='contact')
        store.record_ui_observation('wxid_test_one', {'signature': 'visible signature'}, evidence_ref='profile.png')
    with MomentStore(moments_path) as store:
        store.save([{'id': 'old_post', 'username': 'wxid_test_old', 'create_time': 1}])
    with MemoryStore(memory_path) as store:
        person = store.ensure_person('wxid_test_old')
        store._connection.execute("UPDATE people SET status='confirmed_removed' WHERE person_id=?", (person,))
        store._connection.commit()
    kwargs = {'profiles_path': profiles_path, 'moments_path': moments_path,
              'memory_path': memory_path, 'output': tmp_path / 'runs'}
    first = module.refresh(None, **kwargs)
    second = module.refresh(None, **kwargs)
    assert first['contact_rows'] == 2
    assert first['contact_moments'] == 1
    assert first['images'] == 1 and first['pending_media'] == 1
    assert second['profiles_changed'] == second['moments_changed'] == 0
    assert second['profile_snapshots_indexed'] == second['new_moments_indexed'] == 0
    assert first['network_requests'] == second['media_downloaded'] == 0
    assert first['presence_audit_applied'] is False
    profile_backend.get_all_contact_profiles.assert_called_with(direct_contacts_only=False)
    moments_backend.download_media.assert_not_called()
    with MomentStore(moments_path) as store:
        assert store.get('old_post') is not None
        assert store.get('stranger_post') is None
    with ProfileStore(profiles_path) as store:
        assert store.get('wxid_test_old') is not None
        assert store.get('wxid_test_one')['signature'] == 'visible signature'
    with MemoryStore(memory_path) as store:
        statuses = store._connection.execute('SELECT status FROM people').fetchall()
        assert 'confirmed_removed' in {row[0] for row in statuses}
    manifests = [json.loads((tmp_path / 'runs' / r['run_id'] / 'media_manifest.jsonl').read_text())
                 for r in (first, second)]
    assert manifests[0]['item_id'] == manifests[1]['item_id']
    assert 'https://' not in json.dumps(first)


@pytest.mark.parametrize('failure', ['author_collision', 'invalid_media'])
def test_refresh_bad_later_feed_does_not_commit_earlier_moment(tmp_path, monkeypatch, failure):
    from wechat_auto.backends import collection_sync as module
    profiles = MagicMock()
    profiles.get_all_contact_profiles.return_value = [{'wechat_id': 'u', 'nickname': 'fixture', 'raw': {}}]
    moments = MagicMock()
    bad = {'id': 'existing', 'username': 'u', 'create_time': 1}
    if failure == 'invalid_media':
        bad = {'id': 'bad-media', 'username': 'u', 'create_time': 3, 'images': ['not-a-media-record']}
    moments.read_all_available.return_value = [{'id': 'new', 'username': 'u', 'create_time': 2}, bad]
    monkeypatch.setattr(module, 'DatabaseProfileBackend', lambda db: profiles)
    monkeypatch.setattr(module, 'DatabaseMomentsBackend', lambda db: moments)
    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as store:
        store.save([{'id': 'existing', 'username': 'different-author', 'create_time': 1}])
    with pytest.raises((ValueError, TypeError)):
        module.refresh(None, profiles_path=tmp_path / 'profiles.sqlite3', moments_path=path,
                       memory_path=tmp_path / 'memory.sqlite3', output=tmp_path / 'runs')
    with MomentStore(path) as store:
        assert store.get('new') is None
        assert store.get('bad-media') is None
        assert store.get('existing')['username'] == 'different-author'
    assert not list((tmp_path / 'runs').glob('*/summary.json'))
    moments.download_media.assert_not_called()
    moments.read_all_available.return_value = [
        {'id': 'new', 'username': 'u', 'create_time': 2},
        {'id': 'recovered', 'username': 'u', 'create_time': 3, 'images': []}]
    kwargs = {'profiles_path': tmp_path / 'profiles.sqlite3', 'moments_path': path,
              'memory_path': tmp_path / 'memory.sqlite3', 'output': tmp_path / 'runs'}
    recovered = module.refresh(None, **kwargs)
    assert recovered['moments_changed'] == 2 and recovered['failures'] == 0
    repeated = module.refresh(None, **kwargs)
    assert repeated['moments_changed'] == repeated['new_moments_indexed'] == 0
    with MomentStore(path) as store:
        assert store.get('new') is not None and store.get('recovered') is not None
        assert store.get('existing')['username'] == 'different-author'
