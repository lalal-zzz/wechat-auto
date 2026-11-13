"""Shared lifetime for injected databases and owned DPAPI working copies."""

from contextlib import ExitStack
from weakref import finalize

from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db


class DatabaseResourceOwner:
    def __init__(self, db, *, secret_dir, database_names, include_message_family=False):
        resources = ExitStack()
        try:
            self._database = db if db is not None else resources.enter_context(open_dpapi_wechat_db(
                secret_dir, database_names=database_names, include_message_family=include_message_family))
        except BaseException:
            resources.close()
            raise
        self._closed = False
        self._cleanup = finalize(self, resources.close)

    def _ensure_open(self):
        if getattr(self, '_closed', False):
            raise RuntimeError('Database backend is closed')

    @property
    def _db(self):
        self._ensure_open()
        return self._database

    def close(self):
        self._closed = True
        self._cleanup()

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *_exc):
        self.close()
