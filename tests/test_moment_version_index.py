from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.memory.store import MemoryStore
from wechat_auto.storage import MomentStore


def test_existing_moment_edit_reaches_index_without_changing_rowid(tmp_path):
    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as store:
        store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'before'}])
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        indexer = ArchiveIndexer(memory)
        assert indexer.index_moments(path)['moments_seen'] == 1
        with MomentStore(path) as store:
            store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'after'}])
        assert indexer.index_moments(path)['moments_seen'] == 1
        assert indexer.index_moments(path)['moments_seen'] == 0


def test_old_moment_reference_keeps_original_text_after_multiple_edits(tmp_path):
    from wechat_auto.memory.evidence import EvidenceResolver
    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as store:
        store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'before'}])
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        indexer = ArchiveIndexer(memory)
        indexer.index_moments(path)
        reference = memory._connection.execute('SELECT source_id FROM dirty_nodes').fetchone()[0]
        with MomentStore(path) as store:
            store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'after'}])
            store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'after', 'comments': [{'text': 'new-comment'}]}])
        assert indexer.index_moments(path)['moments_seen'] == 2
        resolver = EvidenceResolver(moments_path=path)
        assert resolver.get('moment', reference, include_content=True)['text'] == 'before'
        assert 'before' not in repr(resolver.get('moment', reference))
        assert resolver.get('moment', reference)['reference_scope'] == 'source_and_version_bound'
        assert resolver.get('moment', 'same')['reference_scope'] == 'legacy_mutable_id'
        assert len(memory.next_jobs()) == 1
        assert indexer.index_moments(path)['moments_seen'] == 0


def test_old_source_is_seeded_once_as_legacy_baseline(tmp_path):
    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as store:
        store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'before'}])
        original = store._connection.execute('SELECT raw_json FROM moments').fetchone()[0]
        for name in ('moment_capture_insert', 'moment_capture_update', 'moment_identity_guard'):
            store._connection.execute(f'DROP TRIGGER {name}')
        store._connection.execute('DROP TABLE moment_versions')
        store._connection.execute('DROP TABLE moment_store_meta')
        store._connection.commit()
    with MomentStore(path) as store:
        assert store.get_version(1)['verification_status'] == 'legacy_baseline'
        assert store._connection.execute('SELECT raw_json FROM moments').fetchone()[0] == original
        store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'after'}])
        assert store.get_version(1)['text'] == 'before'
        assert store.get_version(2)['verification_status'] == 'observed'
    with MomentStore(path) as store:
        assert store._connection.execute('SELECT COUNT(*) FROM moment_versions').fetchone()[0] == 2


def test_moment_version_reference_rejects_other_archive_or_hash(tmp_path):
    from wechat_auto.memory.evidence import EvidenceResolver
    from wechat_auto.utils.moment_reference import moment_reference
    paths = [tmp_path / 'a.sqlite3', tmp_path / 'b.sqlite3']
    for path in paths:
        with MomentStore(path) as store:
            store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'synthetic'}])
    with MomentStore(paths[0]) as store:
        reference = moment_reference(paths[0], 1, store.get_version(1)['content_hash'])
    assert EvidenceResolver(moments_path=paths[1]).get('moment', reference) is None
    parts = reference.split(':')
    parts[-1] = '0'*64
    assert EvidenceResolver(moments_path=paths[0]).get('moment', ':'.join(parts)) is None


def test_failed_current_write_does_not_leave_a_version(tmp_path):
    import sqlite3

    import pytest
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store._connection.execute("""CREATE TRIGGER reject_second BEFORE INSERT ON moments
            WHEN NEW.id='second' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END""")
        store._connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            store.save([{'id': 'first', 'username': 'wxid_test'}, {'id': 'second', 'username': 'wxid_test'}])
        assert store.get_version(1) is None


def test_version_mutation_is_rejected_by_sqlite(tmp_path):
    import sqlite3

    import pytest
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'before'}])
        for sql in ("UPDATE moment_versions SET text='other'", 'DELETE FROM moment_versions'):
            with pytest.raises(sqlite3.IntegrityError, match='append-only'):
                store._connection.execute(sql)
            store._connection.rollback()
        assert store.get_version(1)['text'] == 'before'


def test_failed_legacy_version_seed_preserves_source_and_can_retry(tmp_path):
    import sqlite3
    from unittest.mock import patch

    import pytest

    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as store:
        store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'legacy'}])
        original = store._connection.execute('SELECT raw_json FROM moments').fetchone()[0]
        for name in ('moment_capture_insert', 'moment_capture_update', 'moment_identity_guard'):
            store._connection.execute(f'DROP TRIGGER {name}')
        store._connection.execute('DROP TABLE moment_versions')
        store._connection.execute('DROP TABLE moment_store_meta')
        store._connection.commit()
    class FaultConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith('INSERT INTO moment_store_meta'):
                raise RuntimeError('synthetic migration marker failure')
            return super().execute(sql, *args, **kwargs)
    connection = sqlite3.connect(path, factory=FaultConnection)
    with (patch('wechat_auto.storage.moment_store.sqlite3.connect', return_value=connection),
          pytest.raises(RuntimeError, match='migration marker failure')):
        MomentStore(path)
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute('SELECT 1')
    with MomentStore(path) as store:
        assert store._connection.execute('SELECT raw_json FROM moments').fetchone()[0] == original
        assert store.get_version(1)['verification_status'] == 'legacy_baseline'
        assert store._connection.execute('SELECT COUNT(*) FROM moment_versions').fetchone()[0] == 1
