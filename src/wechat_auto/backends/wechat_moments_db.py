"""Read and archive Moments using the optional local-database backend."""
from __future__ import annotations


class DatabaseMomentsBackend:
    def __init__(self, db=None):
        if db is None:
            from wechatauto import WeChatDB
            db = WeChatDB()
        from wechatauto import MomentDB
        self._db = db
        self._moments = MomentDB(db)

    def resolve_user(self, query: str) -> dict:
        from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend
        return DatabaseConversationBackend(self._db).resolve_chat(query)

    def read_latest(self, limit: int = 20, username: str | None = None) -> list[dict]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return [dict(feed) for feed in self._moments.get_moments(limit=limit, username=username)]

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
        if not confirm:
            raise PermissionError("Moment media download requires confirm=True after user approval")
        return list(self._moments.download_moment_media(feed, save_dir=directory))
