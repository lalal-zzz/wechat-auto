"""wechat-auto — Dual-layer closed-loop AI Agent system for WeChat desktop.

Architecture:
    - Read plane: local encrypted DB -> private offline SQLite
    - Action plane: one BasicSkill; every UI mutation uses HWND messages
    - Observation plane: OCR verifies HWND outcomes and supplies fallback coordinates
    - Composite skills: optional future orchestration, disabled by default

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

__version__ = "0.4.0"

from wechat_auto.engine.loop import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.actions.basic import BasicSkill, BasicLayout
from wechat_auto.actions.composite import CompositeSkill
from wechat_auto.exceptions import (
    WeChatAutoError,
    WeChatNotRunningError,
    ChatNotFoundError,
    SkillExecutionError,
)

__all__ = [
    # Main entry point
    "AgentLoop",
    # Config
    "WeChatConfig",
    "SessionConfig",
    "BasicSkill",
    "BasicLayout",
    "CompositeSkill",
    # Exceptions
    "WeChatAutoError",
    "WeChatNotRunningError",
    "ChatNotFoundError",
    "SkillExecutionError",
]
