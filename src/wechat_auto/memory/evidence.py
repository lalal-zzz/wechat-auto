"""Resolve structured evidence references only when an agent asks for them."""
from __future__ import annotations

from pathlib import Path

from wechat_auto.storage.history_store import HistoryStore
from wechat_auto.storage.moment_store import MomentStore
from wechat_auto.storage.profile_store import ProfileStore
from wechat_auto.utils.moment_reference import parse_moment_reference
from wechat_auto.utils.profile_reference import parse_profile_reference


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
            scoped = str(evidence_id).startswith('moment:')
            parsed = parse_moment_reference(evidence_id, self.moments_path) if scoped else None
            if scoped and parsed is None:
                return None
            with MomentStore(self.moments_path) as store:
                item = store.get_version(parsed[0]) if parsed else store.get(evidence_id)
            if item and scoped and item['content_hash'] != parsed[1]:
                return None
            scope = 'source_and_version_bound' if scoped else 'legacy_mutable_id'
            if item and not include_content:
                return {'id': evidence_id if scoped else item['id'], 'type': 'moment',
                        'username': item['username'], 'create_time': item['create_time'],
                        'content_available': bool(item['text']), 'reference_scope': scope,
                        **({'version_id': item['version_id'], 'verification_status': item['verification_status'],
                            'observed_at': item['observed_at']}
                           if scoped else {})}
            return {**item, 'evidence_id': evidence_id, 'reference_scope': scope} if item else None
        if evidence_type == "profile_snapshot":
            if not self.profiles_path or not self.profiles_path.is_file():
                return None
            scoped = str(evidence_id).startswith('profile:')
            parsed = parse_profile_reference(evidence_id, self.profiles_path) if scoped else None
            if scoped and parsed is None:
                return None
            if not scoped and not str(evidence_id).isdigit():
                return None
            local_id = parsed[0] if parsed else evidence_id
            with ProfileStore(self.profiles_path) as store:
                item = store.snapshot_by_id(local_id)
            if item and scoped and item['content_hash'] != parsed[1]:
                return None
            scope = 'source_and_content_bound' if scoped else 'legacy_local_id'
            if item and not include_content:
                return {'id': evidence_id if scoped else str(item['snapshot_id']), 'type': 'profile_snapshot',
                        'wechat_id': item['wechat_id'], 'observed_at': item['captured_at'],
                        'reference_scope': scope,
                        **({'comparison_scope': item['comparison_scope']} if 'comparison_scope' in item else {})}
            return {**item, 'evidence_id': evidence_id, 'reference_scope': scope} if item else None
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
