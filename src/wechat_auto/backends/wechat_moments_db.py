"""Read and archive Moments using the optional local-database backend."""
from __future__ import annotations

from wechat_auto.backends.database_resource import DatabaseResourceOwner
from wechat_auto.backends.replica_import import replica_module


class MomentMediaDownloadError(RuntimeError):
    """Safe failure details without the private media URL or dynamic content."""

    def __init__(self, expected: int, saved: list[str]):
        self.expected = expected
        self.saved_paths = list(saved)
        self.failure_code = 'moment_media_download_incomplete'
        super().__init__(f'{self.failure_code}:{len(saved)}/{expected}')


class DatabaseMomentsBackend(DatabaseResourceOwner):
    def __init__(self, db=None, *, secret_dir="data/.secrets"):
        super().__init__(db, secret_dir=secret_dir, database_names=('contact.db', 'sns.db'))
        try:
            self._moments = replica_module().MomentDB(self._db)
        except BaseException:
            self.close()
            raise

    def resolve_user(self, query: str) -> dict:
        from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend
        return DatabaseConversationBackend(self._db).resolve_chat(query)

    def read_latest(self, limit: int = 20, username: str | None = None) -> list[dict]:
        self._ensure_open()
        if limit <= 0:
            raise ValueError("limit must be positive")
        return [dict(feed) for feed in self._moments.get_moments(limit=limit, username=username)]

    def read_all_available(self, username: str | None = None) -> list[dict]:
        """Read all locally available rows, not an entire remote timeline."""
        self._ensure_open()
        return [dict(feed) for feed in self._moments.get_moments(limit=0, username=username)]

    def archive_latest(self, database_path: str, *, limit: int = 20, username: str | None = None) -> dict:
        from wechat_auto.storage import MomentStore
        feeds = self.read_latest(limit, username)
        with MomentStore(database_path) as store:
            added = store.save(feeds)
        return {"feeds_read": len(feeds), "rows_saved": added, "database": database_path,
                "username": username, "media_downloaded": False}

    def archive_user(self, query: str, database_path: str, *, limit: int = 20) -> dict:
        user = self.resolve_user(query)
        result = self.archive_latest(database_path, limit=limit, username=user["username"])
        result["resolved"] = True
        return result

    @staticmethod
    def plan_media_download(feed: dict) -> dict:
        """Describe a Moment's media without downloading it."""
        media = list(feed.get("images", [])) + list(feed.get("videos", []))
        return {"moment_id": str(feed.get("id") or feed.get("tid") or ""),
                "author": str(feed.get("nickname", "")), "image_count": len(feed.get("images", [])),
                "video_count": len(feed.get("videos", [])), "media": media,
                "requires_confirmation": bool(media)}

    def download_media(self, feed: dict, directory: str, *, confirm: bool = False) -> list[str]:
        """Download an explicitly approved Moment's media.

        The source may be local cache or a remote URL.  A caller must present
        ``plan_media_download`` to the user and pass ``confirm=True`` only
        after approval; this method never silently starts network traffic.
        """
        self._ensure_open()
        if not confirm:
            raise PermissionError("Moment media download requires confirm=True after user approval")
        expected = len(feed.get('images') or []) + len(feed.get('videos') or [])
        if not expected:
            raise ValueError('Moment has no media to download')
        saved = list(self._moments.download_moment_media(feed, save_dir=directory))
        if len(saved) != expected:
            # The optional dependency silently skips request failures. Do not
            # let [] or a partial result masquerade as a completed download.
            raise MomentMediaDownloadError(expected, saved)
        return saved
