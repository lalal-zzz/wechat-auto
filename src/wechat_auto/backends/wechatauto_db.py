"""Read-only local-database backend for WeChat 4.x conversation workflows.

The optional ``wechatauto-replica`` dependency obtains SQLCipher keys by a
read-only scan of the logged-in Weixin process.  This adapter never sends a
network request, injects code, or writes the WeChat database.  Sending stays
outside this backend and is guarded by an explicit confirmation callback.
"""
from __future__ import annotations

import mimetypes
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
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

    def resolve_contact_username(self, username: str) -> dict:
        """Resolve exactly one contact by the stable internal username/wxid."""
        if not username.strip() or username.endswith("@chatroom"):
            raise ValueError("A non-group WeChat username is required")
        candidates = [dict(item) for item in self._db.search_contact(username)]
        matches = [item for item in candidates
                   if str(item.get("username") or "") == username]
        if len(matches) != 1:
            raise ValueError(f"Expected one contact for stable username; found {len(matches)}")
        contact = matches[0]
        contact["ui_query"] = str(
            contact.get("remark") or contact.get("nick_name")
            or contact.get("alias") or username
        )
        contact["visible_wechat_id"] = str(contact.get("alias") or "")
        return contact

    def plan_contact_action(self, username: str, action: str, *, value: str = "") -> dict:
        """Create a deterministic, non-executing plan bound to one stable identity."""
        from wechat_auto.actions.semantics import ContactActionPlan

        if action not in {"set_remark", "delete_contact", "open_contact"}:
            raise ValueError(f"Unsupported contact action: {action}")
        if action == "set_remark" and not value.strip():
            raise ValueError("set_remark requires a non-empty value")
        contact = self.resolve_contact_username(username)
        return ContactActionPlan(
            username=username,
            action=action,
            ui_query=contact["ui_query"],
            visible_wechat_id=contact["visible_wechat_id"],
            value=value,
            requires_confirmation=action in {"set_remark", "delete_contact"},
        ).to_dict()

    def plan_search(self, query: str, *, target_kind: str,
                    scene: str = "main", expected_username: str | None = None,
                    allow_partial: bool = False) -> dict:
        """Build a no-OCR search plan from local identity data only."""
        from wechat_auto.backends.search_plan import build_search_plan
        candidates = [dict(item) for item in self._db.search_contact(query)]
        if expected_username:
            for item in candidates:
                if str(item.get("username") or "") == expected_username:
                    item["_known_target_kind"] = target_kind
        return build_search_plan(candidates, query, target_kind=target_kind,
                                 scene=scene, allow_partial=allow_partial).to_dict()

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
                            limit: int = 200, voice_model_path=None, voice_device: str = "auto") -> dict:
        """Read one DB delta into our offline SQLite only after an external event.

        Pair this with :class:`WindowsDirectoryWatcher`; no background polling
        occurs here.  The local cursor survives restarts, so a repeated file
        notification with no new message is a cheap no-op.
        """
        from wechat_auto.storage import HistoryStore
        with HistoryStore(database_path, voice_model_path=voice_model_path, voice_device=voice_device) as store:
            since = store.get_cursor(source, username)
            update = self.poll(username, since, limit=limit)
            from wechat_auto.storage import make_message_id
            records = []
            for item in update["all_messages"]:
                records.append({
                    "id": make_message_id(username, item.get("local_id"), item.get("sort_seq"),
                                          item.get("server_id"), item.get("type")), "chat": username,
                    "sender": str(item.get("sender_username", "")), "content": str(item.get("content", "")),
                    "time": str(item.get("create_time", "")),
                    "direction": "outgoing" if str(item.get("sender_id", "")) == "2" else "incoming",
                    "source": source, "raw": {"local_id": item.get("local_id"),
                                                 "sort_seq": item.get("sort_seq"),
                                                 "server_id": item.get("server_id"),
                                                 "type": item.get("type")},
                    "media": self._message_media(item),
                })
            added = store.save_messages(records)
            voice_processing = store.last_voice_processing
            store.set_cursor(source, username, update["watermark"])
        return {"rows_added": added, "watermark": update["watermark"],
                "new_inbound": len(update["messages"]), "voice_processing": voice_processing}

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
            from wechat_auto.storage import HistoryStore, make_message_id
            with HistoryStore(database_path) as store:
                records = [{
                    "id": make_message_id(username, item.get("local_id"), item.get("sort_seq"),
                                          item.get("server_id"), item.get("type")), "chat": username,
                    "sender": str(item.get("sender_username", "")), "content": str(item.get("content", "")),
                    "time": str(item.get("create_time", "")),
                    "direction": "outgoing" if str(item.get("sender_id", "")) == "2" else "incoming",
                    "source": source, "raw": {"local_id": item.get("local_id"),
                                                 "sort_seq": item.get("sort_seq"),
                                                 "server_id": item.get("server_id"),
                                                 "type": item.get("type")},
                    "media": self._message_media(item),
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

    def archive_all_history(self, database_path: str, *, batch_size: int = 500,
                            source: str = "wechat_db",
                            include_images: bool = True, voice_model_path=None, voice_device: str = "auto",
                            progress: Callable[[int, int, str], Any] | None = None) -> dict:
        """Persist every message in every local chat, including local media.

        This is the explicit one-time/full archive path.  It enumerates chats
        from the read-only adapter, reads all message pages, and asks the
        adapter's local ``MediaDownloader`` to materialize supported media into
        a temporary directory before storing the bytes in ``HistoryStore``.
        No network/original-media download method is used.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        from wechat_auto.storage import HistoryStore, make_message_id
        try:
            from wechatauto import MediaDownloader
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install optional dependency: wechatauto-replica") from exc
        total_messages = total_media = rows_added = media_errors = 0
        with tempfile.TemporaryDirectory(prefix="wechat-auto-media-") as media_dir:
            downloader = MediaDownloader(self._db, save_dir=media_dir)
            export_path = str(Path(media_dir) / "messages.sqlite3")
            self._db.export_history(export_path, fmt="sqlite")
            exported = sqlite3.connect(export_path)
            exported.row_factory = sqlite3.Row
            chats = [dict(row) for row in exported.execute(
                "SELECT username,name,message_count FROM chats ORDER BY rowid")]
            with HistoryStore(database_path, voice_model_path=voice_model_path, voice_device=voice_device) as store:
                for chat_index, chat_info in enumerate(chats):
                    username = str(chat_info.get("username", ""))
                    if not username:
                        continue
                    if progress:
                        progress(chat_index, len(chats), username)
                    all_messages = [dict(row) for row in exported.execute(
                        "SELECT username,local_id,type,sender_id,sender_name,create_time,content,sort_seq "
                        "FROM messages WHERE username=? ORDER BY sort_seq,local_id", (username,))]
                    records = []
                    for item in all_messages:
                        local_id = item.get("local_id", item.get("sort_seq"))
                        try:
                            media = self._download_local_media(
                                downloader, username, local_id, item, media_dir,
                                include_images=include_images)
                        except Exception:
                            # A missing image key or an incomplete local media
                            # file must not discard the text history.
                            media_errors += 1
                            media = []
                        records.append({
                            "id": make_message_id(username, local_id, item.get("sort_seq"),
                                                  item.get("server_id"), item.get("type")),
                            "chat": username,
                            "sender": str(item.get("sender_username", "")),
                            "content": str(item.get("content", "")),
                            "time": str(item.get("create_time", "")),
                            "direction": "outgoing" if str(item.get("sender_id", "")) == "2" else "incoming",
                            "source": source,
                            "raw": {"local_id": local_id, "sort_seq": item.get("sort_seq"),
                                    "server_id": item.get("server_id"), "type": item.get("type")},
                            "media": media,
                        })
                    rows_added += store.save_messages(records)
                    if all_messages:
                        store.set_cursor(source, username,
                                         max(int(m.get("sort_seq", 0)) for m in all_messages))
                    total_messages += len(records)
                    total_media += sum(len(record["media"]) for record in records)
            exported.close()
        return {"chats": len(chats), "messages_read": total_messages,
                "media_read": total_media, "rows_added": rows_added,
                "media_errors": media_errors, "include_images": include_images,
                "database": str(Path(database_path).resolve())}

    @staticmethod
    def _download_local_media(downloader, username: str, local_id: Any,
                              message: dict, media_dir: str, *,
                              include_images: bool = True) -> list[dict]:
        raw_type = message.get("local_type")
        if raw_type is None:
            raw_type = {"图片": 3, "语音": 34, "视频": 43,
                        "文件/链接/卡片": 49}.get(str(message.get("type", "")))
        if raw_type is None and "type" not in message:
            try:
                row = downloader.db.get_message_row(username, local_id)
                raw_type = row.get("local_type") if row else None
            except (AttributeError, TypeError):
                return []
        if raw_type is None:
            return []
        kind_by_type = {3: "image", 34: "voice", 43: "video", 49: "file"}
        kind = kind_by_type.get(int(raw_type))
        if not kind:
            return []
        if kind == "image" and not include_images:
            return []
        path = downloader.download_media(username, local_id, save_dir=media_dir)
        if not path or not Path(path).is_file():
            return []
        payload = Path(path).read_bytes()
        return [{"kind": kind, "mime_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
                 "original_ref": str(path), "local_name": Path(path).name, "data": payload}]

    @staticmethod
    def _message_media(message: dict) -> list[dict]:
        """Normalize local media exposed by a WeChat DB adapter.

        Adapters differ in field names, so accept bytes, a path, or a list of
        dictionaries. Remote URLs are deliberately ignored: this archive is
        local-only and must not silently download network media.
        """
        candidates = []
        for key in ("media", "attachments", "images", "image_path", "voice_path",
                    "audio_path", "video_path", "file_path", "media_path"):
            value = message.get(key)
            if value is not None:
                default_kind = {"images": "image", "image_path": "image",
                                "voice_path": "voice", "audio_path": "audio",
                                "video_path": "video", "file_path": "file",
                                "media_path": "file"}.get(key, "file")
                candidates.extend((item, default_kind) for item in (value if isinstance(value, list) else [value]))
        result = []
        for index, (candidate, default_kind) in enumerate(candidates):
            kind, ref, payload = default_kind, "", None
            if isinstance(candidate, (bytes, bytearray, memoryview)):
                payload, ref = bytes(candidate), f"inline:{index}"
            elif isinstance(candidate, dict):
                kind = str(candidate.get("kind") or candidate.get("type") or "file")
                ref = str(candidate.get("path") or candidate.get("file_path") or
                           candidate.get("url") or candidate.get("uri") or "")
                value = candidate.get("data", candidate.get("bytes"))
                if isinstance(value, (bytes, bytearray, memoryview)):
                    payload = bytes(value)
            else:
                ref = str(candidate)
            if payload is None and ref and not ref.lower().startswith(("http://", "https://")):
                path = Path(ref)
                if path.is_file():
                    payload = path.read_bytes()
            if payload is None:
                continue
            mime = mimetypes.guess_type(ref)[0] or "application/octet-stream"
            result.append({"kind": kind, "mime_type": mime, "original_ref": ref,
                           "local_name": Path(ref).name if ref else f"media_{index}",
                           "data": payload})
        return result

    @staticmethod
    def dispatch_draft(draft: str, send: Callable[[str], Any], *, confirm: bool = False) -> Any:
        """Dispatch only after a caller intentionally confirms the exact draft."""
        if not confirm:
            raise PermissionError("Reply dispatch requires confirm=True")
        if not draft.strip():
            raise ValueError("draft must not be empty")
        return send(draft)
