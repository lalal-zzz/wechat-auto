"""Tests for the AgentLoop engine (unit tests with mocks)."""

from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.engine.loop import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig


class TestAgentLoop:
    def test_init_defaults(self):
        agent = AgentLoop()
        assert agent._config is not None
        assert agent._session is not None
        assert agent.is_connected is False

    def test_init_custom_config(self):
        cfg = WeChatConfig(backend="win32")
        agent = AgentLoop(config=cfg)
        assert agent._config.backend == "win32"

    def test_not_connected_raises_on_finder(self):
        agent = AgentLoop()
        with pytest.raises(RuntimeError, match="Not connected"):
            _ = agent.finder

    def test_not_connected_raises_on_router(self):
        agent = AgentLoop()
        with pytest.raises(RuntimeError, match="Not connected"):
            _ = agent.router

    def test_not_connected_raises_on_healer(self):
        agent = AgentLoop()
        with pytest.raises(RuntimeError, match="Not connected"):
            _ = agent.healer

    @patch("wechat_auto.engine.loop.Application")
    def test_connect_calls_app_connect(self, MockApp):
        mock_app_instance = MockApp.return_value
        mock_app_instance.connect.return_value = mock_app_instance

        agent = AgentLoop(session=SessionConfig(auto_activate=False))
        with patch.object(agent, "_init_engine"):
            agent.connect()

        mock_app_instance.connect.assert_called_once()
