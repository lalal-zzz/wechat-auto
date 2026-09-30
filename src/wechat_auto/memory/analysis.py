"""Incremental analysis submission and dependency invalidation."""
from __future__ import annotations

from collections.abc import Iterable

from wechat_auto.memory.markdown import MarkdownMemory
from wechat_auto.memory.store import MemoryStore


class AnalysisService:
    def __init__(self, store: MemoryStore, markdown: MarkdownMemory):
        self.store = store
        self.markdown = markdown

    def submit(self, *, scope_type: str, scope_id: str, markdown: str,
               evidence_ids: Iterable[str], template_version: str,
               period: str = "", claims: Iterable[dict] = (),
               events: Iterable[dict] = (), coverage: dict | None = None,
               correction_ids: Iterable[str] = (), mode: str = "incremental",
               expected_parent: int | None = None) -> dict:
        evidence = list(dict.fromkeys(map(str, evidence_ids)))
        fingerprint = self.store.input_fingerprint(
            scope_type, scope_id, period, evidence, template_version, correction_ids
        )
        current = self.store.current_version(scope_type, scope_id, period)
        parent = int(current["version"]) if current else 0
        if expected_parent is not None and parent != expected_parent:
            raise RuntimeError(f"stale analysis parent: expected {expected_parent}, current {parent}")
        if current and current["input_fingerprint"] == fingerprint:
            return {"changed": False, "version": current["version"],
                    "input_fingerprint": fingerprint, "reason": "input_unchanged"}
        run_id = self.store.start_run(scope_type, scope_id, period, fingerprint, mode=mode)
        created_claims: list[str] = []
        created_events: list[str] = []
        try:
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
                input_fingerprint=fingerprint, expected_parent=expected_parent,
            )
            version = int(result["version"])
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
        except Exception as exc:
            self.store.fail_run(run_id, str(exc))
            raise

    def queue_month(self, conversation_id: str, period: str, *, priority: int = 0,
                    input_fingerprint: str = "") -> str:
        return self.store.enqueue_job(
            "monthly_analysis", "conversation", conversation_id,
            period=period, priority=priority, input_fingerprint=input_fingerprint,
        )

    def mark_message_delta(self, conversation_id: str, period: str, message_id: str) -> None:
        node_id = f"{conversation_id}:{period}"
        self.store.mark_dirty("conversation_month", node_id, "new_message", message_id)
        self.store.enqueue_job("monthly_analysis", "conversation", conversation_id,
                               period=period, priority=50)
        self.store.add_dependency("conversation_month", node_id,
                                  "conversation", conversation_id, "rolls_up_to")
