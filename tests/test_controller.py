from unittest.mock import patch

import pytest

from wechat_auto.config import SessionConfig
from wechat_auto.engine.loop import AgentLoop


def test_router_requires_connection():
    with pytest.raises(RuntimeError, match="Not connected"):
        _ = AgentLoop().router


@patch("wechat_auto.engine.loop.Application")
def test_connect_registers_only_basic_skill(application):
    application.return_value.is_connected.return_value = True
    agent = AgentLoop(session=SessionConfig(auto_activate=False)).connect()
    assert agent.router.available_skills == ["basic_action"]


@patch("wechat_auto.engine.loop.Application")
def test_default_step_does_not_poll_ui(application):
    application.return_value.is_connected.return_value = True
    agent = AgentLoop(session=SessionConfig(auto_activate=False)).connect()
    assert agent.step()["observer"] == "not_configured"
