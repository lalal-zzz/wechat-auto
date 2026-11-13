"""Local stdio MCP surface for WeChat memory and confirmed actions."""
from __future__ import annotations

import argparse
import logging
import sqlite3
from contextlib import ExitStack, asynccontextmanager, closing
from datetime import date
from pathlib import Path
from typing import Any

from wechat_auto.memory.analysis import AnalysisService
from wechat_auto.memory.context import ContextBuilder
from wechat_auto.memory.dashboard import DashboardBuilder
from wechat_auto.memory.evidence import EvidenceResolver
from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.memory.markdown import MarkdownMemory
from wechat_auto.memory.store import MemoryStore
from wechat_auto.version import (
    CONTACT_ACTION_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION,
    __version__,
)


def _mcp_class():
    try:
        from mcp.server.mcpserver import MCPServer
        return MCPServer
    except ImportError:  # pragma: no cover - compatibility with MCP SDK v1
        from mcp.server.fastmcp import FastMCP
        return FastMCP


def _redact_mcp_trace(record: logging.LogRecord) -> bool:
    if record.exc_info or record.exc_text or record.stack_info:
        record.msg = "MCP request failed"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
    return True


def create_server(*, memory_db: str, memory_root: str,
                  history_db: str | None = None, moments_db: str | None = None,
                  profiles_db: str | None = None, basic_skill=None,
                  conversation_backend=None, voice_model_path: str | None = None,
                  runtime_health: dict | None = None):
    """Create an MCP server without opening a network listener."""
    MCPServer = _mcp_class()
    store = MemoryStore(memory_db)

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield {"memory_db": str(store.path)}
        finally:
            store.close()

    server = MCPServer(
        "wechat-auto",
        instructions=("Local-only WeChat archive and memory tools. Expand evidence only when needed. "
                      "Every real send requires an exact, unexpired confirmation."),
        lifespan=lifespan,
    )
    # Kept for process-lifetime cleanup and lightweight integration tests.
    server._wechat_auto_store = store
    markdown = MarkdownMemory(memory_root, store)
    analysis = AnalysisService(store, markdown, history_db)
    context = ContextBuilder(store, markdown, history_db)
    evidence = EvidenceResolver(history_path=history_db, moments_path=moments_db,
                                profiles_path=profiles_db)
    indexer = ArchiveIndexer(store)
    dashboard = DashboardBuilder(store, Path(memory_root) / "dashboard")
    from wechat_auto.backends.collection_sync import LocalCollectionSource
    from wechat_auto.memory.collection import MomentsCollection
    from wechat_auto.memory.contact_state import ContactState
    collection = MomentsCollection(store)
    contact_state = ContactState(store)
    collection_source = LocalCollectionSource(
        memory_path=memory_db, profiles_path=profiles_db or 'data/wechat_contact_profiles.sqlite3',
        moments_path=moments_db or 'data/wechat_moments.sqlite3')

    @server.tool(name='sync.contacts_moments_local')
    def sync_contacts_moments_local() -> dict:
        """Refresh all cached local contact profiles/Moments; no remote media download."""
        return collection_source.refresh()

    @server.tool(name='sync.moments_coverage')
    def sync_moments_coverage(person_id: str) -> dict:
        """Read per-person local cache/UI loading history, never certify all server history."""
        return collection.get(person_id)

    @server.tool(name='sync.enqueue_moments_contacts')
    def sync_enqueue_moments_contacts(person_ids: list[str]) -> dict:
        """Queue explicitly selected known contacts; raw contact rows are not all friends."""
        return collection.enqueue(person_ids)

    @server.tool(name='sync.moments_queue')
    def sync_moments_queue() -> list[dict]:
        """Read the resumable contact loading queue without UI actions."""
        return collection.queue()

    @server.tool(name='entities.contact_state')
    def entities_contact_state(person_id: str) -> dict:
        """Read directional deletion, blocking, access states and their evidence history."""
        return contact_state.get(person_id)

    @server.tool(name='entities.record_contact_state')
    def entities_record_contact_state(person_id: str, relation: str, value: str,
                                      source: str, evidence_ref: str, observation_key: str,
                                      confirmed: bool = False) -> dict:
        """Record reviewed state only; never delete/block contacts or send probe messages."""
        return contact_state.record(person_id, relation, value, source=source,
                                    evidence_ref=evidence_ref, observation_key=observation_key,
                                    confirmed=confirmed)

    @server.tool(name='sync.recover_moments_contact')
    def sync_recover_moments_contact(person_id: str) -> dict:
        """Recover an interrupted entry after checking its collector process has ended."""
        return {'recovered': collection.recover_interrupted(person_id)}

    if basic_skill is not None:
        @server.tool(name='sync.load_contact_moments')
        def sync_load_contact_moments(person_id: str, max_pages: int = 5) -> dict:
            """Load one verified person's visible album then refresh local DB; bounded and resumable."""
            return collection.run_one(person_id, basic_skill, sync_after_load=collection_source,
                                      max_pages=max_pages)

    @server.tool(name="status.summary")
    def status_summary() -> dict:
        """Return counts and pending analysis jobs without exposing private content."""
        return {
            "versions": {
                "application": __version__,
                "memory_schema": store.schema_version,
                "mcp_protocol": MCP_PROTOCOL_VERSION,
                "contact_action_protocol": CONTACT_ACTION_PROTOCOL_VERSION,
            },
            "counts": store.database_summary(),
            "pending_jobs": store.next_jobs(20),
            "runtime": runtime_health or {
                "ui": {"status": "available" if basic_skill is not None else "not_configured"},
                "conversation_backend": {
                    "status": "available" if conversation_backend is not None else "not_configured"
                },
            },
        }

    @server.tool(name="vision.page_catalog")
    def vision_page_catalog() -> dict:
        """Enumerate page families, anchor coverage, layers and verification gaps."""
        from wechat_auto.primitives.page_catalog import (
            PAGE_CATALOG_VERSION,
            list_page_catalog,
        )

        return {"catalog_version": PAGE_CATALOG_VERSION, "pages": list_page_catalog()}

    @server.tool(name="actions.page_capabilities")
    def actions_page_capabilities() -> dict:
        """List per-page navigation contracts and separately confirmed mutations."""
        from wechat_auto.actions.pages import list_page_capabilities

        return list_page_capabilities()

    @server.tool(name="actions.plan_page_route")
    def actions_plan_page_route(source_page: str, target_page: str) -> dict:
        """Plan declared transitions; every execution still needs live pre/post checks."""
        from wechat_auto.actions.pages import plan_page_route

        return {"operations": plan_page_route(source_page, target_page),
                "live_verification_required": True, "coordinates_may_require_calibration": True}

    @server.tool(name="sync.index_archives")
    def sync_index_archives() -> dict:
        """Incrementally index existing archives; raw message bodies are not copied."""
        result: dict[str, Any] = {}
        if history_db:
            result["history"] = indexer.index_history(history_db)
        if profiles_db:
            result["profiles"] = indexer.index_profiles(profiles_db)
            result["profile_snapshots"] = indexer.index_profile_snapshots(profiles_db)
        if moments_db:
            result["moments"] = indexer.index_moments(moments_db)
        return result

    @server.tool(name="analysis.queue_initial")
    def analysis_queue_initial(direct_count: int = 5, group_count: int = 5) -> dict:
        """Queue all months for the most active current direct and group chats."""
        if not history_db:
            raise RuntimeError("history database is not configured")
        return indexer.queue_initial_top(history_db, analysis,
                                         direct_count=direct_count, group_count=group_count)

    @server.tool(name="analysis.jobs")
    def analysis_jobs(limit: int = 20) -> list[dict]:
        """List queued incremental analysis work."""
        return store.next_jobs(limit)

    def validate_analysis_scope(scope_type: str, scope_id: str, period: str) -> None:
        if scope_type not in {"conversation", "person", "relationship", "group", "event"} or not scope_id.strip():
            raise ValueError("A supported scope type and stable scope ID are required")
        if period:
            if scope_type != "conversation" or len(period) != 7:
                raise ValueError("Only conversation scopes support a YYYY-MM period")
            date.fromisoformat(period + "-01")

    def compare_month_archive(node: dict) -> str:
        if not history_db or not node["message_snapshot"]:
            return "unknown"
        conversation = store.get_conversation(node["scope_id"])
        if conversation is None:
            return "unknown"
        from wechat_auto.storage import HistoryStore
        try:
            snapshot = HistoryStore.read_month_message_snapshot(history_db, conversation["source_chat_id"], node["period"])
        except sqlite3.Error:
            return "unknown"
        return "matches" if snapshot == node["message_snapshot"] else "changed"

    def read_latest_message(contact: str) -> tuple[str, dict]:
        if conversation_backend is None:
            raise PermissionError("Current conversation cannot be verified")
        try:
            message, = conversation_backend.get_context(contact, limit=1)
            if int(message.get("sort_seq") or 0) <= 0 or not (message.get("local_id") or message.get("server_id")):
                raise ValueError("Missing stable message identity")
            from wechat_auto.storage import make_message_id
            return make_message_id(contact, message.get("local_id"), message.get("sort_seq"),
                                   message.get("server_id"), message.get("type")), message
        except Exception:
            raise PermissionError("Current conversation cannot be verified") from None

    def compare_live_head(scope_id: str, period: str) -> str:
        conversation = store.get_conversation(scope_id)
        if not history_db or conversation is None or conversation_backend is None:
            return "unknown"
        from wechat_auto.memory.indexer import message_period
        from wechat_auto.storage.history_store import make_message_fingerprint

        chat = conversation["source_chat_id"]
        try:
            message_id, message = read_latest_message(chat)
            if period:
                observed_period = message_period(message.get("create_time"))
                if not observed_period:
                    return "unknown"
                if observed_period != period:
                    return "outside_period"
            with closing(sqlite3.connect(Path(history_db).resolve().as_uri() + "?mode=ro", uri=True)) as archive:
                archive.execute("BEGIN")
                if archive.execute("SELECT 1 FROM messages WHERE id=? AND chat=?", (message_id, chat)).fetchone():
                    return "id_matches"
                fingerprint = make_message_fingerprint(
                    chat, message.get("create_time"), str(message.get("content", "")),
                    str(message.get("sender_username", "")), message.get("type"), message.get("sort_seq"),
                )
                if archive.execute("SELECT 1 FROM messages WHERE chat=? AND fingerprint=? LIMIT 1",
                                   (chat, fingerprint)).fetchone():
                    return "fingerprint_matches"
                return "missing"
        except (PermissionError, sqlite3.Error):
            return "unknown"

    @server.tool(name="analysis.scope_status")
    def analysis_scope_status(scope_type: str, scope_id: str, period: str = "",
                              check_live_head: bool = False) -> dict:
        """Report recorded analysis state for a target and its registered upstream nodes."""
        validate_analysis_scope(scope_type, scope_id, period)
        nodes = store.analysis_scope_status(scope_type, scope_id, period)
        archive_comparison = "unknown"
        if period:
            current = next(node for node in nodes if (node["scope_type"], node["scope_id"], node["period"])
                           == (scope_type, scope_id, period))
            archive_comparison = compare_month_archive(current)
        return {"scope_type": scope_type, "scope_id": scope_id, "period": period,
                "source_freshness": "unknown", "dependency_readiness": "unknown",
                "archive_comparison": archive_comparison,
                "live_head_archive_comparison": compare_live_head(scope_id, period)
                if check_live_head and scope_type == "conversation" else "unknown",
                "nodes": nodes}

    def require_current_months_for(conversation_id: str) -> list[dict]:
        conversation = store.get_conversation(conversation_id)
        if not history_db or conversation is None:
            raise ValueError("Local archive coverage cannot be verified")
        try:
            archive_periods = indexer.history_periods(history_db, conversation["source_chat_id"])
        except sqlite3.Error:
            raise ValueError("Local archive coverage cannot be verified") from None
        months = [node for node in store.analysis_scope_status("conversation", conversation_id)
                  if node["node_type"] == "conversation_month" and node["scope_id"] == conversation_id]
        registered = {node["period"] for node in months}
        if not registered or (archive_periods | set(markdown.list_periods(conversation_id))) - registered:
            raise ValueError("Monthly input registration is incomplete; verify archive coverage first")
        inputs = []
        for node in months:
            if node["version"] is None or any(job["status"] in {"pending", "running"} for job in node["jobs"]):
                raise ValueError("Registered monthly analysis is unfinished")
            if compare_month_archive(node) != "matches":
                raise ValueError("Registered monthly analysis cannot be verified against the local archive")
            body = markdown.read_version("conversation", conversation_id, node["version"], node["period"])
            inputs.append({"period": node["period"], "version": node["version"], "memory": body})
        return inputs

    @server.tool(name="analysis.get_month_input")
    def analysis_get_month_input(conversation_id: str, period: str,
                                 after_id: str = "", limit: int = 1000,
                                 expected_message_snapshot: str | None = None) -> dict:
        """Read one bounded raw month page for an explicitly claimed analysis job."""
        if not history_db:
            raise RuntimeError("history database is not configured")
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError("conversation not found")
        from wechat_auto.storage import HistoryStore
        with HistoryStore(history_db) as history:
            history._connection.execute("BEGIN")
            message_snapshot = history.month_message_snapshot(conversation["source_chat_id"], period)
            if expected_message_snapshot is not None and expected_message_snapshot != message_snapshot:
                raise ValueError("Archived month changed; restart reading from the first page")
            messages = history.fetch_month(conversation["source_chat_id"], period,
                                           after_id=after_id, limit=limit)
        return {"conversation_id": conversation_id, "period": period,
                "messages": messages, "count": len(messages),
                "message_snapshot": message_snapshot,
                "next_after_id": messages[-1]["id"] if len(messages) == limit else ""}

    @server.tool(name="analysis.get_conversation_input")
    def analysis_get_conversation_input(conversation_id: str, require_current_months: bool = False) -> dict:
        """Read current monthly memories for a cross-month conversation rollup."""
        months = require_current_months_for(conversation_id) if require_current_months else [
            {"period": period,
             "memory": markdown.read_current("conversation", conversation_id, period)}
            for period in markdown.list_periods(conversation_id)
        ]
        return {"conversation_id": conversation_id,
                "user_corrections": store.active_user_corrections("conversation", conversation_id),
                "months": months,
                **({"upstream_month_versions": {item["period"]: item["version"] for item in months}}
                   if require_current_months else {})}

    def require_person_rollups(conversations: list[dict]) -> list[dict]:
        if not conversations:
            raise ValueError("No linked conversations; verify analysis dependencies first")
        inputs = []
        for item in conversations:
            conversation_id = item["conversation_id"]
            months = {month["period"]: month["version"] for month in require_current_months_for(conversation_id)}
            rollup = store.current_version("conversation", conversation_id)
            if not rollup:
                raise ValueError("Linked conversation summary is unfinished")
            version = rollup["version"]
            if store.rollup_month_versions(conversation_id, version) != months:
                raise ValueError("Linked conversation summary does not cover the verified monthly versions")
            inputs.append({"conversation": item, "version": version,
                           "memory": markdown.read_version("conversation", conversation_id, version)})
        return inputs

    @server.tool(name="analysis.get_person_input")
    def analysis_get_person_input(person_id: str, claim_limit: int = 100,
                                  require_current_months: bool = False) -> dict:
        """Read compact cross-context inputs for one person's incremental analysis."""
        conversations = store.person_conversations(person_id)
        inputs = require_person_rollups(conversations) if require_current_months else [
            {"conversation": item, "memory": markdown.read_current("conversation", item["conversation_id"])}
            for item in conversations
        ]
        return {"person_id": person_id,
                "user_corrections": store.active_user_corrections("person", person_id),
                "claims": context.compact_claims(
                    person_id=person_id, limit=claim_limit),
                "conversations": inputs,
                "current_person_memory": markdown.read_current("person", person_id),
                **({"upstream_conversation_versions": {
                    item["conversation"]["conversation_id"]: item["version"] for item in inputs
                }} if require_current_months else {})}

    @server.tool(name="analysis.claim_job")
    def analysis_claim_job(worker_id: str = "agent", job_id: str | None = None,
                           scope_type: str = "", scope_id: str = "",
                           period: str = "") -> dict | None:
        """Claim a pending job by ID and/or exact scope, or take the next unfiltered job."""
        scope = None
        if scope_type or scope_id or period:
            validate_analysis_scope(scope_type, scope_id, period)
            scope = (scope_type, scope_id, period)
        return store.claim_next_job(worker_id=worker_id, job_id=job_id, scope=scope)

    @server.tool(name="analysis.complete_job")
    def analysis_complete_job(job_id: str, success: bool, error: str = "") -> dict:
        """Close one claimed analysis job after submission or failure."""
        store.complete_job(job_id, success=success, error=error)
        return {"job_id": job_id, "status": "complete" if success else "failed"}

    @server.tool(name="analysis.submit")
    def analysis_submit(scope_type: str, scope_id: str, markdown_text: str,
                        evidence_ids: list[str], template_version: str,
                        period: str = "", claims: list[dict] | None = None,
                        events: list[dict] | None = None,
                        coverage: dict | None = None,
                        mode: str = "incremental",
                        expected_parent: int | None = None,
                        correction_ids: list[str] | None = None,
                        expected_message_snapshot: str | None = None,
                        expected_upstream_month_versions: dict[str, int] | None = None,
                        expected_upstream_conversation_versions: dict[str, int] | None = None) -> dict:
        """Commit structured results and one compact full Markdown version atomically."""
        if correction_ids:
            active_ids = {item["correction_id"] for item in store.active_user_corrections(scope_type, scope_id)}
            if not set(correction_ids) <= active_ids:
                raise ValueError("Correction IDs must be active and belong to the analysis target")
        with ExitStack() as resources:
            if expected_upstream_conversation_versions is not None:
                if scope_type != "person" or period or not history_db:
                    raise ValueError("Upstream conversation versions require a person analysis and an archive")
                if Path(history_db).samefile(memory_db):
                    raise ValueError("Protected publication requires separate archive and Memory databases")
                from wechat_auto.storage import HistoryStore
                history = resources.enter_context(HistoryStore(history_db))
                resources.enter_context(history.protect_archive_snapshot())
                versions = {item["conversation"]["conversation_id"]: item["version"]
                            for item in require_person_rollups(store.person_conversations(scope_id))}
                if versions != expected_upstream_conversation_versions:
                    raise ValueError("Upstream conversation versions changed; read the person inputs again")
            if expected_upstream_month_versions is not None:
                if scope_type != "conversation" or period or not history_db:
                    raise ValueError("Upstream monthly versions require a conversation rollup and an archive")
                if Path(history_db).samefile(memory_db):
                    raise ValueError("Protected publication requires separate archive and Memory databases")
                from wechat_auto.storage import HistoryStore
                history = resources.enter_context(HistoryStore(history_db))
                resources.enter_context(history.protect_archive_snapshot())
                versions = {item["period"]: item["version"] for item in require_current_months_for(scope_id)}
                if versions != expected_upstream_month_versions:
                    raise ValueError("Upstream monthly versions changed; read the rollup inputs again")
            if expected_message_snapshot is not None:
                if scope_type != "conversation" or not period or not history_db:
                    raise ValueError("Message snapshot requires a conversation month and an archive")
                conversation = store.get_conversation(scope_id)
                if conversation is None:
                    raise ValueError("Conversation not found")
                if Path(history_db).samefile(memory_db):
                    raise ValueError("Protected publication requires separate archive and Memory databases")
                from wechat_auto.storage import HistoryStore
                history = resources.enter_context(HistoryStore(history_db))
                snapshot = resources.enter_context(history.protect_month_snapshot(conversation["source_chat_id"], period))
                if snapshot != expected_message_snapshot:
                    raise ValueError("Archived month changed; restart reading before submitting")
            return analysis.submit(
                scope_type=scope_type, scope_id=scope_id, period=period,
                markdown=markdown_text, evidence_ids=evidence_ids,
                template_version=template_version, claims=claims or (), events=events or (),
                coverage=coverage, mode=mode, expected_parent=expected_parent,
                correction_ids=correction_ids or (), message_snapshot=expected_message_snapshot,
                upstream_month_versions=expected_upstream_month_versions,
                upstream_conversation_versions=expected_upstream_conversation_versions,
            )

    @server.tool(name="claims.get")
    def claims_get(claim_id: str, include_evidence_refs: bool = False) -> dict | None:
        """Read one compact claim; optionally include evidence references, not raw content."""
        return store.get_claim(claim_id, include_evidence=include_evidence_refs)

    @server.tool(name="claims.create")
    def claims_create(canonical_text: str, claim_type: str,
                      status: str = "inferred", confidence: float = .5,
                      subject_person_id: str = "", object_person_id: str = "",
                      conversation_id: str = "", group_id: str = "",
                      valid_from: str = "", valid_to: str = "",
                      evidence_refs: list[dict] | None = None) -> dict:
        """Create one compact structured claim; long analysis belongs in Markdown."""
        claim_id = store.add_claim(
            canonical_text, claim_type=claim_type, status=status, confidence=confidence,
            subject_person_id=subject_person_id or None, object_person_id=object_person_id or None,
            conversation_id=conversation_id or None, group_id=group_id or None,
            valid_from=valid_from or None, valid_to=valid_to or None,
            evidence=evidence_refs or (),
        )
        return {"claim_id": claim_id}

    @server.tool(name="claims.invalidate")
    def claims_invalidate(claim_id: str) -> dict:
        """Retain but deactivate a claim and create a new claim version."""
        return {"claim_id": claim_id, "version": store.invalidate_claim(claim_id),
                "status": "inactive"}

    @server.tool(name="claims.search")
    def claims_search(query: str = "", person_id: str = "",
                      conversation_id: str = "", limit: int = 30) -> list[dict]:
        """Search compact claims by task scope."""
        return store.search_claims(query=query, person_id=person_id or None,
                                   conversation_id=conversation_id or None, limit=limit)

    @server.tool(name="events.get")
    def events_get(event_id: str) -> dict | None:
        """Read a long-running event with phases and links."""
        return store.get_event(event_id)

    @server.tool(name="events.upsert")
    def events_upsert(title: str, event_type: str = "life_event", summary: str = "",
                      started_at: str = "", ended_at: str = "", status: str = "observed",
                      confidence: float = .5, people: list[str] | None = None,
                      conversations: list[str] | None = None, claims: list[str] | None = None,
                      phases: list[dict] | None = None, event_id: str = "") -> dict:
        """Create or version one cross-month event."""
        value = store.add_event(
            title, event_type=event_type, summary=summary, started_at=started_at or None,
            ended_at=ended_at or None, status=status, confidence=confidence,
            people=people or (), conversations=conversations or (), claims=claims or (),
            phases=phases or (), event_id=event_id or None,
        )
        return {"event_id": value}

    @server.tool(name="entities.people")
    def entities_people(active_only: bool = False, limit: int = 100) -> list[dict]:
        """List normalized people without messages or media."""
        return store.list_people(active_only=active_only, limit=limit)

    @server.tool(name="entities.conversations")
    def entities_conversations(active_only: bool = False, limit: int = 100) -> list[dict]:
        """List normalized conversations without message bodies."""
        return store.list_conversations(active_only=active_only, limit=limit)

    @server.tool(name="entities.ensure_relationship")
    def entities_ensure_relationship(left_person_id: str, right_person_id: str,
                                     relationship_type: str = "unknown") -> dict:
        """Create or update a stable relationship between two people."""
        return {"relationship_id": store.ensure_relationship(
            left_person_id, right_person_id, relationship_type=relationship_type
        )}

    @server.tool(name="entities.reconcile_snapshot")
    def entities_reconcile_snapshot(entity_type: str, entity_ids: list[str],
                                    observed_at: str = "", source: str = "wechat_db",
                                    complete: bool = True) -> dict:
        """Apply a presence snapshot; incomplete snapshots never mark absence."""
        return store.reconcile_snapshot(entity_type, entity_ids,
                                        observed_at=observed_at or None,
                                        source=source, complete=complete)

    @server.tool(name="entities.propose_merge")
    def entities_propose_merge(left_person_id: str, right_person_id: str,
                               reason: str) -> dict:
        """Create an identity merge candidate; this does not merge anyone."""
        return {"candidate_id": store.propose_identity_merge(left_person_id, right_person_id, reason),
                "merged": False, "requires_confirmation": True}

    @server.tool(name="entities.decide_merge")
    def entities_decide_merge(candidate_id: str, confirm: bool) -> dict:
        """Explicitly accept or reject one reviewed identity merge candidate."""
        return store.decide_identity_merge(candidate_id, confirm=confirm)

    @server.tool(name="memory.add_correction")
    def memory_add_correction(target_type: str, target_id: str,
                              correction_text: str) -> dict:
        """Record a user correction and dirty its dependent memory."""
        return {"correction_id": store.add_user_correction(
            target_type, target_id, correction_text
        )}

    @server.tool(name="evidence.get_for_claim")
    def evidence_get_for_claim(claim_id: str, include_content: bool = False) -> list[dict]:
        """Expand a claim's evidence one level; raw content is opt-in."""
        refs = store.evidence_for_claim(claim_id)
        result = []
        for ref in refs:
            item = evidence.get(ref["evidence_type"], ref["evidence_id"],
                                include_content=include_content)
            result.append({"reference": ref, "evidence": item})
        return result

    @server.tool(name="evidence.get_context")
    def evidence_get_context(evidence_type: str, evidence_id: str,
                             before: int = 5, after: int = 5) -> list[dict]:
        """Explicitly expand nearby raw message context for one evidence item."""
        return evidence.context(evidence_type, evidence_id, before=before, after=after)

    @server.tool(name="memory.get_current")
    def memory_get_current(scope_type: str, scope_id: str, period: str = "") -> str:
        """Read the latest successful compact Markdown memory."""
        return markdown.read_current(scope_type, scope_id, period)

    @server.tool(name="memory.get_version")
    def memory_get_version(scope_type: str, scope_id: str, version: int,
                           period: str = "") -> str:
        """Read a prior complete Markdown memory version."""
        return markdown.read_version(scope_type, scope_id, version, period)

    @server.tool(name="memory.recover_publication")
    def memory_recover_publication(scope_type: str, scope_id: str, period: str = "") -> dict:
        """Preserve unindexed candidates in work/analysis; restore only successful text."""
        return markdown.recover_publication(scope_type, scope_id, period)

    @server.tool(name="memory.compare_versions")
    def memory_compare_versions(scope_type: str, scope_id: str, left: int,
                                right: int, period: str = "") -> str:
        """Return a compact unified diff between full memory versions."""
        return markdown.compare(scope_type, scope_id, left, right, period)

    @server.tool(name="memory.compact_context")
    def memory_compact_context(person_id: str = "", conversation_id: str = "",
                               query: str = "", limit: int = 30) -> dict:
        """Build high-density agent context with short claim references."""
        return context.compact_claims(person_id=person_id or None,
                                      conversation_id=conversation_id or None,
                                      query=query, limit=limit)

    @server.tool(name="charts.refresh")
    def charts_refresh(person_id: str = "", conversation_id: str = "") -> dict:
        """Regenerate the self-contained offline dashboard and Mermaid timeline."""
        kwargs = {"person_id": person_id or None, "conversation_id": conversation_id or None}
        return {"html": dashboard.build(**kwargs), "mermaid": dashboard.export_mermaid(**kwargs),
                "png": dashboard.export_png(**kwargs)}

    @server.tool(name="reply.create_draft")
    def reply_create_draft(conversation_id: str, trigger_evidence_id: str,
                           text: str, context_fingerprint: str,
                           expires_at: str = "", expected_memory_version_fingerprint: str | None = None) -> dict:
        """Save a reply candidate without touching WeChat."""
        with store.atomic():
            draft_id = store.create_reply_draft(conversation_id, trigger_evidence_id, text,
                                                context_fingerprint, expires_at or None)
            store.bind_reply_memory_versions(draft_id, conversation_id, expected_memory_version_fingerprint)
        return {"draft_id": draft_id, "sent": False, "requires_confirmation": True}

    def reply_context_with_versions(conversation_id: str, messages: list[dict], **kwargs) -> dict:
        fingerprint = store.reply_memory_version_fingerprint(conversation_id)
        result = context.reply_context(conversation_id, messages, **kwargs)
        if store.reply_memory_version_fingerprint(conversation_id) != fingerprint:
            raise PermissionError("Reply Memory changed while reading; read the reply context again")
        return {**result, "memory_version_fingerprint": fingerprint}

    @server.tool(name="reply.build_context")
    def reply_build_context(conversation_id: str, current_messages: list[dict],
                            person_id: str = "", claim_limit: int = 20,
                            pending_limit: int = 200, pending_after_id: str = "") -> dict:
        """Combine formal Markdown Memory, unanalysed archive pages and current messages."""
        return reply_context_with_versions(conversation_id, current_messages,
                                     person_id=person_id or None, claim_limit=claim_limit,
                                     pending_limit=pending_limit, pending_after_id=pending_after_id)

    def current_reply_trigger(contact: str) -> str:
        return read_latest_message(contact)[0]

    @server.tool(name="reply.confirm")
    def reply_confirm(draft_id: str) -> dict:
        """Confirm one exact saved draft; this still does not send it."""
        trigger = None
        if conversation_backend is not None:
            row = store._connection.execute(
                "SELECT c.source_chat_id FROM reply_drafts d JOIN conversations c USING(conversation_id) "
                "WHERE d.draft_id=?", (draft_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Draft conversation not found")
            trigger = current_reply_trigger(row["source_chat_id"])
        with store.atomic():
            confirmation_id = store.confirm_reply_draft(draft_id, expected_trigger=trigger)
        return {"draft_id": draft_id, "confirmation_id": confirmation_id,
                "sent": False, "confirmation_is_single_use": True}

    if basic_skill is not None:
        @server.tool(name="actions.open_search_content")
        def actions_open_search_content(query: str) -> dict:
            """Verify the main search query and open its network result in the right pane."""
            return basic_skill.open_search_content(query)

        @server.tool(name="vision.observe_windows")
        def vision_observe_windows(include_ocr: bool = True) -> list[dict]:
            """Observe main and auxiliary client-process HWNDs separately."""
            return basic_skill.observe_windows(include_ocr=include_ocr)

        @server.tool(name="vision.inspect_windows")
        def vision_inspect_windows(include_ocr: bool = True) -> list[dict]:
            """Compact HWND roles, layered surfaces and operations; omit private OCR/text."""
            return basic_skill.inspect_windows(include_ocr=include_ocr)

        @server.tool(name="vision.resolve_window")
        def vision_resolve_window(page: str, presentation: str | None = None, hwnd: int | None = None) -> dict:
            """Select a unique current surface; never authenticates a contact or executes input."""
            return basic_skill.resolve_target_window(page, presentation=presentation, hwnd=hwnd)

        @server.tool(name="actions.navigate_page")
        def actions_navigate_page(page: str, max_steps: int = 6) -> dict:
            """Bounded registered navigation, reselecting windows after each verified step."""
            return basic_skill.navigate_page(page, max_steps=max_steps)

        @server.tool(name="actions.restore_main_window")
        def actions_restore_main_window(max_steps: int = 6) -> dict:
            """Close known read-only auxiliary content; never cancel editors or close main client."""
            return basic_skill.restore_main_window(max_steps=max_steps)

        @server.tool(name="actions.ensure_contacts_section")
        def actions_ensure_contacts_section() -> dict:
            """Expand only the personal Contacts tree using current header/chevron observations."""
            return basic_skill.ensure_contacts_section()

        @server.tool(name="sync.capture_contact_profile")
        def sync_capture_contact_profile(wechat_id: str, expected_alias: str,
                                         database_path: str = 'data/wechat_contact_profiles.sqlite3') -> dict:
            """Archive explicit fields on a verified profile, preserving unobserved prior fields."""
            result = basic_skill.capture_contact_profile(wechat_id, expected_alias, database_path)
            result['indexing'] = indexer.index_profile_snapshots(database_path)
            return result

        @server.tool(name="vision.prepare_review")
        def vision_prepare_review(operation: str, hwnd: int | None = None, expected_alias: str | None = None) -> dict:
            """Save a private current screenshot and short-lived single-use review plan; no input."""
            return basic_skill.prepare_visual_review(operation, hwnd=hwnd, expected_alias=expected_alias)

        @server.tool(name="actions.apply_review")
        def actions_apply_review(review_id: str, box: list[float], source_page: str) -> dict:
            """Validate an Agent's screenshot box, perform one read-only navigation and verify it."""
            return basic_skill.apply_visual_review(review_id, box, source_page)

        @server.tool(name="actions.page_operation")
        def actions_page_operation(operation: str, hwnd: int | None = None,
                                   expected_page: str | None = None) -> dict:
            """Perform one guarded navigation step; never sends or saves data."""
            return basic_skill.page_operation(operation, hwnd=hwnd, expected_page=expected_page)

        @server.tool(name="vision.observe_page")
        def vision_observe_page(include_ocr: bool = True) -> dict:
            """Observe OCR and theme-adaptive geometry in one frame; never performs actions."""
            return basic_skill.vision.observe_page(include_ocr=include_ocr)

        @server.tool(name="actions.prepare_text")
        def actions_prepare_text(contact: str, text: str) -> dict:
            """Open a chat and prepare text through the sole BasicSkill action path."""
            return basic_skill.execute(action="prepare_text", contact=contact, text=text)

        @server.tool(name="actions.execute_contact")
        def actions_execute_contact(action_id: str, confirmation_id: str) -> dict:
            """Consume an exact stored contact-action confirmation and execute it once."""
            plan = store.consume_pending_action(action_id, confirmation_id)
            try:
                result = basic_skill.execute(
                    action="execute_contact_action", username=plan["username"],
                    contact_action=plan["action"], ui_query=plan["ui_query"],
                    visible_wechat_id=plan.get("visible_wechat_id", ""),
                    value=plan.get("value", ""), confirm=True,
                    confirmation_target=plan["username"],
                )
            except Exception:
                store.finish_pending_action(action_id, succeeded=False)
                raise
            store.finish_pending_action(action_id, succeeded=True)
            return {"action_id": action_id, "result": result}

        @server.tool(name="actions.confirm_contact")
        def actions_confirm_contact(action_id: str) -> dict:
            """Confirm one exact stored contact mutation; this does not execute it."""
            confirmation_id = store.confirm_pending_action(action_id)
            return {"action_id": action_id, "confirmation_id": confirmation_id,
                    "confirmation_is_single_use": True, "executed": False}

        @server.tool(name="reply.send_confirmed")
        def reply_send_confirmed(confirmation_id: str, conversation_id: str,
                                 contact: str, text: str) -> dict:
            """Consume an exact confirmation, then send through BasicSkill."""
            conversation = store.get_conversation(conversation_id)
            if (not conversation or conversation['conversation_type'] != 'direct'
                    or conversation['source_chat_id'] != contact):
                raise PermissionError('Stable recipient does not match the confirmed direct conversation')
            def verify_contact_state() -> None:
                if contact == "filehelper":
                    return
                members = store._connection.execute(
                    "SELECT DISTINCT m.person_id,p.person_type,i.identity_value "
                    "FROM conversation_members m JOIN people p USING(person_id) "
                    "LEFT JOIN person_identities i ON i.person_id=m.person_id "
                    "AND i.identity_type='wxid' AND i.identity_value=? "
                    "WHERE m.conversation_id=? AND m.valid_to IS NULL AND p.person_type<>'self'",
                    (contact, conversation_id),
                ).fetchall()
                if len(members) != 1 or members[0]["person_type"] != "contact" or members[0]["identity_value"] != contact:
                    raise PermissionError("Current contact identity is missing or ambiguous; dispatch stopped")
                state = contact_state.get(members[0]["person_id"])
                if state["presence"] not in {"active", "restored"} or state["automatic_send_blocked"]:
                    raise PermissionError("Recipient relationship state blocks dispatch; review required")

            verify_contact_state()
            trigger = current_reply_trigger(contact)
            with store.atomic():
                draft_id = store.consume_confirmation(confirmation_id, conversation_id, text, expected_trigger=trigger)

            def before_dispatch() -> None:
                if current_reply_trigger(contact) != trigger:
                    raise PermissionError("Conversation changed during preparation; dispatch stopped")
                verify_contact_state()
                store.require_reply_memory_versions(draft_id, conversation_id)

            try:
                result = basic_skill.execute(action="send_text", contact=contact,
                                             text=text, confirm=True, before_dispatch=before_dispatch)
            except Exception:
                store.finish_reply_dispatch(draft_id, sent=False)
                raise
            store.finish_reply_dispatch(draft_id, sent=result.get('sent') is True
                                        and result.get('success') is True,
                                        dispatched=result.get('dispatched') is True)
            return {"draft_id": draft_id, "result": result}

    if conversation_backend is not None:
        @server.tool(name="entities.plan_contact_action")
        def entities_plan_contact_action(username: str, action: str,
                                         value: str = "") -> dict:
            """Resolve a semantic contact action by exact stable username without executing it."""
            plan = conversation_backend.plan_contact_action(username, action, value=value)
            if plan["requires_confirmation"]:
                plan["action_id"] = store.create_pending_action(action, username, plan)
            return plan

        @server.tool(name="monitor.run_once")
        def monitor_run_once(username: str, context_limit: int = 30) -> dict:
            """Archive and process one persistent-cursor pass; an external scheduler invokes it."""
            from wechat_auto.memory.indexer import message_period
            from wechat_auto.storage import make_message_id

            archive_result = None
            if history_db:
                archive_result = conversation_backend.sync_when_notified(username, history_db,
                    **({"voice_model_path": voice_model_path} if voice_model_path else {}))
            saved_cursor = store.get_sync_cursor("reply_monitor", username)
            since_seq = int(saved_cursor or 0)
            update = conversation_backend.poll(username, since_seq, limit=200)
            current = conversation_backend.get_context(username, context_limit)
            conversation = store.ensure_conversation(
                username, conversation_type="group" if username.endswith("@chatroom") else "direct"
            )
            normalized_context = [{
                "chat": username, "conversation_id": conversation,
                "time": str(item.get("create_time", "")),
                "sender": str(item.get("sender_name") or item.get("sender_username") or ""),
                "content": str(item.get("content", "")),
                "id": make_message_id(username, item.get("local_id"), item.get("sort_seq"),
                                      item.get("server_id"), item.get("type")),
            } for item in current]
            reply_context = reply_context_with_versions(conversation, normalized_context)
            with store.atomic():
                committed = int(store.get_sync_cursor("reply_monitor", username) or 0)
                monthly_ids: dict[str, list[str]] = {}
                for item in update["all_messages"]:
                    if int(item.get("sort_seq") or 0) <= committed:
                        continue
                    period = message_period(item.get("create_time"))
                    if period:
                        monthly_ids.setdefault(period, []).append(make_message_id(
                            username, item.get("local_id"), item.get("sort_seq"),
                            item.get("server_id"), item.get("type"),
                        ))
                for period, message_ids in monthly_ids.items():
                    store.queue_month_message_delta(conversation, period, message_ids)
                watermark = max(committed, int(update["watermark"]))
                if watermark > committed:
                    store.set_sync_cursor("reply_monitor", username, watermark)
            new_messages = [item for item in update["messages"] if int(item.get("sort_seq") or 0) > committed]
            return {"username": username, "conversation_id": conversation,
                    "watermark": watermark, "new_messages": new_messages,
                    "reply_context": reply_context, "archive": archive_result,
                    "sent": False, "requires_confirmation": True}

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local WeChat Auto MCP server over stdio")
    parser.add_argument("--memory-db", default="data/wechat_memory.sqlite3")
    parser.add_argument("--memory-root", default="data/memory")
    parser.add_argument("--history-db")
    parser.add_argument("--voice-model-path", help="existing local model for ASR during archive writes")
    parser.add_argument("--moments-db")
    parser.add_argument("--profiles-db")
    parser.add_argument("--secret-dir", default="data/.secrets",
                        help="local DPAPI-protected database keys")
    parser.add_argument("--with-wechat-runtime", action="store_true",
                        help="Attach to the logged-in Weixin client and register confirmed action tools")
    args = parser.parse_args(argv)
    runtime = None
    backend = None
    server = None
    resources = ExitStack()
    health = {"ui": {"status": "not_configured"},
              "conversation_backend": {"status": "not_configured"}}
    try:
        if args.with_wechat_runtime:
            from wechat_auto.backends import DatabaseConversationBackend
            from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db
            from wechat_auto.engine import AgentLoop
            runtime = AgentLoop()
            try:
                runtime.connect()
            except Exception as exc:
                health["ui"] = {"status": "unavailable", "error_type": type(exc).__name__}
                health["conversation_backend"] = {"status": "unavailable", "reason": "ui_unavailable"}
                runtime.disconnect()
                runtime = None
            else:
                health["ui"] = {"status": "available"}
                try:
                    database = resources.enter_context(open_dpapi_wechat_db(
                        args.secret_dir, database_names=('contact.db',), include_message_family=True))
                    backend = DatabaseConversationBackend(database)
                except Exception as exc:
                    health["conversation_backend"] = {
                        "status": "unavailable", "error_type": type(exc).__name__
                    }
                else:
                    health["conversation_backend"] = {"status": "available"}
        server = create_server(
            memory_db=args.memory_db, memory_root=args.memory_root,
            history_db=args.history_db, moments_db=args.moments_db,
            profiles_db=args.profiles_db,
            basic_skill=runtime.basic_skill if runtime else None,
            conversation_backend=backend, voice_model_path=args.voice_model_path,
            runtime_health=health,
        )
        # SDK exception rendering can include request arguments and frame locals.
        for name in ("mcp.server.mcpserver.server", "mcp.server.fastmcp.server", "mcp.server.lowlevel.server"):
            logger = logging.getLogger(name)
            logger.addFilter(_redact_mcp_trace)
            resources.callback(logger.removeFilter, _redact_mcp_trace)
        server.run(transport="stdio")
    finally:
        try:
            try:
                if server is not None:
                    server._wechat_auto_store.close()
            finally:
                resources.close()
        finally:
            if runtime is not None:
                runtime.disconnect()


if __name__ == "__main__":
    main()
