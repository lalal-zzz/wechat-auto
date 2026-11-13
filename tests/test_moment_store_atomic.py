import sqlite3

import pytest

from wechat_auto.storage import MomentStore


def test_moment_id_cannot_overwrite_another_authors_content(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store.save([{'id': 'same', 'username': 'wxid_first', 'text': 'original'}])
        before = store.get('same')
        with pytest.raises(ValueError, match='author'):
            store.save([{'id': 'same', 'username': 'wxid_other', 'text': 'other'}])
        assert store.get('same') == before


def test_conflicting_author_within_batch_does_not_write_either_row(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        with pytest.raises(ValueError, match='author'):
            store.save([{'id': 'same', 'username': 'wxid_first'}, {'id': 'same', 'username': 'wxid_other'}])
        assert store.get('same') is None


def test_sql_fault_rolls_back_partial_batch_and_later_save_cannot_commit_it(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store._connection.execute("""CREATE TRIGGER fail_second BEFORE INSERT ON moments
            WHEN NEW.id='second' BEGIN SELECT RAISE(ABORT,'synthetic write fault'); END""")
        store._connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            store.save([{'id': 'first', 'username': 'wxid_test'}, {'id': 'second', 'username': 'wxid_test'}])
        assert store.get('first') is None
        store.save([{'id': 'later', 'username': 'wxid_test'}])
        assert store.get('first') is None


def test_known_creation_time_cannot_be_silently_replaced(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store.save([{'id': 'same', 'username': 'wxid_test', 'create_time': 100}])
        with pytest.raises(ValueError, match='creation time'):
            store.save([{'id': 'same', 'username': 'wxid_test', 'create_time': 200}])
        assert store.get('same')['create_time'] == 100


def test_unknown_creation_time_can_be_enriched(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store.save([{'id': 'same', 'username': 'wxid_test'}])
        assert store.save([{'id': 'same', 'username': 'wxid_test', 'create_time': 100}]) == 1
        assert store.get('same')['create_time'] == 100


def test_identical_moment_save_is_noop_but_same_author_edits_are_saved(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        record = {'id': 'same', 'username': 'wxid_test', 'text': 'original'}
        assert store.save([record]) == 1
        assert store.save([record]) == 0
        assert store.save([{**record, 'text': 'updated'}]) == 1
        assert store.get('same')['text'] == 'updated'

@pytest.mark.parametrize('record', [
    {'id': True, 'username': 'wxid_test'}, {'id': -1, 'username': 'wxid_test'},
    {'id': 'test', 'username': 123}, {'id': 'test', 'username': '  '},
    {'id': 'test', 'username': 'test@chatroom'},
    {'id': 'test', 'username': 'wxid_test', 'create_time': True},
    {'id': 'test', 'username': 'wxid_test', 'create_time': 1.5},
])
def test_invalid_moment_identity_or_time_is_not_coerced_into_a_fact(tmp_path, record):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        with pytest.raises((ValueError, TypeError)):
            store.save([record])
        assert store._connection.execute('SELECT COUNT(*) FROM moments').fetchone()[0] == 0


def test_late_author_conflict_rolls_back_an_earlier_existing_row_update(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'original'}])
        original = store.get('same')
        with pytest.raises(ValueError, match='author'):
            store.save([{'id': 'same', 'username': 'wxid_test', 'text': 'updated'},
                        {'id': 'same', 'username': 'wxid_other', 'text': 'other'}])
        assert store.get('same') == original


def test_concurrent_conflicting_authors_do_not_mix_owner_and_content(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path):
        pass
    barrier = Barrier(2)
    def write(author):
        with MomentStore(path) as store:
            barrier.wait(timeout=5)
            try:
                store.save([{'id': 'same', 'username': author, 'text': author}])
                return author
            except ValueError:
                return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, name) for name in ('wxid_first', 'wxid_test_second')]
        winners = [result for future in futures if (result := future.result(timeout=10))]
    assert len(winners) == 1
    with MomentStore(path) as store:
        assert store.get('same')['username'] == store.get('same')['text'] == winners[0]
        raw = json.loads(store._connection.execute('SELECT raw_json FROM moments').fetchone()[0])
        assert raw['username'] == winners[0]


def test_dictionary_key_order_does_not_create_a_false_update(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        first = {'id': 'same', 'username': 'wxid_test', 'comments': [{'username': 'wxid_other', 'text': 'synthetic'}]}
        second = {'username': 'wxid_test', 'id': 'same', 'comments': [{'text': 'synthetic', 'username': 'wxid_other'}]}
        assert store.save([first]) == 1
        assert store.save([second]) == 0
