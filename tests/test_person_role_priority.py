from itertools import permutations

import pytest

from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.memory.store import MemoryStore
from wechat_auto.storage import ProfileStore


@pytest.mark.parametrize('order', list(permutations(('group_member', 'contact', 'self'))))
def test_stable_person_role_and_name_do_not_depend_on_discovery_order(tmp_path, order):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        ids = [memory.ensure_person('wxid_same', person_type=role, display_name=role+'-name', mark_active=False)
               for role in order]
        assert len(set(ids)) == 1
        row = memory._connection.execute('SELECT person_type,display_name,status FROM people').fetchone()
        assert tuple(row) == ('self', 'self-name', 'unknown')


def test_group_discovered_person_can_become_contact_without_new_person_id(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_same', person_type='group_member', display_name='group-name', mark_active=False)
        assert memory.ensure_person('wxid_same', person_type='contact', display_name='contact-name', mark_active=False) == person
        assert tuple(memory._connection.execute('SELECT person_type,display_name FROM people').fetchone()) == ('contact', 'contact-name')


def test_same_role_observation_can_update_display_name(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_same', person_type='contact', display_name='before')
        assert memory.ensure_person('wxid_same', person_type='contact', display_name='after') == person
        assert memory._connection.execute('SELECT display_name FROM people').fetchone()[0] == 'after'


def test_self_profile_index_promotes_group_discovered_identity(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_same', 'group_id': 'test@chatroom', 'nickname': 'group-global'}, profile_type='group_member')
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        indexer = ArchiveIndexer(memory)
        indexer.index_profiles(path)
        person = memory._connection.execute('SELECT person_id FROM people').fetchone()[0]
        with ProfileStore(path) as profiles:
            profiles.save({'wechat_id': 'wxid_same', 'nickname': 'self-current', 'display_name': 'self-current'}, profile_type='self')
        indexer.index_profiles(path)
        row = memory._connection.execute('SELECT person_id,person_type,display_name FROM people').fetchone()
        assert tuple(row) == (person, 'self', 'self-current')


def test_unsupported_person_kind_is_rejected_before_writes(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        with pytest.raises(ValueError, match='person_type'):
            memory.ensure_person('wxid_same', person_type='unsupported')
        assert memory._connection.execute('SELECT COUNT(*) FROM people').fetchone()[0] == 0


def test_unknown_existing_person_kind_is_preserved_for_review(tmp_path):
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        person = memory.ensure_person('wxid_same', person_type='group_member', display_name='legacy')
        memory._connection.execute("UPDATE people SET person_type='legacy-unknown' WHERE person_id=?", (person,))
        memory._connection.commit()
        with pytest.raises(ValueError, match='requires review'):
            memory.ensure_person('wxid_same', person_type='contact', display_name='new')
        assert tuple(memory._connection.execute('SELECT person_type,display_name FROM people').fetchone()) == ('legacy-unknown', 'legacy')


def test_concurrent_role_observations_cannot_demote_self(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / 'memory.sqlite3'
    with MemoryStore(path) as memory:
        person = memory.ensure_person('wxid_same', person_type='group_member', mark_active=False)
    barrier = Barrier(2)
    def observe(role):
        with MemoryStore(path) as memory:
            barrier.wait(timeout=5)
            return memory.ensure_person('wxid_same', person_type=role, display_name=role+'-name', mark_active=False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(observe, role) for role in ('contact', 'self')]
        assert [future.result(timeout=10) for future in futures] == [person, person]
    with MemoryStore(path) as memory:
        assert tuple(memory._connection.execute('SELECT person_type,display_name FROM people').fetchone()) == ('self', 'self-name')
