"""Force two independent connections to read the same token before claiming it."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from wechat_auto.memory.store import MemoryStore


class _ReadBarrier:
    def __init__(self, connection, barrier, prefix):
        self.connection = connection
        self.barrier = barrier
        self.prefix = prefix

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, parameters=()):
        cursor = self.connection.execute(sql, parameters)
        if not sql.startswith(self.prefix):
            return cursor
        row = cursor.fetchone()
        cursor.close()
        self.barrier.wait(timeout=10)

        class Result:
            def fetchone(self):
                return row

        return Result()


@pytest.mark.parametrize('kind', ['reply', 'action'])
@pytest.mark.parametrize('operation', ['confirm', 'consume'])
def test_confirmation_can_be_claimed_only_once_across_connections(tmp_path, kind, operation):
    path = tmp_path / 'memory.sqlite3'
    with MemoryStore(path) as first, MemoryStore(path) as second:
        if kind == 'reply':
            conversation = first.ensure_conversation('wxid_test_target', conversation_type='direct')
            target = first.create_reply_draft(conversation, 'trigger', 'exact text', 'context')
            token = first.confirm_reply_draft(target) if operation == 'consume' else None

            def call(store):
                if operation == 'confirm':
                    return store.confirm_reply_draft(target)
                return store.consume_confirmation(token, conversation, 'exact text')
        else:
            target = first.create_pending_action('set_remark', 'wxid_test_target', {'value': 'test'})
            token = first.confirm_pending_action(target) if operation == 'consume' else None

            def call(store):
                if operation == 'confirm':
                    return store.confirm_pending_action(target)
                return store.consume_pending_action(target, token)

        barrier = Barrier(2)
        prefix = 'SELECT status,expires_at' if operation == 'confirm' else 'SELECT *'
        for store in (first, second):
            store._connection = _ReadBarrier(store._connection, barrier, prefix)

        def attempt(store):
            try:
                call(store)
                return 'claimed'
            except PermissionError:
                return 'rejected'

        with ThreadPoolExecutor(max_workers=2) as workers:
            assert sorted(workers.map(attempt, (first, second))) == ['claimed', 'rejected']
