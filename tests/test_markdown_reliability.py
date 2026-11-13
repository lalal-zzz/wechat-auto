"""Failure injection for complete Markdown versions and current pointers."""

import subprocess
import sys
from unittest.mock import patch

import pytest

from wechat_auto.memory import MarkdownMemory, MemoryStore


@pytest.mark.parametrize('failure', ['version_replace', 'current_replace', 'record_version'])
def test_failed_publication_preserves_previous_complete_version(tmp_path, failure):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        memory.write('person', 'p1', '# Original\ncomplete body', input_fingerprint='first')
        original = memory.read_current('person', 'p1')
        original_write = memory._atomic_write

        def write(path, body):
            if ((failure == 'version_replace' and path.name == 'v000002.md')
                    or (failure == 'current_replace' and path.name == 'current.md')):
                raise OSError('synthetic write failure')
            original_write(path, body)

        with (
            patch.object(memory, '_atomic_write', side_effect=write),
            patch.object(store, 'record_version', side_effect=RuntimeError('synthetic index failure'))
            if failure == 'record_version' else patch.object(store, 'record_version', wraps=store.record_version),
            pytest.raises((OSError, RuntimeError)),
        ):
            memory.write('person', 'p1', '# Candidate\nnew complete body', input_fingerprint='second')
        assert memory.read_current('person', 'p1') == original
        assert memory.read_version('person', 'p1', 1) == original
        assert store.current_version('person', 'p1')['version'] == 1
        assert not (tmp_path / 'memory/people/p1/versions/v000002.md').exists()
        assert not list((tmp_path / 'memory').rglob('*.tmp'))


def test_failed_atomic_replace_leaves_original_and_removes_temporary_file(tmp_path):
    path = tmp_path / 'current.md'
    path.write_text('original', encoding='utf-8')
    with patch('wechat_auto.memory.markdown.os.replace', side_effect=OSError('synthetic')), pytest.raises(OSError):
        MarkdownMemory._atomic_write(path, 'candidate')
    assert path.read_text(encoding='utf-8') == 'original'
    assert list(tmp_path.iterdir()) == [path]


def test_same_target_lock_rejects_competing_writer_then_allows_retry(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        directory = memory._directory('person', 'p1')
        directory.mkdir(parents=True)
        with memory._write_lock(directory), pytest.raises(RuntimeError, match='already being written'):
            memory.write('person', 'p1', '# Candidate\nbody', input_fingerprint='first')
        assert store.current_version('person', 'p1') is None
        assert memory.write('person', 'p1', '# Candidate\nbody', input_fingerprint='first')['version'] == 1


def test_unindexed_version_is_preserved_for_review(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        version = tmp_path / 'memory/people/p1/versions/v000001.md'
        version.parent.mkdir(parents=True)
        version.write_text('unindexed complete candidate', encoding='utf-8')
        with pytest.raises(RuntimeError, match='Unindexed'):
            memory.write('person', 'p1', '# Different\nbody', input_fingerprint='first')
        assert version.read_text(encoding='utf-8') == 'unindexed complete candidate'
        assert memory.read_current('person', 'p1') == ''


def test_stale_parent_is_rejected_even_when_content_is_unchanged(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        memory.write('person', 'p1', '# Original\nbody', input_fingerprint='first')
        with pytest.raises(RuntimeError, match='stale Markdown parent'):
            memory.write('person', 'p1', '# Original\nbody', input_fingerprint='first', expected_parent=0)


@pytest.mark.parametrize('component', ['../escape', 'con', 'NUL.txt', 'name.', 'name ', ' name', 'a\x01b'])
def test_unsafe_windows_components_do_not_create_memory_files(tmp_path, component):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        with pytest.raises(ValueError, match='unsafe memory path'):
            memory.write('person', component, '# Original\nbody', input_fingerprint='first')
        assert list(memory.root.iterdir()) == []


def test_uncommitted_current_file_is_not_exposed_as_successful_memory(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        directory = memory._directory('person', 'p1')
        directory.mkdir(parents=True)
        (directory / 'current.md').write_text('uncommitted candidate', encoding='utf-8')
        assert memory.read_current('person', 'p1') == ''
        (directory / 'current.md').unlink()
        memory.write('person', 'p1', '# Original\ncomplete', input_fingerprint='first')
        original = memory.read_current('person', 'p1')
        (directory / 'current.md').write_text('new uncommitted candidate', encoding='utf-8')
        assert memory.read_current('person', 'p1') == original
        (directory / 'versions/v000001.md').write_text('corrupted indexed body', encoding='utf-8')
        with pytest.raises(RuntimeError, match='integrity validation'):
            memory.read_current('person', 'p1')


def test_os_releases_memory_lock_after_abrupt_process_exit(tmp_path):
    directory = tmp_path / 'target'
    directory.mkdir()
    code = '''
import os,sys
from pathlib import Path
from wechat_auto.memory.markdown import MarkdownMemory
with MarkdownMemory._write_lock(Path(sys.argv[1])):
    os._exit(0)
'''
    subprocess.run([sys.executable, '-c', code, str(directory)], check=True, timeout=15)
    with MarkdownMemory._write_lock(directory):
        assert (directory / '.write.lock').exists()
