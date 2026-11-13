import json
from unittest.mock import patch

import pytest

from wechat_auto.storage import ProfileStore


def profile(group, name, **extra):
    return {'wechat_id': 'wxid_test', 'group_id': group, 'nickname': 'global-name',
            'group_display_name': name, 'is_owner': False, **extra}


def test_two_groups_same_member_remain_independent_across_restart(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as store:
        store.save(profile('a@chatroom', 'A1'), profile_type='group_member')
        store.save(profile('b@chatroom', 'B1'), profile_type='group_member')
        result = store.save(profile('a@chatroom', 'A2'), profile_type='group_member')
        assert result['changed_fields'] == ['group_display_name']
        unchanged = store.save(profile('b@chatroom', 'B1'), profile_type='group_member')
        assert unchanged['changed_fields'] == []
        assert store._connection.execute("SELECT COUNT(*) FROM profiles WHERE profile_type='group_member'").fetchone()[0] == 0
    with ProfileStore(path) as store:
        assert store.get('wxid_test', profile_type='group_member', group_id='a@chatroom')['group_display_name'] == 'A2'
        assert store.get('wxid_test', profile_type='group_member', group_id='b@chatroom')['group_display_name'] == 'B1'
        assert len(store.history('wxid_test', profile_type='group_member', group_id='a@chatroom')) == 2
        assert len(store.history('wxid_test', profile_type='group_member', group_id='b@chatroom')) == 2
        changes = store.changes('wxid_test', profile_type='group_member', group_id='a@chatroom')
        assert changes[0]['old'] == 'A1' and changes[0]['new'] == 'A2'
        assert changes[0]['comparison_scope'] == 'scoped'
        assert all(change['new'] != 'B1' for change in changes)


@pytest.mark.parametrize('failure', ['wrong_group', 'serialization', 'duplicate'])
def test_group_batch_failure_rolls_back_snapshots_current_and_changes(tmp_path, failure):
    with ProfileStore(tmp_path / 'profiles.sqlite3') as store:
        first = profile('a@chatroom', 'A1')
        second = profile('b@chatroom' if failure == 'wrong_group' else 'a@chatroom', 'A2',
                         wechat_id=' wxid_test ' if failure == 'duplicate' else 'wxid_other')
        if failure == 'serialization':
            second['raw'] = {'bad': {1, 2}}
        with pytest.raises((ValueError, TypeError)):
            store.save_group_members([first, second], group_id='a@chatroom')
        assert store.get('wxid_test', profile_type='group_member', group_id='a@chatroom') is None
        assert store.history('wxid_test', profile_type='group_member') == []
        assert store.changes('wxid_test', profile_type='group_member', group_id='a@chatroom') == []
        store.save_group_members([first], group_id='a@chatroom')
        assert len(store.history('wxid_test', profile_type='group_member')) == 1


def test_legacy_migration_preserves_raw_history_and_marks_it_unverified(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    originals = [json.dumps(profile('a@chatroom', 'legacy-A')), json.dumps(profile('b@chatroom', 'legacy-B'))]
    with ProfileStore(path) as store:
        for text in originals:
            store._connection.execute("INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json) VALUES('group_member','wxid_test',?)", (text,))
        store._connection.execute("INSERT INTO profiles(profile_type,wechat_id,group_id,raw_json) VALUES('group_member','wxid_test','b@chatroom','{}')")
        store._connection.execute("DELETE FROM group_profile_meta WHERE key='scope_index_v1'")
        store._connection.commit()
    with ProfileStore(path) as store:
        for group in ('a@chatroom', 'b@chatroom'):
            saved = store.get('wxid_test', profile_type='group_member', group_id=group)
            assert saved['verification_status'] == 'legacy_unverified'
        before = [row[0] for row in store._connection.execute('SELECT profile_json FROM profile_snapshots ORDER BY snapshot_id')]
        assert before == originals
        result = store.save(profile('a@chatroom', 'fresh-A'), profile_type='group_member')
        assert result['comparison_scope'] == 'scoped_baseline'
        assert store.get('wxid_test', profile_type='group_member', group_id='a@chatroom')['verification_status'] == 'observed_scoped'
        assert store.get('wxid_test', profile_type='group_member', group_id='b@chatroom')['verification_status'] == 'legacy_unverified'
        assert store._connection.execute('SELECT COUNT(*) FROM profiles').fetchone()[0] == 1
    with ProfileStore(path) as store:
        assert store._connection.execute('SELECT COUNT(*) FROM group_profile_versions').fetchone()[0] == 3
        old = [row[0] for row in store._connection.execute('SELECT profile_json FROM profile_snapshots ORDER BY snapshot_id LIMIT 2')]
        assert old == originals


def test_malformed_legacy_snapshot_is_preserved_but_not_promoted(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as store:
        store._connection.execute("INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json) VALUES('group_member','wxid_test','invalid-json')")
        store._connection.execute("DELETE FROM group_profile_meta WHERE key='scope_index_v1'")
        store._connection.commit()
    with ProfileStore(path) as store:
        assert store.get('wxid_test', profile_type='group_member', group_id='a@chatroom') is None
        summary = json.loads(store._connection.execute("SELECT value FROM group_profile_meta WHERE key='scope_index_v1'").fetchone()[0])
        assert summary == {'indexed': 0, 'skipped': 1}
        assert store._connection.execute('SELECT profile_json FROM profile_snapshots').fetchone()[0] == 'invalid-json'


def test_failed_scope_initialization_closes_connection(tmp_path):
    import sqlite3
    connection = sqlite3.connect(tmp_path / 'profiles.sqlite3')
    with (patch('wechat_auto.storage.profile_store.sqlite3.connect', return_value=connection),
          patch.object(ProfileStore, '_initialize_group_scopes', side_effect=RuntimeError('synthetic migration fault')),
          pytest.raises(RuntimeError, match='migration fault')):
        ProfileStore(tmp_path / 'profiles.sqlite3')
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute('SELECT 1')


def test_group_save_sql_failure_rolls_back_all_three_records(tmp_path):
    import sqlite3
    with ProfileStore(tmp_path / 'profiles.sqlite3') as store:
        store._connection.execute("""CREATE TRIGGER fail_group_change BEFORE INSERT ON profile_changes
            WHEN NEW.profile_type='group_member' BEGIN SELECT RAISE(ABORT,'synthetic change failure'); END""")
        store._connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            store.save(profile('a@chatroom', 'A1'), profile_type='group_member')
        assert store.history('wxid_test', profile_type='group_member') == []
        assert store.get('wxid_test', profile_type='group_member', group_id='a@chatroom') is None
        assert store._connection.execute('SELECT COUNT(*) FROM group_profile_versions').fetchone()[0] == 0


def test_empty_cached_group_batch_does_not_remove_previous_members(tmp_path):
    with ProfileStore(tmp_path / 'profiles.sqlite3') as store:
        store.save(profile('a@chatroom', 'A1'), profile_type='group_member')
        assert store.save_group_members([], group_id='a@chatroom') == []
        assert store.get('wxid_test', profile_type='group_member', group_id='a@chatroom')['group_display_name'] == 'A1'


def test_mid_migration_failure_rolls_back_index_and_can_resume(tmp_path):
    import sqlite3
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as store:
        for group in ('a@chatroom', 'b@chatroom'):
            store._connection.execute("INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json) VALUES('group_member','wxid_test',?)",
                                      (json.dumps(profile(group, 'legacy')),))
        store._connection.execute("DELETE FROM group_profile_meta WHERE key='scope_index_v1'")
        store._connection.commit()
    with (patch.object(ProfileStore, '_group_id', side_effect=['a@chatroom', RuntimeError('synthetic mid-migration fault')]),
          pytest.raises(RuntimeError, match='mid-migration fault')):
        ProfileStore(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute('SELECT COUNT(*) FROM group_profile_versions').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM group_profile_meta').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM profile_snapshots').fetchone()[0] == 2
    finally:
        connection.close()
    with ProfileStore(path) as store:
        assert store.get('wxid_test', profile_type='group_member', group_id='b@chatroom')['verification_status'] == 'legacy_unverified'


def test_two_connections_can_initialize_same_legacy_scope_index(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as store:
        store._connection.execute("INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json) VALUES('group_member','wxid_test',?)",
                                  (json.dumps(profile('a@chatroom', 'legacy')),))
        store._connection.execute("DELETE FROM group_profile_meta WHERE key='scope_index_v1'")
        store._connection.commit()
    barrier = Barrier(2)
    def open_store():
        barrier.wait(timeout=5)
        with ProfileStore(path) as store:
            return store.get('wxid_test', profile_type='group_member', group_id='a@chatroom')['verification_status']
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(open_store) for _ in range(2)]
        assert [future.result(timeout=10) for future in futures] == ['legacy_unverified'] * 2
    with ProfileStore(path) as store:
        assert store._connection.execute('SELECT COUNT(*) FROM group_profile_versions').fetchone()[0] == 1


@pytest.mark.parametrize('extra,error', [({'username': 'wxid_other'}, ValueError),
                                         ({'chatroom_id': 'other@chatroom'}, ValueError),
                                         ({'is_owner': '0'}, TypeError)])
def test_direct_group_save_requires_normalized_identity_scope_and_flags(tmp_path, extra, error):
    with ProfileStore(tmp_path / 'profiles.sqlite3') as store:
        with pytest.raises(error):
            store.save(profile('a@chatroom', 'A1', **extra), profile_type='group_member')
        assert store.history('wxid_test', profile_type='group_member') == []
