"""Recovery preserves candidates byte-for-byte and never promotes unindexed text."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wechat_auto.memory import MarkdownMemory, MemoryStore


def prepare(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    memory = MarkdownMemory(tmp_path / 'memory', store)
    memory.write('person', 'p1', '# Original\ncomplete', input_fingerprint='first')
    directory = memory._directory('person', 'p1')
    candidate = directory / 'versions/v000002.md'
    candidate.write_bytes(b'# Candidate\nnot committed\n')
    (directory / 'current.md').write_bytes(candidate.read_bytes())
    return store, memory, directory, candidate


def test_recovery_preserves_binary_pointer_and_partial_temp_files(tmp_path):
    store, memory, directory, candidate = prepare(tmp_path)
    try:
        (directory / 'current.md').write_bytes(b'\xff\x00synthetic damage')
        temporary = directory / 'versions/v000003.md.partial.tmp'
        temporary.write_bytes(b'partial candidate')
        result = memory.recover_publication('person', 'p1')
        work = Path(result['work_dir'])
        assert (work / 'current.md').read_bytes() == b'\xff\x00synthetic damage'
        assert (work / 'versions/v000002.md').read_bytes() == b'# Candidate\nnot committed\n'
        assert (work / 'versions/v000003.md.partial.tmp').read_bytes() == b'partial candidate'
        assert (directory / 'current.md').read_text(encoding='utf-8') == memory.read_current('person', 'p1')
        receipt = json.loads((work / 'recovery.json').read_text(encoding='utf-8'))
        assert receipt['status'] == 'recovered' and receipt['promoted'] is False
        assert store.current_version('person', 'p1')['version'] == 1
        assert not candidate.exists()
    finally:
        store.close()


@pytest.mark.parametrize('failure', ['move', 'restore_pointer'])
def test_recovery_failure_restores_pre_recovery_files(tmp_path, failure):
    store, memory, directory, candidate = prepare(tmp_path)
    pointer = directory / 'current.md'
    before = {path: path.read_bytes() for path in (pointer, candidate)}
    original_write = memory._atomic_write
    from os import replace

    def move(source, destination):
        if failure == 'move' and Path(source) == candidate:
            raise OSError('synthetic move failure')
        replace(source, destination)

    def write(path, content):
        if failure == 'restore_pointer' and path == pointer:
            raise OSError('synthetic restore failure')
        original_write(path, content)

    try:
        with (
            patch('wechat_auto.memory.markdown.os.replace', side_effect=move),
            patch.object(memory, '_atomic_write', side_effect=write),
            pytest.raises(OSError, match='synthetic'),
        ):
            memory.recover_publication('person', 'p1')
        assert all(path.read_bytes() == payload for path, payload in before.items())
        assert store.current_version('person', 'p1')['version'] == 1
        assert '# Original' in memory.read_current('person', 'p1')
        for receipt in (tmp_path / 'work/analysis').glob('*/recovery.json'):
            assert json.loads(receipt.read_text(encoding='utf-8'))['status'] != 'recovered'
    finally:
        store.close()


def test_damaged_indexed_version_stops_without_promoting_candidate(tmp_path):
    store, memory, directory, candidate = prepare(tmp_path)
    try:
        (directory / 'versions/v000001.md').write_text('damaged indexed body', encoding='utf-8')
        with pytest.raises(RuntimeError, match='integrity validation'):
            memory.recover_publication('person', 'p1')
        assert candidate.read_bytes() == b'# Candidate\nnot committed\n'
        assert not (tmp_path / 'work').exists()
    finally:
        store.close()


def test_recovery_does_not_interfere_with_an_active_target_lock(tmp_path):
    store, memory, directory, candidate = prepare(tmp_path)
    try:
        with memory._write_lock(directory), pytest.raises(RuntimeError, match='already being written'):
            memory.recover_publication('person', 'p1')
        assert candidate.read_bytes() == b'# Candidate\nnot committed\n'
        assert not (tmp_path / 'work').exists()
    finally:
        store.close()
