"""Local stdio MCP surface for WeChat memory and confirmed actions."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
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


def create_server(*, memory_db: str, memory_root: str,
                  history_db: str | None = None, moments_db: str | None = None,
                  profiles_db: str | None = None, basic_skill=None,
                  conversation_backend=None):
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
    analysis = AnalysisService(store, markdown)
    context = ContextBuilder(store)
    evidence = EvidenceResolver(history_path=history_db, moments_path=moments_db,
                                profiles_path=profiles_db)
    indexer = ArchiveIndexer(store)
    dashboard = DashboardBuilder(store, Path(memory_root) / "dashboard")

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

    @server.tool(name="analysis.get_month_input")
    def analysis_get_month_input(conversation_id: str, period: str,
                                 after_id: str = "", limit: int = 1000) -> dict:
        """Read one bounded raw month page for an explicitly claimed analysis job."""
        if not history_db:
            raise RuntimeError("history database is not configured")
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError("conversation not found")
        from wechat_auto.storage import HistoryStore
        with HistoryStore(history_db) as history:
            messages = history.fetch_month(conversation["source_chat_id"], period,
                                           after_id=after_id, limit=limit)
        return {"conversation_id": conversation_id, "period": period,
                "messages": messages, "count": len(messages),
                "next_after_id": messages[-1]["id"] if len(messages) == limit else ""}

    @server.tool(name="analysis.get_conversation_input")
    def analysis_get_conversation_input(conversation_id: str) -> dict:
        """Read current monthly memories for a cross-month conversation rollup."""
        periods = markdown.list_periods(conversation_id)
        return {"conversation_id": conversation_id, "months": [
            {"period": period,
             "memory": markdown.read_current("conversation", conversation_id, period)}
            for period in periods
        ]}

    @server.tool(name="analysis.get_person_input")
    def analysis_get_person_input(person_id: str, claim_limit: int = 100) -> dict:
        """Read compact cross-context inputs for one person's incremental analysis."""
        conversations = store.person_conversations(person_id)
        return {"person_id": person_id, "claims": context.compact_claims(
                    person_id=person_id, limit=claim_limit),
                "conversations": [{"conversation": item,
                    "memory": markdown.read_current("conversation", item["conversation_id"])}
                    for item in conversations],
                "current_person_memory": markdown.read_current("person", person_id)}

    @server.tool(name="analysis.claim_job")
    def analysis_claim_job(worker_id: str = "agent") -> dict | None:
        """Atomically claim one analysis job so agents do not duplicate work."""
        return store.claim_next_job(worker_id=worker_id)

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
                        expected_parent: int | None = None) -> dict:
        """Commit structured results and one compact full Markdown version atomically."""
        return analysis.submit(
            scope_type=scope_type, scope_id=scope_id, period=period,
            markdown=markdown_text, evidence_ids=evidence_ids,
            template_version=template_version, claims=claims or (), events=events or (),
            coverage=coverage, mode=mode, expected_parent=expected_parent,
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
                           expires_at: str = "") -> dict:
        """Save a reply candidate without touching WeChat."""
        draft_id = store.create_reply_draft(conversation_id, trigger_evidence_id, text,
                                            context_fingerprint, expires_at or None)
        return {"draft_id": draft_id, "sent": False, "requires_confirmation": True}

    @server.tool(name="reply.build_context")
    def reply_build_context(conversation_id: str, current_messages: list[dict],
                            person_id: str = "", claim_limit: int = 20) -> dict:
        """Build compact reply context; raw historical evidence remains collapsed."""
        return context.reply_context(conversation_id, current_messages,
                                     person_id=person_id or None, claim_limit=claim_limit)

    @server.tool(name="reply.confirm")
    def reply_confirm(draft_id: str) -> dict:
        """Confirm one exact saved draft; this still does not send it."""
        confirmation_id = store.confirm_reply_draft(draft_id)
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
            draft_id = store.consume_confirmation(confirmation_id, conversation_id, text)
            try:
                result = basic_skill.execute(action="send_text", contact=contact,
                                             text=text, confirm=True)
            except Exception:
                store.finish_reply_dispatch(draft_id, sent=False)
                raise
            store.finish_reply_dispatch(draft_id, sent=True)
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

            archive_result = None
            if history_db:
                archive_result = conversation_backend.sync_when_notified(username, history_db)
            saved_cursor = store.get_sync_cursor("reply_monitor", username)
            since_seq = int(saved_cursor or 0)
            update = conversation_backend.poll(username, since_seq, limit=200)
            current = conversation_backend.get_context(username, context_limit)
            conversation = store.ensure_conversation(
                username, conversation_type="group" if username.endswith("@chatroom") else "direct"
            )
            for item in update["all_messages"]:
                period = message_period(item.get("create_time"))
                if not period:
                    continue
                message_id = str(item.get("server_id") or item.get("local_id") or item.get("sort_seq"))
                analysis.mark_message_delta(conversation, period, message_id)
            store.set_sync_cursor("reply_monitor", username, update["watermark"])
            normalized_context = [{
                "time": str(item.get("create_time", "")),
                "sender": str(item.get("sender_name") or item.get("sender_username") or ""),
                "content": str(item.get("content", "")),
            } for item in current]
            reply_context = context.reply_context(conversation, normalized_context)
            return {"username": username, "conversation_id": conversation,
                    "watermark": update["watermark"], "new_messages": update["messages"],
                    "reply_context": reply_context, "archive": archive_result,
                    "sent": False, "requires_confirmation": True}

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local WeChat Auto MCP server over stdio")
    parser.add_argument("--memory-db", default="data/wechat_memory.sqlite3")
    parser.add_argument("--memory-root", default="data/memory")
    parser.add_argument("--history-db")
    parser.add_argument("--moments-db")
    parser.add_argument("--profiles-db")
    parser.add_argument("--with-wechat-runtime", action="store_true",
                        help="Attach to the logged-in Weixin client and register confirmed action tools")
    args = parser.parse_args(argv)
    runtime = None
    backend = None
    if args.with_wechat_runtime:
        from wechat_auto.backends import DatabaseConversationBackend
        from wechat_auto.engine import AgentLoop
        runtime = AgentLoop().connect()
        backend = DatabaseConversationBackend()
    server = create_server(
        memory_db=args.memory_db, memory_root=args.memory_root,
        history_db=args.history_db, moments_db=args.moments_db,
        profiles_db=args.profiles_db,
        basic_skill=runtime.basic_skill if runtime else None,
        conversation_backend=backend,
    )
    try:
        server.run(transport="stdio")
    finally:
        if runtime is not None:
            runtime.disconnect()


if __name__ == "__main__":
    main()
