"""Exercise the real stdio transport with isolated local storage."""

import asyncio
import json
import sqlite3
import sys
from contextlib import closing

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from wechat_auto.mcp_server import create_server
from wechat_auto.memory import MarkdownMemory, MemoryStore
from wechat_auto.memory.analysis import AnalysisService
from wechat_auto.storage import HistoryStore
from wechat_auto.storage.voice_transcription import VoiceTranscriptions


def test_stdio_tool_exception_log_excludes_private_request_arguments(tmp_path):
    marker = "synthetic-private-reply-marker"
    log_path = tmp_path / "stderr.log"

    async def run():
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "wechat_auto.mcp_server", "--memory-db", str(tmp_path / "memory.sqlite3"),
            "--memory-root", str(tmp_path / "memory"),
        ])
        with log_path.open("w", encoding="utf-8") as log:
            async with (stdio_client(params, errlog=log) as (reader, writer),
                        ClientSession(reader, writer, read_timeout_seconds=20) as session):
                await session.initialize()
                result = await session.call_tool("reply.create_draft", {
                    "conversation_id": marker, "trigger_evidence_id": marker, "text": marker,
                    "context_fingerprint": marker, "expected_memory_version_fingerprint": marker,
                })
                assert result.is_error
                assert not (await session.call_tool("status.summary", {})).is_error

    asyncio.run(run())
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "MCP request failed" in log_text
    assert marker not in log_text
    assert "Traceback" not in log_text


def test_protected_rollup_holds_archive_writer_lock_during_publication(tmp_path, monkeypatch):
    history_path = tmp_path / "history.sqlite3"
    with HistoryStore(history_path) as archive:
        archive._connection.execute("PRAGMA journal_mode=WAL")
        archive.save_messages([{"id": "first", "chat": "wxid_test_one", "time": "2026-09-01"}])
        server = create_server(memory_db=str(tmp_path / "memory.sqlite3"),
                               memory_root=str(tmp_path / "memory"), history_db=str(history_path))

        async def call(name, args):
            reply = await server.call_tool(name, args)
            assert not reply.is_error
            value = reply.structured_content or json.loads(reply.content[0].text)
            return value["result"] if isinstance(value, dict) and set(value) == {"result"} else value

        async def check():
            await call("sync.index_archives", {})
            conversation = (await call("entities.conversations", {}))[0]["conversation_id"]
            snapshot = archive.month_message_snapshot("wxid_test_one", "2026-09")
            base = {"scope_type": "conversation", "scope_id": conversation, "evidence_ids": ["first"],
                    "template_version": "synthetic"}
            await call("analysis.submit", {**base, "period": "2026-09", "markdown_text": "# Month",
                                          "expected_message_snapshot": snapshot})
            submit = AnalysisService.submit

            def check_writer_lock(service, **kwargs):
                with (closing(sqlite3.connect(history_path, timeout=0)) as writer,
                      pytest.raises(sqlite3.OperationalError, match="database is locked")):
                    writer.execute("BEGIN IMMEDIATE")
                return submit(service, **kwargs)

            monkeypatch.setattr(AnalysisService, "submit", check_writer_lock)
            result = await call("analysis.submit", {**base, "markdown_text": "# Rollup",
                                                    "expected_upstream_month_versions": {"2026-09": 1}})
            assert result["version"] == 1

        try:
            asyncio.run(check())
            assert archive.save_messages([{"id": "late", "chat": "wxid_test_one", "time": "2026-10-01"}]) == 1
        finally:
            server._wechat_auto_store.close()


def test_stdio_analysis_commit_persists_complete_version_and_facts(tmp_path):
    history = tmp_path / 'history.sqlite3'
    with HistoryStore(history) as archive:
        archive.save_messages([{'id': 'synthetic-evidence', 'chat': 'wxid_test_one',
                                'content': 'synthetic source', 'time': '2026-09-01 10:00:00'}])

    async def run():
        parameters = StdioServerParameters(command=sys.executable, args=[
            '-m', 'wechat_auto.mcp_server', '--memory-db', str(tmp_path / 'memory.sqlite3'),
            '--memory-root', str(tmp_path / 'memory'), '--history-db', str(history)])
        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer, read_timeout_seconds=15) as session,
        ):
            await session.initialize()

            async def call(name, arguments):
                response = await session.call_tool(name, arguments)
                assert not response.is_error
                value = response.structured_content or json.loads(response.content[0].text)
                return value['result'] if isinstance(value, dict) and set(value) == {'result'} else value

            await call('sync.index_archives', {})
            conversation = (await call('entities.conversations', {}))[0]['conversation_id']
            rollup = {'conversation_id': conversation, 'require_current_months': True}
            assert (await session.call_tool('analysis.get_conversation_input', rollup)).is_error
            month = {'conversation_id': conversation, 'period': '2026-09'}
            snapshot = (await call('analysis.get_month_input', month))['message_snapshot']
            arguments = {'scope_type': 'conversation', 'scope_id': conversation, 'period': '2026-09',
                         'markdown_text': '# Synthetic analysis\n\nComplete synthetic body.',
                         'evidence_ids': ['synthetic-evidence'], 'template_version': 'synthetic',
                         'claims': [{'canonical_text': 'synthetic fact', 'claim_type': 'fact',
                                     'evidence': [{'evidence_id': 'synthetic-evidence'}]}],
                         'events': [{'title': 'synthetic event'}],
                         'coverage': {'message_watermark': 'synthetic-evidence'}, 'expected_parent': 0,
                         'expected_message_snapshot': snapshot}
            result = await call('analysis.submit', arguments)
            assert result['version'] == 1
            scope_status = await call('analysis.scope_status', {
                'scope_type': 'conversation', 'scope_id': conversation, 'period': '2026-09'
            })
            assert scope_status['source_freshness'] == scope_status['dependency_readiness'] == 'unknown'
            assert scope_status['archive_comparison'] == 'matches'
            assert scope_status['nodes'][0]['version'] == 1
            assert scope_status['nodes'][0]['message_watermark'] == 'synthetic-evidence'
            assert (await call('analysis.get_conversation_input', rollup))['months'][0]['period'] == '2026-09'
            arguments['expected_parent'] = 1
            repeated = await call('analysis.submit', arguments)
            assert repeated['changed'] is False
            directory = tmp_path / 'memory/conversations' / conversation / 'months/2026-09'
            candidate = directory / 'versions/v000002.md'
            candidate.write_text('# Uncommitted\nsynthetic candidate', encoding='utf-8')
            (directory / 'current.md').write_bytes(candidate.read_bytes())
            recovery_arguments = {'scope_type': 'conversation', 'scope_id': conversation, 'period': '2026-09'}
            recovery = await call('memory.recover_publication', recovery_arguments)
            assert recovery['changed'] and recovery['promoted'] is False
            assert (await call('memory.recover_publication', recovery_arguments))['changed'] is False
            retained = list((tmp_path / 'work/analysis').glob('*/versions/v000002.md'))
            assert len(retained) == 1 and retained[0].read_text(encoding='utf-8').startswith('# Uncommitted')
            counts = (await call('status.summary', {}))['counts']
            assert counts['claims'] == counts['events'] == counts['analysis_versions'] == 1
            with MemoryStore(tmp_path / 'memory.sqlite3') as store:
                person_id = store._connection.execute(
                    "SELECT person_id FROM person_identities WHERE identity_value='wxid_test_one'"
                ).fetchone()[0]
            person_input = {'person_id': person_id, 'require_current_months': True}
            assert (await session.call_tool('analysis.get_person_input', person_input)).is_error
            verified_rollup = await call('analysis.get_conversation_input', rollup)
            rollup_submission = {'scope_type': 'conversation', 'scope_id': conversation,
                                 'markdown_text': '# Synthetic rollup', 'evidence_ids': ['synthetic-evidence'],
                                 'template_version': 'synthetic',
                                 'expected_upstream_month_versions': verified_rollup['upstream_month_versions']}
            assert (await session.call_tool('analysis.submit', {
                **rollup_submission, 'expected_upstream_month_versions': {'2026-09': 2},
            })).is_error
            assert (await call('analysis.submit', rollup_submission))['version'] == 1
            assert not (await call('analysis.submit', rollup_submission))['changed']
            assert (await call('analysis.get_person_input', person_input))['conversations'][0]['version'] == 1
            person_versions = (await call('analysis.get_person_input', person_input))['upstream_conversation_versions']
            person_submission = {'scope_type': 'person', 'scope_id': person_id, 'markdown_text': '# Synthetic person',
                                 'evidence_ids': ['synthetic-evidence'], 'template_version': 'synthetic',
                                 'expected_upstream_conversation_versions': person_versions}
            assert (await call('analysis.submit', person_submission))['version'] == 1
            assert not (await call('analysis.submit', person_submission))['changed']
            assert (await call('analysis.submit', {**arguments, 'template_version': 'synthetic-revised',
                                                    'claims': [], 'events': []}))['version'] == 2
            assert (await session.call_tool('analysis.get_person_input', person_input)).is_error
            assert (await session.call_tool('analysis.submit', rollup_submission)).is_error
            refreshed = {**rollup_submission, 'expected_upstream_month_versions': {'2026-09': 2}}
            assert (await call('analysis.submit', refreshed))['version'] == 2
            assert (await call('analysis.get_person_input', person_input))['conversations'][0]['version'] == 2
            assert (await session.call_tool('analysis.submit', person_submission)).is_error
            person_submission['expected_upstream_conversation_versions'] = {conversation: 2}
            assert (await call('analysis.submit', person_submission))['version'] == 2
            with HistoryStore(history) as archive:
                archive.save_messages([{'id': 'other-month', 'chat': 'wxid_test_one',
                                        'content': 'other month', 'time': '2026-10-01 10:00:00'}])
                assert (await call('analysis.get_month_input', month))['message_snapshot'] == snapshot
                assert (await session.call_tool('analysis.get_conversation_input', rollup)).is_error
                assert (await session.call_tool('analysis.get_person_input', person_input)).is_error
                assert (await session.call_tool('analysis.submit', rollup_submission)).is_error
                archive.save_messages([{'id': 'late-old-message', 'chat': 'wxid_test_one',
                                        'content': 'backfill', 'time': '2026-09-01 09:00:00',
                                        'raw': {'type': 34}}])
            stale_page = await session.call_tool('analysis.get_month_input', {
                **month, 'after_id': 'synthetic-evidence', 'expected_message_snapshot': snapshot,
            })
            assert stale_page.is_error
            assert (await session.call_tool('analysis.submit', arguments)).is_error
            before_transcription = (await call('analysis.get_month_input', month))['message_snapshot']
            with HistoryStore(history) as archive:
                assert VoiceTranscriptions(archive).save('late-old-message', 'synthetic transcript',
                                                          engine='user_corrected', source_ref='test')
            revised = await call('analysis.get_month_input', month)
            assert revised['message_snapshot'] != before_transcription
            assert revised['messages'][-1]['transcription']['text'] == 'synthetic transcript'
            arguments['expected_message_snapshot'] = before_transcription
            assert (await session.call_tool('analysis.submit', arguments)).is_error
            status = await call('analysis.scope_status', {'scope_type': 'conversation',
                                'scope_id': conversation, 'period': '2026-09'})
            assert status['nodes'][0]['version'] == 2
            assert status['archive_comparison'] == 'changed'
            assert (await session.call_tool('analysis.get_conversation_input', rollup)).is_error
            assert (await session.call_tool('analysis.get_person_input', person_input)).is_error
            history.rename(history.with_suffix('.unavailable'))
            status = await call('analysis.scope_status', {'scope_type': 'conversation',
                                'scope_id': conversation, 'period': '2026-09'})
            assert status['archive_comparison'] == 'unknown'
            assert not history.exists()
            return conversation

    conversation = asyncio.run(asyncio.wait_for(run(), timeout=30))
    with MemoryStore(tmp_path / 'memory.sqlite3') as store:
        memory = MarkdownMemory(tmp_path / 'memory', store)
        assert 'Complete synthetic body.' in memory.read_current('conversation', conversation, '2026-09')

def test_stdio_cold_start_restart_and_readonly_tools(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        scoped_job = store.enqueue_job("monthly_analysis", "conversation", "synthetic-chat", period="2026-09")
        other_job = store.enqueue_job("monthly_analysis", "conversation", "synthetic-chat", period="2026-10",
                                      priority=100)

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "wechat_auto.mcp_server", "--memory-db",
                  str(tmp_path / "memory.sqlite3"), "--memory-root",
                  str(tmp_path / "memory")],
        )
        snapshots = []
        for iteration in range(2):
            async with (
                stdio_client(parameters) as (reader, writer),
                ClientSession(reader, writer, read_timeout_seconds=15) as session,
            ):
                await session.initialize()
                listing = await session.list_tools()
                names = {tool.name for tool in listing.tools}
                assert "status.summary" in names
                assert "reply.send_confirmed" not in names
                result = await session.call_tool("status.summary", {})
                assert not result.is_error
                snapshots.append(result.structured_content or json.loads(result.content[0].text))
                catalog = await session.call_tool("vision.page_catalog", {})
                assert not catalog.is_error
                payload = catalog.structured_content or json.loads(catalog.content[0].text)
                assert len(payload["pages"]) >= 49
                unavailable = await session.call_tool("analysis.queue_initial", {})
                assert unavailable.is_error
                # A dependency error must not terminate the transport or hide status.
                healthy = await session.call_tool("status.summary", {})
                assert not healthy.is_error
                if iteration == 1:
                    async def claim(arguments):
                        reply = await session.call_tool("analysis.claim_job", arguments)
                        assert not reply.is_error
                        value = reply.structured_content
                        if value is None and reply.content:
                            value = json.loads(reply.content[0].text)
                        return value["result"] if isinstance(value, dict) and set(value) == {"result"} else value

                    scope = {"scope_type": "conversation", "scope_id": "synthetic-chat", "period": "2026-09"}
                    assert (await claim(scope))["job_id"] == scoped_job
                    assert await claim(scope) in (None, {})
                    assert (await claim({}))["job_id"] == other_job
        assert snapshots[0] == snapshots[1]

    asyncio.run(asyncio.wait_for(run(), timeout=45))


@pytest.mark.parametrize('failure', ['connect', 'backend'])
def test_stdio_dependency_failure_preserves_status_and_available_tools(tmp_path, failure):
    code = """
from unittest.mock import MagicMock, patch
from wechat_auto.mcp_server import main
runtime = MagicMock()
if FAILURE == 'connect':
    runtime.connect.side_effect = RuntimeError('private diagnostic detail')
with patch('wechat_auto.engine.AgentLoop', return_value=runtime), patch(
    'wechat_auto.backends.dpapi_db.open_dpapi_wechat_db'
), patch(
    'wechat_auto.backends.DatabaseConversationBackend',
    side_effect=RuntimeError('private database detail')
):
    main()
""".replace('FAILURE', repr(failure))

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=['-c', code, '--with-wechat-runtime', '--memory-db',
                  str(tmp_path / 'memory.sqlite3'), '--memory-root', str(tmp_path / 'memory')],
        )
        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer, read_timeout_seconds=15) as session,
        ):
            await session.initialize()
            result = await session.call_tool('status.summary', {})
            assert not result.is_error
            payload = result.structured_content or json.loads(result.content[0].text)
            health = payload['runtime']
            assert health['ui']['status'] == ('unavailable' if failure == 'connect' else 'available')
            assert health['conversation_backend']['status'] == 'unavailable'
            assert 'private' not in repr(health)
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert 'status.summary' in names
            assert 'monitor.run_once' not in names
            assert ('vision.inspect_windows' in names) == (failure == 'backend')

    asyncio.run(asyncio.wait_for(run(), timeout=30))
