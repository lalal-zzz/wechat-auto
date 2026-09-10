"""Read-only local-database backend for WeChat 4.x conversation workflows.

The optional ``wechatauto-replica`` dependency obtains SQLCipher keys by a
read-only scan of the logged-in Weixin process.  This adapter never sends a
network request, injects code, or writes the WeChat database.  Sending stays
outside this backend and is guarded by an explicit confirmation callback.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DatabaseConversationBackend:
    def __init__(self, db=None):
        if db is None:
            try:
                from wechatauto import WeChatDB
            except ImportError as exc:  # pragma: no cover - dependency optional
                raise RuntimeError("Install optional dependency: wechatauto-replica") from exc
            db = WeChatDB()
        self._db = db

    def resolve_chat(self, query: str) -> dict:
        """Resolve a user-provided name to exactly one local conversation."""
        if not query.strip():
            raise ValueError("query must not be empty")
        candidates = list(self._db.search_contact(query))
        exact = [item for item in candidates if query in {
            str(item.get("username", "")), str(item.get("nick_name", "")), str(item.get("remark", "")),
        }]
        matches = exact or candidates
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one local contact match; found {len(matches)}")
        result = dict(matches[0])
        if not result.get("username"):
            raise ValueError("Resolved contact has no local username")
        return result

    def get_context(self, username: str, limit: int = 30) -> list[dict]:
        """Read and order the latest local messages for prompt/context use."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        messages = [dict(item) for item in self._db.get_messages(username, limit=limit)]
        return sorted(messages, key=lambda item: int(item.get("sort_seq", 0)))

    def poll(self, username: str, since_seq: int = 0, limit: int = 200) -> dict:
        """Fetch incremental messages and return an advanced watermark.

        The cursor advances over both inbound and outbound entries so the same
        locally-created message is not repeatedly reconsidered on each poll.
        """
        items = [dict(item) for item in self._db.get_new_messages(username, since_seq, limit)]
        items.sort(key=lambda item: int(item.get("sort_seq", 0)))
        watermark = max([since_seq, *[int(item.get("sort_seq", 0)) for item in items]])
        inbound = [item for item in items if str(item.get("sender_id", "")) != "2"]
        return {"username": username, "messages": inbound, "all_messages": items,
                "watermark": watermark}

    def build_reply_drafts(
        self, username: str, since_seq: int, reply_builder: Callable[[dict, list[dict]], str],
        *, context_limit: int = 30,
    ) -> dict:
        """Read new inbound messages and make drafts; never dispatch them."""
        poll = self.poll(username, since_seq)
        context = self.get_context(username, context_limit)
        drafts = []
        for message in poll["messages"]:
            draft = reply_builder(message, context)
            if not isinstance(draft, str) or not draft.strip():
                continue
            drafts.append({"message": message, "context": context, "draft": draft})
        return {"username": username, "watermark": poll["watermark"], "drafts": drafts,
                "new_message_count": len(poll["messages"])}

    def sync_when_notified(self, username: str, database_path: str, *, source: str = "wechat_db",
                            limit: int = 200) -> dict:
        """Read one DB delta into our offline SQLite only after an external event.

        Pair this with :class:`WindowsDirectoryWatcher`; no background polling
        occurs here.  The local cursor survives restarts, so a repeated file
        notification with no new message is a cheap no-op.
        """
        from wechat_auto.storage import HistoryStore
        with HistoryStore(database_path) as store:
            since = store.get_cursor(source, username)
            update = self.poll(username, since, limit=limit)
            records = []
            for item in update["all_messages"]:
                records.append({
                    "id": f"{username}:{item.get('local_id', item.get('sort_seq'))}", "chat": username,
                    "sender": str(item.get("sender_username", "")), "content": str(item.get("content", "")),
                    "time": str(item.get("create_time", "")),
                    "direction": "outgoing" if str(item.get("sender_id", "")) == "2" else "incoming",
                    "source": source, "raw": {"sort_seq": item.get("sort_seq"), "type": item.get("type")},
                })
            added = store.save_messages(records)
            store.set_cursor(source, username, update["watermark"])
        return {"rows_added": added, "watermark": update["watermark"],
                "new_inbound": len(update["messages"])}

    def initial_import(self, username: str, database_path: str, *, batch_size: int = 200,
                       max_messages: int = 10_000, source: str = "wechat_db") -> dict:
        """One-time bounded import into the offline store, in DB sequence order.

        This reads the source database in batches only for the initial import.
        Future calls should use ``sync_when_notified`` after a file-change
        signal, which starts from the cursor saved here.
        """
        if batch_size <= 0 or max_messages <= 0:
            raise ValueError("batch_size and max_messages must be positive")
        total, added, cursor, batches = 0, 0, 0, 0
        while total < max_messages:
            take = min(batch_size, max_messages - total)
            update = self.poll(username, cursor, limit=take)
            if not update["all_messages"]:
                break
            # Persist through the same idempotent path, but force this batch's
            # cursor rather than consulting a pre-existing sync cursor.
            from wechat_auto.storage import HistoryStore
            with HistoryStore(database_path) as store:
                records = [{
                    "id": f"{username}:{item.get('local_id', item.get('sort_seq'))}", "chat": username,
                    "sender": str(item.get("sender_username", "")), "content": str(item.get("content", "")),
                    "time": str(item.get("create_time", "")),
                    "direction": "outgoing" if str(item.get("sender_id", "")) == "2" else "incoming",
                    "source": source, "raw": {"sort_seq": item.get("sort_seq"), "type": item.get("type")},
                } for item in update["all_messages"]]
                added += store.save_messages(records)
                store.set_cursor(source, username, update["watermark"])
            batches += 1
            total += len(update["all_messages"])
            if update["watermark"] <= cursor or len(update["all_messages"]) < take:
                cursor = update["watermark"]
                break
            cursor = update["watermark"]
        return {"messages_read": total, "rows_added": added, "batches": batches,
                "watermark": cursor, "complete": total < max_messages}

    @staticmethod
    def dispatch_draft(draft: str, send: Callable[[str], Any], *, confirm: bool = False) -> Any:
        """Dispatch only after a caller intentionally confirms the exact draft."""
        if not confirm:
            raise PermissionError("Reply dispatch requires confirm=True")
        if not draft.strip():
            raise ValueError("draft must not be empty")
        return send(draft)
