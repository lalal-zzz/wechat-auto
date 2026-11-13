import pytest

from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.memory.store import MemoryStore
from wechat_auto.storage import ProfileStore


def test_equal_local_snapshot_ids_from_distinct_archives_remain_distinct(tmp_path):
    paths = [tmp_path / 'one.sqlite3', tmp_path / 'two.sqlite3']
    for index, path in enumerate(paths):
        with ProfileStore(path) as profiles:
            result = profiles.save({'wechat_id': f'wxid_test_synthetic_{index}', 'nickname': 'synthetic'}, profile_type='contact')
            assert result['snapshot_id'] == 1
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        indexer = ArchiveIndexer(memory)
        for path in paths:
            indexer.index_profile_snapshots(path)
        rows = memory._connection.execute('SELECT snapshot_ref,person_id FROM profile_snapshot_refs').fetchall()
        assert len(rows) == 2
        assert len({row[0] for row in rows}) == len({row[1] for row in rows}) == 2
        assert all(row[0].startswith('profile:') for row in rows)


def test_bound_reference_requires_same_archive_and_unchanged_content(tmp_path):
    from wechat_auto.memory.evidence import EvidenceResolver
    from wechat_auto.utils.profile_reference import profile_reference
    paths = [tmp_path / 'one.sqlite3', tmp_path / 'two.sqlite3']
    for path in paths:
        with ProfileStore(path) as profiles:
            profiles.save({'wechat_id': 'wxid_test', 'signature': 'private synthetic body'}, profile_type='contact')
    with ProfileStore(paths[0]) as profiles:
        digest = profiles.snapshot_by_id(1)['content_hash']
    ref = profile_reference(paths[0], 1, digest)
    resolver = EvidenceResolver(profiles_path=paths[0])
    compact = resolver.get('profile_snapshot', ref)
    assert compact['id'] == ref and compact['reference_scope'] == 'source_and_content_bound'
    assert 'private synthetic body' not in repr(compact)
    assert 'private synthetic body' in repr(resolver.get('profile_snapshot', ref, include_content=True))
    assert EvidenceResolver(profiles_path=paths[1]).get('profile_snapshot', ref) is None
    assert resolver.get('profile_snapshot', '1')['reference_scope'] == 'legacy_local_id'
    with ProfileStore(paths[0]) as profiles:
        profiles._connection.execute("UPDATE profile_snapshots SET profile_json='{}' WHERE snapshot_id=1")
        profiles._connection.commit()
    assert resolver.get('profile_snapshot', ref) is None


def test_v2_reference_index_replays_old_cursor_without_rewriting_old_refs(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test'}, profile_type='contact')
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_test')
        memory._connection.execute("INSERT INTO profile_snapshot_refs VALUES('1',?,'old','legacy','old-hash')", (person,))
        memory._connection.execute("INSERT INTO sync_cursors(source,stream_id,cursor,updated_at) VALUES('profile_snapshot_index',?,'1',CURRENT_TIMESTAMP)", (str(path.resolve()),))
        memory._connection.commit()
        indexer = ArchiveIndexer(memory)
        assert indexer.index_profile_snapshots(path)['snapshots_seen'] == 1
        assert indexer.index_profile_snapshots(path)['snapshots_seen'] == 0
        assert memory._connection.execute('SELECT COUNT(*) FROM profile_snapshot_refs').fetchone()[0] == 2
        assert memory._connection.execute("SELECT content_hash FROM profile_snapshot_refs WHERE snapshot_ref='1'").fetchone()[0] == 'old-hash'


def test_invalid_bound_reference_never_falls_back_to_local_number(tmp_path):
    from wechat_auto.memory.evidence import EvidenceResolver
    from wechat_auto.utils.profile_reference import profile_source_key
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test'}, profile_type='contact')
    resolver = EvidenceResolver(profiles_path=path)
    for value in ('profile:1', f'profile:{profile_source_key(path)}:9999999999999999999:{"0"*64}',
                  f'profile:{profile_source_key(path)}:1:bad-hash'):
        assert resolver.get('profile_snapshot', value) is None

@pytest.mark.parametrize('column', ['wechat_id', 'captured_at', 'source'])
def test_bound_reference_rejects_changed_snapshot_metadata(tmp_path, column):
    from wechat_auto.memory.evidence import EvidenceResolver
    from wechat_auto.utils.profile_reference import profile_reference
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test'}, profile_type='contact')
        reference = profile_reference(path, 1, profiles.snapshot_by_id(1)['content_hash'])
        profiles._connection.execute(f'UPDATE profile_snapshots SET {column}=? WHERE snapshot_id=1', ('changed',))
        profiles._connection.commit()
    assert EvidenceResolver(profiles_path=path).get('profile_snapshot', reference) is None


def test_snapshot_subject_mismatch_cannot_create_a_bound_reference(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test'}, profile_type='contact')
        profiles._connection.execute("UPDATE profile_snapshots SET wechat_id='wxid_other'")
        profiles._connection.commit()
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        with pytest.raises(ValueError, match='subject identity'):
            ArchiveIndexer(memory).index_profile_snapshots(path)
        assert memory._connection.execute('SELECT COUNT(*) FROM profile_snapshot_refs').fetchone()[0] == 0


def test_unverified_malformed_group_snapshot_is_skipped_without_stalling(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles._connection.execute("INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json) VALUES('group_member','wxid_test_legacy','invalid-json')")
        profiles._connection.commit()
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        result = ArchiveIndexer(memory).index_profile_snapshots(path)
        assert result['legacy_group_snapshots_skipped'] == 1 and result['cursor'] == 1
        assert result['snapshots_seen'] == 0
