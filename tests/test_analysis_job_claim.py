import asyncio
import json

from wechat_auto.mcp_server import create_server


def test_mcp_exact_job_claim_preserves_other_scopes(tmp_path):
    server = create_server(memory_db=str(tmp_path / "memory.sqlite3"),
                           memory_root=str(tmp_path / "memory"))
    store = server._wechat_auto_store
    try:
        other = store.enqueue_job("monthly_analysis", "conversation", "other",
                                  period="2026-09", priority=100)
        target = store.enqueue_job("monthly_analysis", "conversation", "target",
                                   period="2024-06", priority=1)
        result = asyncio.run(server.call_tool("analysis.claim_job", {"job_id": target}))
        payload = result.structured_content or json.loads(result.content[0].text)
        payload = payload.get("result", payload)
        assert payload["job_id"] == target
        assert payload["scope_id"] == "target"
        assert store.next_jobs()[0]["job_id"] == other
    finally:
        store.close()
