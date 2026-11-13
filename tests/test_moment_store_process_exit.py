import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from wechat_auto.storage import MomentStore


@pytest.mark.parametrize('journal', ['DELETE', 'WAL'])
@pytest.mark.parametrize('existing', [False, True])
def test_exit_inside_batch_rolls_back_rows_and_versions_then_retry_commits(tmp_path, journal, existing):
    path = tmp_path / 'moments.db'
    original = {'id': 'first', 'username': 'u', 'create_time': 1, 'text': 'original'}
    batch = [{**original, 'text': 'updated'}, {'id': 'second', 'username': 'u', 'create_time': 2}]
    with MomentStore(path) as store:
        if existing:
            store.save([original])
        baseline_versions = store._connection.execute('SELECT count(*) FROM moment_versions').fetchone()[0]
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA journal_mode=' + journal).fetchone()[0] == journal.lower()
    code = '''
import os,sys
from wechat_auto.storage import MomentStore
with MomentStore(sys.argv[1]) as store:
    def exit_mid_batch():
        count=store._connection.execute('SELECT count(*) FROM moments').fetchone()[0]
        os._exit(73 if store._connection.in_transaction and count==2 else 74)
    store._connection.create_function('exit_mid_batch',0,exit_mid_batch)
    store._connection.execute("""CREATE TEMP TRIGGER stop_uncommitted_batch
        AFTER INSERT ON moments WHEN NEW.id='second'
        BEGIN SELECT exit_mid_batch(); END""")
    store.save([{'id':'first','username':'u','create_time':1,'text':'updated'},
                {'id':'second','username':'u','create_time':2}])
'''
    process = subprocess.run([sys.executable, '-c', code, str(path)],
                             capture_output=True, timeout=20, check=False)
    assert process.returncode == 73, process.stderr.decode(errors='replace')
    with MomentStore(path) as store:
        assert store._connection.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert store._connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert store.get('second') is None
        first = store.get('first')
        assert (first is not None) == existing
        if existing:
            assert first['text'] == 'original'
        assert store._connection.execute('SELECT count(*) FROM moment_versions').fetchone()[0] == baseline_versions
        changed, inserted = store.save_with_new_ids(batch)
        assert changed == 2
        assert inserted == ({'second'} if existing else {'first', 'second'})
        assert store.save(batch) == 0
        assert store.get('first')['text'] == 'updated'
        assert store._connection.execute('SELECT count(*) FROM moment_versions').fetchone()[0] == baseline_versions + 2
