"""Abrupt child exit must not expose an uncommitted analysis as successful."""

import subprocess
import sys

import pytest

from wechat_auto.memory import AnalysisService, MarkdownMemory, MemoryStore


@pytest.mark.parametrize('existing', [False, True])
def test_exit_after_markdown_publish_rolls_back_database_and_keeps_candidate(tmp_path, existing):
    database, root = tmp_path / 'memory.sqlite3', tmp_path / 'memory'
    with MemoryStore(database) as store:
        conversation = store.ensure_conversation('wxid_test_one', conversation_type='direct')
        memory = MarkdownMemory(root, store)
        if existing:
            AnalysisService(store, memory).submit(
                scope_type='conversation', scope_id=conversation, period='2026-09',
                markdown='# Original\ncomplete body', evidence_ids=['old'], template_version='synthetic')
        original = memory.read_current('conversation', conversation, '2026-09')
    code = '''
import os,sys
from wechat_auto.memory import AnalysisService,MarkdownMemory,MemoryStore
with MemoryStore(sys.argv[1]) as store:
    memory=MarkdownMemory(sys.argv[2],store)
    store.update_coverage=lambda *args,**kwargs: os._exit(23)
    AnalysisService(store,memory).submit(
        scope_type='conversation',scope_id=sys.argv[3],period='2026-09',
        markdown='# Candidate\\nnot committed',evidence_ids=['new'],template_version='synthetic',
        claims=[{'canonical_text':'uncommitted fact','claim_type':'fact'}],
        events=[{'title':'uncommitted event'}])
'''
    result = subprocess.run([sys.executable, '-c', code, str(database), str(root), conversation],
                            capture_output=True, timeout=20, check=False)
    assert result.returncode == 23
    with MemoryStore(database) as store:
        memory = MarkdownMemory(root, store)
        assert memory.read_current('conversation', conversation, '2026-09') == original
        counts = store.database_summary()
        assert counts['analysis_versions'] == int(existing)
        assert counts['claims'] == counts['events'] == 0
        assert store._connection.execute("SELECT count(*) FROM analysis_runs WHERE status='running'").fetchone()[0] == 1
        directory = memory._directory('conversation', conversation, '2026-09')
        candidate = directory / 'versions' / f'v{int(existing)+1:06d}.md'
        assert candidate.read_text(encoding='utf-8').startswith('# Candidate')
        with pytest.raises(FileNotFoundError, match='successfully indexed'):
            memory.read_version('conversation', conversation, int(existing) + 1, '2026-09')
        assert (directory / 'current.md').read_text(encoding='utf-8') == candidate.read_text(encoding='utf-8')
        with pytest.raises(RuntimeError, match='Unindexed'):
            memory.write('conversation', conversation, '# Retry\nnew body', period='2026-09',
                         input_fingerprint='retry')
        candidate_bytes = candidate.read_bytes()
        recovery = memory.recover_publication('conversation', conversation, '2026-09')
        assert recovery['changed'] and not recovery['promoted']
        from pathlib import Path

        work = Path(recovery['work_dir'])
        assert work.is_relative_to(tmp_path / 'work/analysis')
        assert (work / 'versions' / candidate.name).read_bytes() == candidate_bytes
        assert (work / 'current.md').read_bytes() == candidate_bytes
        assert not candidate.exists()
        assert memory.read_current('conversation', conversation, '2026-09') == original
        if existing:
            assert (directory / 'current.md').read_text(encoding='utf-8') == original
        else:
            assert not (directory / 'current.md').exists()
        assert memory.recover_publication('conversation', conversation, '2026-09')['changed'] is False
        assert store._connection.execute("SELECT count(*) FROM analysis_runs WHERE status='running'").fetchone()[0] == 1
        assert memory.write('conversation', conversation, '# Retry\nnew body', period='2026-09',
                            input_fingerprint='retry')['version'] == int(existing) + 1
