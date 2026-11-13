import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from unittest.mock import MagicMock

import pytest

from wechat_auto.backends import collection_sync as module


@pytest.mark.parametrize('stage', ['memory_index', 'output_write'])
def test_abrupt_refresh_exit_preserves_commits_and_explicit_retry_finishes(tmp_path, monkeypatch, stage):
    code = '''
import os, sys
from pathlib import Path
from wechat_auto.backends import collection_sync as module
class Profiles:
    def get_all_contact_profiles(self, **kwargs):
        return [{'wechat_id':'u','nickname':'fixture','raw':{}}]
class Moments:
    def read_all_available(self):
        return [{'id':'post','username':'u','create_time':1}]
module.DatabaseProfileBackend=lambda db: Profiles()
module.DatabaseMomentsBackend=lambda db: Moments()
if sys.argv[2]=='memory_index':
    module.ArchiveIndexer.index_moments=lambda *args,**kwargs: os._exit(73)
else:
    original=Path.write_text
    def stop_at_summary(path,*args,**kwargs):
        if path.name=='summary.json':
            os._exit(73)
        return original(path,*args,**kwargs)
    Path.write_text=stop_at_summary
root=Path(sys.argv[1])
module.refresh(None,profiles_path=root/'profiles.db',moments_path=root/'moments.db',
               memory_path=root/'memory.db',output=root/'runs')
'''
    process = subprocess.run([sys.executable, '-c', code, str(tmp_path), stage],
                             capture_output=True, timeout=20, check=False)
    assert process.returncode == 73, process.stderr.decode(errors='replace')
    receipts = list((tmp_path / 'runs').glob('*/run_status.json'))
    assert len(receipts) == 1
    old_receipt = receipts[0].read_bytes()
    status = json.loads(old_receipt)
    assert status['status'] == 'running' and status['stage'] == stage
    assert status['may_have_partial_writes']
    assert 'moment_archive' in status['completed_stages']
    assert not list((tmp_path / 'runs').glob('*/summary.json'))
    for name in ('profiles.db', 'moments.db', 'memory.db'):
        with closing(sqlite3.connect(tmp_path / name, timeout=0)) as db:
            assert db.execute('PRAGMA quick_check').fetchall() == [('ok',)]
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    profiles, moments = MagicMock(), MagicMock()
    profiles.get_all_contact_profiles.return_value = [{'wechat_id': 'u', 'nickname': 'fixture', 'raw': {}}]
    moments.read_all_available.return_value = [{'id': 'post', 'username': 'u', 'create_time': 1}]
    monkeypatch.setattr(module, 'DatabaseProfileBackend', lambda db: profiles)
    monkeypatch.setattr(module, 'DatabaseMomentsBackend', lambda db: moments)
    kwargs = {'profiles_path': tmp_path / 'profiles.db', 'moments_path': tmp_path / 'moments.db',
              'memory_path': tmp_path / 'memory.db', 'output': tmp_path / 'runs'}
    recovered = module.refresh(None, **kwargs)
    assert recovered['profiles_changed'] == recovered['moments_changed'] == 0
    assert recovered['new_moments_indexed'] == (1 if stage == 'memory_index' else 0)
    receipt = json.loads((tmp_path / 'runs' / recovered['run_id'] / 'run_status.json').read_text(encoding='utf-8'))
    assert receipt['status'] == 'completed'
    repeated = module.refresh(None, **kwargs)
    assert repeated['new_moments_indexed'] == repeated['profile_snapshots_indexed'] == 0
    assert receipts[0].read_bytes() == old_receipt
