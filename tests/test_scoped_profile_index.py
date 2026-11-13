import json

import pytest

from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.memory.store import MemoryStore
from wechat_auto.storage import ProfileStore


def test_scoped_groups_share_person_and_keep_contextual_aliases(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test', 'nickname': 'contact-name', 'display_name': 'preferred-name'}, profile_type='contact')
        for group, name in [('a@chatroom', 'group-A'), ('b@chatroom', 'group-B')]:
            profiles.save({'wechat_id': 'wxid_test', 'nickname': 'global-name', 'group_id': group,
                           'group_display_name': name}, profile_type='group_member')
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        indexer = ArchiveIndexer(memory)
        result = indexer.index_profiles(path)
        assert result['people_created_or_seen'] == 1 and result['scoped_group_profiles_seen'] == 2
        assert memory._connection.execute('SELECT display_name FROM people').fetchone()[0] == 'preferred-name'
        aliases = memory._connection.execute("SELECT alias_value,context_id FROM person_aliases WHERE alias_type='group_display_name' ORDER BY context_id").fetchall()
        assert [tuple(row) for row in aliases] == [('group-A', 'a@chatroom'), ('group-B', 'b@chatroom')]
        assert memory._connection.execute("SELECT COUNT(*) FROM person_aliases WHERE alias_type='nickname' AND alias_value LIKE 'group-%'").fetchone()[0] == 0
        assert indexer.index_profile_snapshots(path)['snapshots_seen'] == 3
        assert indexer.index_profile_snapshots(path)['snapshots_seen'] == 0
        indexer.index_profiles(path)
        assert memory._connection.execute("SELECT COUNT(*) FROM person_aliases WHERE alias_type='group_display_name'").fetchone()[0] == 2


def test_legacy_group_rows_are_skipped_and_cursor_does_not_stall(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles._connection.execute("INSERT INTO profiles(profile_type,wechat_id,nickname,raw_json) VALUES('group_member','wxid_test_legacy','legacy','{}')")
        profiles._connection.execute("INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json) VALUES('group_member','wxid_test_legacy',?)",
                                     (json.dumps({'wechat_id': 'wxid_test_legacy', 'group_id': 'a@chatroom'}),))
        profiles._connection.commit()
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        indexer = ArchiveIndexer(memory)
        assert indexer.index_profiles(path)['profiles_seen'] == 0
        result = indexer.index_profile_snapshots(path)
        assert result['snapshots_seen'] == 0 and result['legacy_group_snapshots_skipped'] == 1
        assert result['cursor'] > 0
        assert indexer.index_profile_snapshots(path)['legacy_group_snapshots_skipped'] == 0
        assert memory._connection.execute('SELECT COUNT(*) FROM people').fetchone()[0] == 0


def test_mismatched_scoped_profile_rolls_back_prior_contact_index(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test_contact', 'nickname': 'contact'}, profile_type='contact')
        profiles.save({'wechat_id': 'wxid_test', 'group_id': 'a@chatroom'}, profile_type='group_member')
        profiles._connection.execute("UPDATE group_profile_current SET wechat_id='wxid_other'")
        profiles._connection.commit()
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        with pytest.raises(ValueError, match='identity mismatch'):
            ArchiveIndexer(memory).index_profiles(path)
        assert memory._connection.execute('SELECT COUNT(*) FROM people').fetchone()[0] == 0


def test_scoped_snapshot_mismatch_rolls_back_refs_people_and_cursor(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test_contact', 'nickname': 'contact'}, profile_type='contact')
        profiles.save({'wechat_id': 'wxid_test', 'group_id': 'a@chatroom'}, profile_type='group_member')
        profiles._connection.execute("UPDATE group_profile_versions SET group_id='other@chatroom'")
        profiles._connection.commit()
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        with pytest.raises(ValueError, match='snapshot identity mismatch'):
            ArchiveIndexer(memory).index_profile_snapshots(path)
        for table in ('people', 'profile_snapshot_refs', 'dirty_nodes', 'sync_cursors'):
            assert memory._connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
