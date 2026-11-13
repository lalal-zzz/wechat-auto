"""Runtime startup failures must release resources already acquired."""

from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.mcp_server import main


@pytest.mark.parametrize("failure", ["connect", "backend", "server", "run", None])
def test_main_cleans_up_runtime_on_each_startup_boundary(failure):
    runtime = MagicMock()
    server = MagicMock()
    error = RuntimeError("simulated startup failure")
    if failure == "connect":
        runtime.connect.side_effect = error
    if failure == "run":
        server.run.side_effect = error
    with (
        patch("wechat_auto.engine.AgentLoop", return_value=runtime),
        patch("wechat_auto.backends.dpapi_db.open_dpapi_wechat_db") as database_context,
        patch("wechat_auto.backends.DatabaseConversationBackend",
              side_effect=error if failure == "backend" else None),
        patch("wechat_auto.mcp_server.create_server", return_value=server,
              side_effect=error if failure == "server" else None) as factory,
    ):
        if failure in {"server", "run"}:
            with pytest.raises(RuntimeError, match="simulated startup failure"):
                main(["--with-wechat-runtime"])
        else:
            main(["--with-wechat-runtime"])
    if failure in {"connect", "backend", None}:
        parameters = factory.call_args.kwargs
        health = parameters["runtime_health"]
        assert health["ui"]["status"] == ("unavailable" if failure == "connect" else "available")
        assert health["conversation_backend"]["status"] == (
            "unavailable" if failure in {"connect", "backend"} else "available"
        )
        if failure == "connect":
            assert parameters["basic_skill"] is None
        if failure in {"connect", "backend"}:
            assert parameters["conversation_backend"] is None
        assert "simulated startup failure" not in repr(health)
    runtime.disconnect.assert_called_once()
    if failure != 'connect':
        database_context.return_value.__exit__.assert_called_once()
    if failure in {"connect", "backend", "run", None}:
        server._wechat_auto_store.close.assert_called_once()
    else:
        server._wechat_auto_store.close.assert_not_called()


def test_main_closes_memory_without_wechat_runtime():
    server = MagicMock()
    with patch("wechat_auto.mcp_server.create_server", return_value=server):
        main([])
    server.run.assert_called_once_with(transport="stdio")
    server._wechat_auto_store.close.assert_called_once()
