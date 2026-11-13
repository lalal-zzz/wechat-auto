import sqlite3
from contextlib import nullcontext
from unittest.mock import patch

import pytest

from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.memory.store import MemoryStore
from wechat_auto.storage import MomentStore


@pytest.mark.parametrize('incremental,stage', [(initial, stage) for initial in (False, True)
                                               for stage in ('person', 'dirty', 'cursor')] + [(True, 'queue')])
def test_moment_index_failure_rolls_back_all_state_and_can_resume(tmp_path, incremental, stage):
    path = tmp_path / 'moments.sqlite3'
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        indexer = ArchiveIndexer(memory)
        if incremental:
            with MomentStore(path) as moments:
                moments.save([{'id': 'baseline', 'username': 'wxid_test_baseline'}])
            indexer.index_moments(path)
        with MomentStore(path) as moments:
            moments.save([{'id': 'new1', 'username': 'wxid_first'}, {'id': 'new2', 'username': 'wxid_test_second'}])
        tables = ('people', 'person_identities', 'dirty_nodes', 'analysis_jobs', 'sync_cursors')
        before = {table: [tuple(row) for row in memory._connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                  for table in tables}
        if stage == 'cursor':
            memory._connection.execute("""CREATE TRIGGER reject_moment_cursor BEFORE INSERT ON sync_cursors
                WHEN NEW.source IN ('moment_index','moment_version_index') BEGIN SELECT RAISE(ABORT,'synthetic cursor fault'); END""")
            memory._connection.commit()
            fault = nullcontext()
        else:
            name = {'person': 'ensure_person', 'dirty': 'mark_dirty', 'queue': 'enqueue_job'}[stage]
            original = getattr(memory, name)
            calls = 0
            def fail_second(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError('synthetic index fault')
                return original(*args, **kwargs)
            fault = patch.object(memory, name, side_effect=fail_second)
        with fault, pytest.raises((RuntimeError, sqlite3.IntegrityError), match='synthetic'):
            indexer.index_moments(path)
        after = {table: [tuple(row) for row in memory._connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                 for table in tables}
        assert after == before
        if stage == 'cursor':
            memory._connection.execute('DROP TRIGGER reject_moment_cursor')
            memory._connection.commit()
        result = indexer.index_moments(path)
        assert result['moments_seen'] == 2
        assert indexer.index_moments(path)['moments_seen'] == 0


def test_concurrent_moment_indexers_only_process_new_rows_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / 'moments.sqlite3'
    memory_path = tmp_path / 'memory.sqlite3'
    with MomentStore(path) as moments:
        moments.save([{'id': 'new1', 'username': 'wxid_first'}, {'id': 'new2', 'username': 'wxid_test_second'}])
    with MemoryStore(memory_path):
        pass
    barrier = Barrier(2)
    def run_index():
        with MemoryStore(memory_path) as memory:
            barrier.wait(timeout=5)
            return ArchiveIndexer(memory).index_moments(path)['moments_seen']
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_index) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == [0, 2]
    with MemoryStore(memory_path) as memory:
        assert memory._connection.execute('SELECT COUNT(*) FROM people').fetchone()[0] == 2
        assert memory._connection.execute("SELECT cursor FROM sync_cursors WHERE source='moment_version_index'").fetchone()[0] == '2'


@pytest.mark.parametrize('failure', ['interrupt', 'commit'])
def test_moment_interrupt_or_commit_fault_leaves_no_partial_index(tmp_path, failure):
    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as moments:
        moments.save([{'id': 'new1', 'username': 'wxid_first'}])
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        target = memory if failure == 'interrupt' else memory._connection
        method = 'mark_dirty' if failure == 'interrupt' else '_commit_atomic'
        error = KeyboardInterrupt() if failure == 'interrupt' else RuntimeError('synthetic commit fault')
        with patch.object(target, method, side_effect=error), pytest.raises(type(error)):
            ArchiveIndexer(memory).index_moments(path)
        for table in ('people', 'person_identities', 'dirty_nodes', 'analysis_jobs', 'sync_cursors'):
            assert memory._connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        assert ArchiveIndexer(memory).index_moments(path)['moments_seen'] == 1
