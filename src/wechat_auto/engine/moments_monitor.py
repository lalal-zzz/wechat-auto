"""Event-triggered local Moments detection and interaction-policy planning."""
from __future__ import annotations

from collections.abc import Iterable


class MomentsMonitor:
    """Turn an ``sns.db`` change into offline storage and safe action requests.

    Call ``bootstrap`` once (it stores a baseline without treating existing
    feeds as new).  Thereafter call ``scan_once`` only after a directory-change
    event from ``WindowsDirectoryWatcher``.  It never polls on its own and
    never clicks Like; UI execution remains a separately confirmed action.
    """
    def __init__(self, backend, database_path: str, *, auto_like_usernames: Iterable[str] = ()):
        self.backend = backend
        self.database_path = database_path
        self.auto_like_usernames = {str(item) for item in auto_like_usernames}

    def bootstrap(self, limit: int = 100) -> dict:
        from wechat_auto.storage import MomentStore
        feeds = self.backend.read_latest(limit=limit)
        with MomentStore(self.database_path) as store:
            added = store.save(feeds)
        return {"baseline": True, "feeds_seen": len(feeds), "rows_saved": added}

    def scan_once(self, limit: int = 100) -> dict:
        from wechat_auto.storage import MomentStore
        feeds = self.backend.read_latest(limit=limit)
        ids = [str(feed.get("id") or feed.get("tid") or "") for feed in feeds]
        with MomentStore(self.database_path) as store:
            known = store.existing_ids(ids)
            new_feeds = [feed for feed in feeds if str(feed.get("id") or feed.get("tid") or "") not in known]
            saved = store.save(new_feeds)
        actions = []
        for feed in new_feeds:
            username = str(feed.get("username", ""))
            actions.append({
                "kind": "like_moment", "moment_id": str(feed.get("id") or feed.get("tid") or ""),
                "username": username, "author": str(feed.get("nickname", "")),
                "auto_eligible": username in self.auto_like_usernames,
                "requires_foreground_verification": True,
                "requires_confirmation": username not in self.auto_like_usernames,
            })
        return {"new_feeds": new_feeds, "rows_saved": saved, "actions": actions}
