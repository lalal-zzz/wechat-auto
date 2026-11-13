"""Opt-in atomic batches across existing store methods with local commits."""

import sqlite3
from contextlib import contextmanager
from threading import RLock

from wechat_auto.memory.observation_time import observation_first, observation_last


class MemoryConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mutex = RLock()
        self._batch = False
        self._rollback_only = False
        self.create_function("wa_observed_first", 2, observation_first, deterministic=True)
        self.create_function("wa_observed_last", 2, observation_last, deterministic=True)

    def execute(self, *args, **kwargs):
        with self._mutex:
            return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._mutex:
            return super().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._mutex:
            if self._batch:
                raise RuntimeError('Schema scripts cannot run inside an atomic batch')
            return super().executescript(*args, **kwargs)

    def commit(self):
        with self._mutex:
            if not self._batch:
                super().commit()

    def rollback(self):
        with self._mutex:
            if self._batch:
                self._rollback_only = True
            else:
                super().rollback()

    def close(self):
        with self._mutex:
            if self._batch:
                raise RuntimeError('Cannot close a connection during an atomic batch')
            super().close()

    def __enter__(self):
        self._mutex.acquire()
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if self._batch:
                if kind is not None:
                    self._rollback_only = True
                return False
            return super().__exit__(kind, value, traceback)
        finally:
            self._mutex.release()

    @contextmanager
    def atomic(self):
        with self._mutex:
            if self._batch or self.in_transaction:
                raise RuntimeError('Atomic batch requires an idle connection')
            super().execute('BEGIN IMMEDIATE')
            self._batch, self._rollback_only = True, False
            try:
                yield self
                if self._rollback_only:
                    raise RuntimeError('Atomic batch was marked for rollback')
                self._commit_atomic()
            except BaseException:
                super().rollback()
                raise
            finally:
                self._batch = False

    def _commit_atomic(self):
        super().commit()
