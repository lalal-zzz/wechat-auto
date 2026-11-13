"""Incremental analysis submission and dependency invalidation."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from wechat_auto.memory.markdown import MarkdownMemory
from wechat_auto.memory.store import MemoryStore


class AnalysisService:
    def __init__(self, store: MemoryStore, markdown: MarkdownMemory, history_path=None):
        self.store = store
        self.markdown = markdown
        self.history_path = Path(history_path).resolve() if history_path else None

    def submit(self, *, scope_type: str, scope_id: str, markdown: str,
               evidence_ids: Iterable[str], template_version: str,
               period: str = "", claims: Iterable[dict] = (),
               events: Iterable[dict] = (), coverage: dict | None = None,
               correction_ids: Iterable[str] = (), mode: str = "incremental",
               expected_parent: int | None = None, message_snapshot: str | None = None,
               upstream_month_versions: dict[str, int] | None = None,
               upstream_conversation_versions: dict[str, int] | None = None) -> dict:
        evidence = list(dict.fromkeys(map(str, evidence_ids)))
        fingerprint = self.store.input_fingerprint(
            scope_type, scope_id, period, evidence, template_version, correction_ids
        )
        if message_snapshot is not None:
            fingerprint = hashlib.sha256(f"{fingerprint}:{message_snapshot}".encode("ascii")).hexdigest()
        elif self.history_path and self.history_path.is_file():
            with closing(sqlite3.connect(self.history_path.as_uri()+"?mode=ro",uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='voice_transcriptions' AND type='table'").fetchone():
                    ids = set(evidence)
                    revisions = [tuple(row) for row in db.execute("SELECT message_id,version,text,engine,audio_sha256 FROM voice_transcriptions") if row[0] in ids]
                    if revisions:
                        fingerprint = hashlib.sha256((fingerprint+repr(sorted(revisions))).encode("utf-8")).hexdigest()
        if upstream_month_versions is not None:
            fingerprint = hashlib.sha256(
                (fingerprint + ":rollup-month-versions-v1:" +
                 json.dumps(upstream_month_versions, sort_keys=True)).encode("utf-8")
            ).hexdigest()
        if upstream_conversation_versions is not None:
            fingerprint = hashlib.sha256(
                (fingerprint + ":person-rollups-v1:" +
                 json.dumps(upstream_conversation_versions, sort_keys=True)).encode("utf-8")
            ).hexdigest()
        with self.markdown.publication(scope_type, scope_id, period):
            current = self.store.current_version(scope_type, scope_id, period)
            parent = int(current["version"]) if current else 0
            if expected_parent is not None and parent != expected_parent:
                raise RuntimeError(f"stale analysis parent: expected {expected_parent}, current {parent}")
            if current and current["input_fingerprint"] == fingerprint:
                self.markdown.read_current(scope_type, scope_id, period)
                return {"changed": False, "version": current["version"],
                        "input_fingerprint": fingerprint, "reason": "input_unchanged"}
            previous_body = self.markdown.read_current(scope_type, scope_id, period) if current else None
            result = None
            run_id = self.store.start_run(scope_type, scope_id, period, fingerprint, mode=mode)
            created_claims: list[str] = []
            created_events: list[str] = []
            try:
                with self.store.atomic():
                    if upstream_month_versions is not None:
                        versions = self.store.current_registered_month_versions(scope_id)
                        if versions != upstream_month_versions:
                            raise ValueError("Upstream monthly versions changed before publication")
                    if upstream_conversation_versions is not None:
                        linked = {item["conversation_id"] for item in self.store.person_conversations(scope_id)}
                        if linked != set(upstream_conversation_versions):
                            raise ValueError("Linked conversations changed before publication")
                        for conversation_id, version in upstream_conversation_versions.items():
                            current_rollup = self.store.current_version("conversation", conversation_id)
                            if (not current_rollup or current_rollup["version"] != version
                                    or self.store.rollup_month_versions(conversation_id, version) !=
                                    self.store.current_registered_month_versions(conversation_id)):
                                raise ValueError("Upstream conversation versions changed before publication")
                    for claim in claims:
                        item = dict(claim)
                        item.setdefault("conversation_id", scope_id if scope_type == "conversation" else None)
                        created_claims.append(self.store.add_claim(**item))
                    for event in events:
                        item = dict(event)
                        item.setdefault("conversations", [scope_id] if scope_type == "conversation" else [])
                        created_events.append(self.store.add_event(**item))
                    result = self.markdown.write(
                        scope_type, scope_id, markdown, period=period,
                        input_fingerprint=fingerprint, expected_parent=parent,
                    )
                    version = int(result["version"])
                    if message_snapshot is not None:
                        self.store.record_archive_snapshot(scope_type, scope_id, period, version, message_snapshot)
                    if upstream_month_versions is not None:
                        self.store.record_rollup_month_versions(scope_id, version, upstream_month_versions)
                    values = coverage or {}
                    self.store.update_coverage(
                        scope_type, scope_id, period,
                        message_watermark=str(values.get("message_watermark", "")),
                        moment_watermark=str(values.get("moment_watermark", "")),
                        profile_watermark=str(values.get("profile_watermark", "")),
                        evidence_count=len(evidence), input_fingerprint=fingerprint,
                    )
                    self.store.complete_run(run_id, version)
                    node_id = f"{scope_id}:{period}" if period else scope_id
                    node_type = "conversation_month" if scope_type == "conversation" and period else scope_type
                    downstream = self.store.propagate_dirty(node_type, node_id, "analysis_updated")
                    for node in downstream:
                        if node["node_type"] == "conversation":
                            self.store.enqueue_job("conversation_summary", "conversation",
                                                   node["node_id"], priority=30)
                        elif node["node_type"] == "person":
                            self.store.enqueue_job("person_analysis", "person",
                                                   node["node_id"], priority=20)
                        elif node["node_type"] == "relationship":
                            self.store.enqueue_job("relationship_analysis", "relationship",
                                                   node["node_id"], priority=20)
                    return {"changed": bool(result["changed"]), "version": version,
                            "input_fingerprint": fingerprint, "claims": created_claims,
                            "events": created_events, "downstream_dirty": downstream,
                            "path": result["path"]}
            except BaseException as exc:
                try:
                    if result is not None:
                        self.markdown._rollback_publication(result, previous_body)
                finally:
                    self.store.fail_run(run_id, str(exc))
                raise

    def queue_month(self, conversation_id: str, period: str, *, priority: int = 0,
                    input_fingerprint: str = "") -> str:
        return self.store.enqueue_job(
            "monthly_analysis", "conversation", conversation_id,
            period=period, priority=priority, input_fingerprint=input_fingerprint,
        )

    def mark_message_delta(self, conversation_id: str, period: str, message_id: str | Iterable[str]) -> None:
        ids = (message_id,) if isinstance(message_id, str) else message_id
        with self.store.atomic():
            self.store.queue_month_message_delta(conversation_id, period, ids)
