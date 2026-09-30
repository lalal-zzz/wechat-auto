"""wechat-auto — Dual-layer closed-loop AI Agent system for WeChat desktop.

Architecture:
    - Read plane: local encrypted DB -> private offline SQLite
    - Action plane: one BasicSkill; every UI mutation uses HWND messages
    - Observation plane: OCR verifies HWND outcomes and supplies fallback coordinates
    - Analysis orchestration: MCP tools and repository Skills above BasicSkill

Quick start::

    from wechat_auto import AgentLoop

    agent = AgentLoop()
    agent.connect()
    agent.run(poll_interval=5.0)  # continuous closed-loop

Or dispatch a primitive HWND action::

    from wechat_auto import AgentLoop

    agent = AgentLoop()
    agent.connect()
    agent.router.route("basic_action", {"action": "open_chat", "contact": "文件传输助手"})
"""

from wechat_auto.actions.basic import BasicLayout, BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.engine.loop import AgentLoop
from wechat_auto.exceptions import (
    ChatNotFoundError,
    SkillExecutionError,
    WeChatAutoError,
    WeChatNotRunningError,
)
from wechat_auto.version import __version__

__all__ = [
    # Main entry point
    "AgentLoop",
    "BasicLayout",
    "BasicSkill",
    "ChatNotFoundError",
    "SessionConfig",
    "SkillExecutionError",
    # Exceptions
    "WeChatAutoError",
    # Config
    "WeChatConfig",
    "WeChatNotRunningError",
    "__version__",
]
