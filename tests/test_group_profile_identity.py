from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from wechat_auto.backends.profile import DatabaseProfileBackend


@pytest.mark.parametrize('group_id', ['', 'wxid_test_person', None])
def test_group_reader_rejects_non_group_ids_before_adapter_call(group_id):
    reader = MagicMock(return_value=[])
    with pytest.raises(ValueError):
        DatabaseProfileBackend(SimpleNamespace(get_group_members=reader)).get_group_members(group_id)
    reader.assert_not_called()


@pytest.mark.parametrize('records', [
    [{'username': 'wxid_test', 'group_id': 'other@chatroom'}],
    [{'username': 'wxid_test', 'wxid': 'wxid_other'}],
    [{'alias': 'public-test'}],
    [{'username': 'wxid_test'}, {'username': 'wxid_test'}],
    [{'username': 'wxid_test'}, None],
])
def test_group_reader_rejects_cross_group_or_ambiguous_member_identity(records):
    backend = DatabaseProfileBackend(SimpleNamespace(get_group_members=lambda group_id: records))
    with pytest.raises((ValueError, TypeError)):
        backend.get_group_members('test@chatroom')


@pytest.mark.parametrize('flag,expected', [(False, False), (True, True), (0, False), (1, True),
                                          ('0', False), ('1', True), ('false', False), ('true', True),
                                          (None, None)])
def test_group_reader_keeps_scoped_name_and_explicit_owner_flag(flag, expected):
    db = SimpleNamespace(get_group_members=lambda group_id: [{'wxid': 'wxid_test',
        'nickname': 'global-name', 'group_display_name': 'group-name', 'is_owner': flag}])
    member = DatabaseProfileBackend(db).get_group_members('test@chatroom')[0]
    assert member['wechat_id'] == 'wxid_test'
    assert member['nickname'] == 'global-name'
    assert member['group_display_name'] == 'group-name'
    assert member['group_id'] == 'test@chatroom'
    assert member['is_owner'] is expected


def test_group_archive_uses_scoped_current_profile_key(tmp_path):
    reader = MagicMock(return_value=[{'username': 'wxid_test'}])
    backend = DatabaseProfileBackend(SimpleNamespace(get_group_members=reader))
    path = tmp_path / 'profiles.sqlite3'
    result = backend.archive_group_members('test@chatroom', str(path))
    reader.assert_called_once_with('test@chatroom')
    assert result['members'] == 1 and result['coverage_status'] == 'cached_only'
    assert not result['server_members_complete']
    from wechat_auto.storage import ProfileStore
    with ProfileStore(path) as store:
        assert store.get('wxid_test', profile_type='group_member', group_id='test@chatroom')['wechat_id'] == 'wxid_test'

@pytest.mark.parametrize('flag', ['yes', 2, [], 1.0])
def test_unrecognized_owner_flags_do_not_become_truthy_facts(flag):
    db = SimpleNamespace(get_group_members=lambda group_id: [{'username': 'wxid_test', 'is_owner': flag}])
    with pytest.raises(ValueError, match='owner flag'):
        DatabaseProfileBackend(db).get_group_members('test@chatroom')


def test_legacy_adapter_member_fields_remain_scoped_and_owner_unknown():
    db = SimpleNamespace(get_group_members=lambda group_id: [{'username': 'wxid_test',
        'nick_name': 'global-name', 'display_name': 'local-group-name'}])
    member = DatabaseProfileBackend(db).get_group_members('test@chatroom')[0]
    assert member['nickname'] == 'global-name'
    assert member['group_display_name'] == 'local-group-name'
    assert member['is_owner'] is None


def test_direct_profile_store_cannot_bypass_group_archive_guard(tmp_path):
    from wechat_auto.storage import ProfileStore
    with ProfileStore(tmp_path / 'profiles.sqlite3') as store:
        with pytest.raises(PermissionError, match='Group-scoped'):
            store.save({'wechat_id': 'wxid_test', 'group_display_name': 'test-name'}, profile_type='group_member')
        assert store.history('wxid_test', profile_type='group_member') == []


def test_legacy_unscoped_current_is_rejected_without_deleting_history(tmp_path):
    import json

    from wechat_auto.storage import ProfileStore
    payload = {'wechat_id': 'wxid_test', 'group_id': 'test@chatroom', 'group_display_name': 'legacy-name'}
    with ProfileStore(tmp_path / 'profiles.sqlite3') as store:
        store._connection.execute("INSERT INTO profiles(profile_type,wechat_id,group_id,raw_json) VALUES(?,?,?,?)",
                                  ('group_member', 'wxid_test', 'test@chatroom', '{}'))
        store._connection.execute("INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json) VALUES(?,?,?)",
                                  ('group_member', 'wxid_test', json.dumps(payload)))
        store._connection.commit()
        with pytest.raises(PermissionError, match='Group-scoped'):
            store.get('wxid_test', profile_type='group_member')
        assert store.history('wxid_test', profile_type='group_member')[0]['profile'] == payload
        assert store._connection.execute('SELECT COUNT(*) FROM profiles').fetchone()[0] == 1
