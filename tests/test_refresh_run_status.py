import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wechat_auto.backends import collection_sync as module
from wechat_auto.storage import MomentStore


@pytest.mark.parametrize('failure', ['source_read', 'memory_index', 'output_write'])
def test_refresh_failure_receipt_is_redacted_and_retry_completes(tmp_path, monkeypatch, failure):
    profiles = MagicMock()
    profiles.get_all_contact_profiles.return_value = [{'wechat_id': 'u', 'nickname': 'fixture', 'raw': {}}]
    moments = MagicMock()
    moments.read_all_available.return_value = [{'id': 'post', 'username': 'u', 'create_time': 1}]
    monkeypatch.setattr(module, 'DatabaseProfileBackend', lambda db: profiles)
    monkeypatch.setattr(module, 'DatabaseMomentsBackend', lambda db: moments)
    original = module.ArchiveIndexer.index_moments
    original_write = Path.write_text
    problem = RuntimeError('private-message-must-not-appear-in-receipt')
    if failure == 'source_read':
        moments.read_all_available.side_effect = problem
    elif failure == 'memory_index':
        monkeypatch.setattr(module.ArchiveIndexer, 'index_moments', MagicMock(side_effect=problem))
    else:
        def fail_summary(path, *args, **kwargs):
            if path.name == 'summary.json':
                raise problem
            return original_write(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'write_text', fail_summary)
    kwargs = {'profiles_path': tmp_path / 'profiles.db', 'moments_path': tmp_path / 'moments.db',
              'memory_path': tmp_path / 'memory.db', 'output': tmp_path / 'runs'}
    with pytest.raises(RuntimeError) as caught:
        module.refresh(None, **kwargs)
    assert caught.value is problem
    receipts = list((tmp_path / 'runs').glob('*/run_status.json'))
    assert len(receipts) == 1
    text = receipts[0].read_text(encoding='utf-8')
    receipt = json.loads(text)
    assert 'private-message' not in text
    assert receipt['status'] == 'failed' and receipt['stage'] == failure
    assert receipt['error_type'] == 'RuntimeError'
    assert receipt['may_have_partial_writes'] == (failure != 'source_read')
    if failure != 'source_read':
        assert 'moment_archive' in receipt['completed_stages']
        with MomentStore(kwargs['moments_path']) as store:
            assert store.get('post') is not None
    moments.read_all_available.side_effect = None
    monkeypatch.setattr(module.ArchiveIndexer, 'index_moments', original)
    monkeypatch.setattr(Path, 'write_text', original_write)
    result = module.refresh(None, **kwargs)
    success = json.loads((tmp_path / 'runs' / result['run_id'] / 'run_status.json').read_text(encoding='utf-8'))
    assert success['status'] == 'completed'
    assert 'memory_index' in success['completed_stages']
    assert 'output_write' in success['completed_stages']
    assert json.loads(receipts[0].read_text(encoding='utf-8'))['status'] == 'failed'
