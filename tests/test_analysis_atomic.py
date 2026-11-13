"""Failed analysis cannot publish partial facts, versions or coverage."""

import sqlite3
from unittest.mock import patch

import pytest

from wechat_auto.memory import AnalysisService, MarkdownMemory, MemoryStore


@pytest.mark.parametrize('failure', ['add_claim', 'add_event', 'write', 'update_coverage',
                                    'complete_run', 'propagate_dirty', '_commit_atomic', 'interrupt'])
@pytest.mark.parametrize('existing', [False, True])
def test_analysis_failure_rolls_back_facts_files_and_watermarks(tmp_path, failure, existing):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        service = AnalysisService(store, memory)
        conversation = store.ensure_conversation('wxid_test_one', conversation_type='direct')
        baseline = {'scope_type': 'conversation', 'scope_id': conversation, 'period': '2026-09',
                    'template_version': 'synthetic'}
        if existing:
            service.submit(**baseline, markdown='# Original\ncomplete body', evidence_ids=['old'],
                           claims=[{'canonical_text': 'original fact', 'claim_type': 'fact'}],
                           events=[{'event_type': 'task', 'title': 'original event', 'event_id': 'e1'}],
                           coverage={'message_watermark': '10'})
            # Separate timestamps deterministically; the failed run must be
            # identified by ID, never whichever row sorts first in one second.
            store._connection.execute("UPDATE analysis_runs SET started_at='2000-01-01T00:00:00+00:00'")
            store._connection.commit()
        runs_before = {row[0] for row in store._connection.execute('SELECT run_id FROM analysis_runs')}
        original_body = memory.read_current('conversation', conversation, '2026-09')
        before = store.database_summary()
        coverage_before = [tuple(row) for row in store._connection.execute('SELECT * FROM analysis_coverage')]
        dirty_before = store._connection.execute('SELECT count(*) FROM dirty_nodes').fetchone()[0]
        target = memory if failure == 'write' else store._connection if failure == '_commit_atomic' else store
        method = 'update_coverage' if failure == 'interrupt' else failure
        original = getattr(target, method)
        error_type = KeyboardInterrupt if failure == 'interrupt' else sqlite3.OperationalError

        def fail_after_write(*args, **kwargs):
            if failure not in {'write', '_commit_atomic'}:
                original(*args, **kwargs)
            raise error_type('synthetic analysis failure')

        with patch.object(target, method, side_effect=fail_after_write), pytest.raises(
            error_type, match='synthetic analysis failure'
        ):
            service.submit(**baseline, markdown='# Candidate\nnew complete body', evidence_ids=['new'],
                           claims=[{'canonical_text': 'new fact', 'claim_type': 'fact'}],
                           events=[{'event_type': 'task', 'title': 'changed event', 'event_id': 'e1'}],
                           coverage={'message_watermark': '20'}, expected_parent=int(existing))
        after = store.database_summary()
        for name in ('claims', 'events', 'analysis_versions', 'analysis_jobs'):
            assert after[name] == before[name]
        if existing:
            assert store.get_event('e1')['title'] == 'original event'
        else:
            assert store.get_event('e1') is None
        assert [tuple(row) for row in store._connection.execute('SELECT * FROM analysis_coverage')] == coverage_before
        assert store._connection.execute('SELECT count(*) FROM dirty_nodes').fetchone()[0] == dirty_before
        assert store._connection.execute('SELECT count(*) FROM event_versions').fetchone()[0] == int(existing)
        assert memory.read_current('conversation', conversation, '2026-09') == original_body
        directory = memory._directory('conversation', conversation, '2026-09')
        if existing:
            assert (directory / 'current.md').read_text(encoding='utf-8') == original_body
        else:
            assert not (directory / 'current.md').exists()
        assert not (directory / 'versions' / f'v{int(existing)+1:06d}.md').exists()
        runs_after = dict(store._connection.execute('SELECT run_id,status FROM analysis_runs'))
        new_runs = runs_after.keys() - runs_before
        assert len(new_runs) == 1
        assert runs_after[new_runs.pop()] == 'failed'
        assert all(runs_after[run_id] == 'complete' for run_id in runs_before)


def test_atomic_batch_is_invisible_to_other_connection_until_commit(tmp_path):
    path = tmp_path / 'memory.sqlite3'
    with MemoryStore(path) as store, MemoryStore(path) as observer:
        with store.atomic():
            store.ensure_person('wxid_test_new')
            assert observer.database_summary()['people'] == 0
        assert observer.database_summary()['people'] == 1


def test_swallowed_inner_transaction_failure_still_rolls_back_batch(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        with pytest.raises(RuntimeError, match='marked for rollback'), store.atomic():
            store.ensure_person('wxid_test_new')
            try:
                with store.transaction():
                    raise ValueError('synthetic inner failure')
            except ValueError:
                pass
        assert store.database_summary()['people'] == 0


def test_schema_script_cannot_implicitly_commit_atomic_batch(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        with pytest.raises(RuntimeError, match='Schema scripts'), store.atomic():
            store.ensure_person('wxid_test_new')
            store._connection.executescript('CREATE TABLE unexpected(value TEXT);')
        assert store.database_summary()['people'] == 0
        assert store._connection.execute(
            "SELECT name FROM sqlite_master WHERE name='unexpected'"
        ).fetchone() is None
