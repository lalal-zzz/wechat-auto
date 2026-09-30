"""Resolve structured evidence references only when an agent asks for them."""
from __future__ import annotations

from pathlib import Path

from wechat_auto.storage.history_store import HistoryStore
from wechat_auto.storage.moment_store import MomentStore
from wechat_auto.storage.profile_store import ProfileStore


class EvidenceResolver:
    def __init__(self, *, history_path: str | Path | None = None,
                 moments_path: str | Path | None = None,
                 profiles_path: str | Path | None = None):
        self.history_path = Path(history_path).resolve() if history_path else None
        self.moments_path = Path(moments_path).resolve() if moments_path else None
        self.profiles_path = Path(profiles_path).resolve() if profiles_path else None

    def get(self, evidence_type: str, evidence_id: str, *, include_content: bool = False) -> dict | None:
        if evidence_type == "message":
            if not self.history_path or not self.history_path.is_file():
                return None
            with HistoryStore(self.history_path) as store:
                item = store.get_message(evidence_id)
            if item and not include_content:
                return {"id": item["id"], "type": "message", "chat": item["chat"],
                        "time": item["time"], "direction": item["direction"],
                        "content_available": bool(item["content"])}
            return item
        if evidence_type == "moment":
            if not self.moments_path or not self.moments_path.is_file():
                return None
            with MomentStore(self.moments_path) as store:
                item = store.get(evidence_id)
            if item and not include_content:
                return {"id": item["id"], "type": "moment", "username": item["username"],
                        "create_time": item["create_time"], "content_available": bool(item["text"])}
            return item
        if evidence_type == "profile_snapshot":
            if not self.profiles_path or not self.profiles_path.is_file():
                return None
            with ProfileStore(self.profiles_path) as store:
                item = store.snapshot_by_id(evidence_id)
            if item and not include_content:
                return {"id": str(item["snapshot_id"]), "type": "profile_snapshot",
                        "wechat_id": item["wechat_id"], "observed_at": item["captured_at"]}
            return item
        return None

    def context(self, evidence_type: str, evidence_id: str, *, before: int = 5,
                after: int = 5) -> list[dict]:
        if evidence_type != "message" or not self.history_path or not self.history_path.is_file():
            return []
        with HistoryStore(self.history_path) as store:
            message = store.get_message(evidence_id)
            if message is None:
                return []
            return store.fetch_context(message["chat"], evidence_id, before=before, after=after)
