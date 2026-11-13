import pytest

from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.memory.store import MemoryStore
from wechat_auto.storage import MomentStore


@pytest.mark.parametrize('entity', ['person', 'conversation'])
def test_out_of_order_observations_extend_bounds_without_regressing_last_seen(tmp_path, entity):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        ensure = memory.ensure_person if entity == 'person' else lambda key, **kwargs: memory.ensure_conversation(key, conversation_type='direct', **kwargs)
        ident = ensure('wxid_test', seen_at='2026-10-24T02:00:00Z', mark_active=False)
        ensure('wxid_test', seen_at='2026-10-24T00:00:00Z', mark_active=False)
        table, column = ('people', 'person_id') if entity == 'person' else ('conversations', 'conversation_id')
        row = memory._connection.execute(f'SELECT first_seen_at,last_seen_at FROM {table} WHERE {column}=?', (ident,)).fetchone()
        assert tuple(row) == ('2026-10-24T00:00:00Z', '2026-10-24T02:00:00Z')
        if entity == 'person':
            row = memory._connection.execute('SELECT first_seen_at,last_seen_at FROM person_identities').fetchone()
            assert tuple(row) == ('2026-10-24T00:00:00Z', '2026-10-24T02:00:00Z')


def test_observation_order_uses_offsets_and_does_not_guess_unknown_time(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_test', seen_at='2026-10-24T09:00:00+08:00')
        memory.ensure_person('wxid_test', seen_at='2026-10-24T02:00:00Z')
        memory.ensure_person('wxid_test', seen_at='unknown-time')
        row = memory._connection.execute('SELECT last_seen_at FROM people WHERE person_id=?', (person,)).fetchone()
        assert row[0] == '2026-10-24T02:00:00Z'


def test_old_moment_nickname_does_not_replace_contact_display_name(tmp_path):
    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as moments:
        moments.save([{'id': 'old-post', 'username': 'wxid_test', 'nickname': 'old-post-name'}])
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_test', display_name='preferred-contact-name')
        ArchiveIndexer(memory).index_moments(path)
        assert memory._connection.execute('SELECT display_name FROM people WHERE person_id=?', (person,)).fetchone()[0] == 'preferred-contact-name'


def test_epoch_seconds_and_milliseconds_compare_with_zoned_timestamps(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_test', seen_at='2026-01-02T00:00:00Z')
        memory.ensure_person('wxid_test', seen_at='1767225600')
        memory.ensure_person('wxid_test', seen_at='1767398400000')
        row = memory._connection.execute('SELECT first_seen_at,last_seen_at FROM people WHERE person_id=?', (person,)).fetchone()
        assert tuple(row) == ('1767225600', '1767398400000')


def test_unzoned_time_does_not_fabricate_an_absolute_order(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_test', seen_at='2026-01-02T00:00:00Z')
        for value in ('2030-01-01 00:00:00', '2010-01-01 00:00:00', 'not-a-time'):
            memory.ensure_person('wxid_test', seen_at=value)
        row = memory._connection.execute('SELECT first_seen_at,last_seen_at FROM people WHERE person_id=?', (person,)).fetchone()
        assert tuple(row) == ('2026-01-02T00:00:00Z',) * 2


def test_equivalent_instants_keep_original_timestamp_representation(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_test', seen_at='2026-10-24T09:00:00+08:00')
        memory.ensure_person('wxid_test', seen_at='2026-10-24T01:00:00Z')
        row = memory._connection.execute('SELECT first_seen_at,last_seen_at FROM people WHERE person_id=?', (person,)).fetchone()
        assert tuple(row) == ('2026-10-24T09:00:00+08:00',) * 2


def test_concurrent_observations_preserve_minimum_and_maximum(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / 'memory.sqlite3'
    with MemoryStore(path) as memory:
        person = memory.ensure_person('wxid_test', seen_at='2026-10-24T01:00:00Z')
    barrier = Barrier(2)
    def observe(value):
        with MemoryStore(path) as memory:
            barrier.wait(timeout=5)
            return memory.ensure_person('wxid_test', seen_at=value, mark_active=False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(observe, value) for value in ('2026-10-24T00:00:00Z', '2026-10-24T02:00:00Z')]
        assert [future.result(timeout=10) for future in futures] == [person, person]
    with MemoryStore(path) as memory:
        row = memory._connection.execute('SELECT first_seen_at,last_seen_at FROM people').fetchone()
        assert tuple(row) == ('2026-10-24T00:00:00Z', '2026-10-24T02:00:00Z')


def test_moment_historical_alias_is_scoped_and_rolls_back_with_index(tmp_path):
    import sqlite3
    path = tmp_path / 'moments.sqlite3'
    with MomentStore(path) as moments:
        moments.save([{'id': 'post', 'username': 'wxid_test', 'nickname': 'post-name'}])
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        memory._connection.execute("""CREATE TRIGGER fail_dirty BEFORE INSERT ON dirty_nodes
            BEGIN SELECT RAISE(ABORT,'synthetic dirty failure'); END""")
        memory._connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            ArchiveIndexer(memory).index_moments(path)
        assert memory._connection.execute('SELECT COUNT(*) FROM person_aliases').fetchone()[0] == 0
        memory._connection.execute('DROP TRIGGER fail_dirty')
        memory._connection.commit()
        ArchiveIndexer(memory).index_moments(path)
        row = memory._connection.execute('SELECT alias_value,context_id FROM person_aliases').fetchone()
        assert row[0] == 'post-name' and row[1].startswith('moment:')
