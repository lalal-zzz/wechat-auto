"""wechat-auto — Dual-layer closed-loop AI Agent system for WeChat desktop.

Architecture:
    - Engine (Brain): Closed-loop orchestration (Perceive → Decide → Execute → Reset)
    - Skills (Tier 1): High-level composite skill packages (90% scenarios)
    - Atomic (Tier 2): Native UIA atomic tools (10% fallback)

Quick start::

    from wechat_auto import AgentLoop

    agent = AgentLoop()
    agent.connect()
    agent.run(poll_interval=5.0)  # continuous closed-loop

Or use atomic tools directly::

    from wechat_auto import AgentLoop

    agent = AgentLoop()
    agent.connect()
    # Access Tier 2 tools via router
"""

__version__ = "0.2.0"

from wechat_auto.engine.loop import AgentLoop
from wechat_auto.atomic.tools import AtomicUITools
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.exceptions import (
    WeChatAutoError,
    WeChatNotRunningError,
    WeChatNotFoundError,
    ChatNotFoundError,
    ContactNotFoundError,
    SendMessageError,
    ElementNotFoundError,
    OperationTimeoutError,
    MomentsError,
    EmojiNotFoundError,
    SkillExecutionError,
    AtomicToolError,
    EnvironmentResetError,
)

__all__ = [
    # Main entry point
    "AgentLoop",
    # Tier 2 atomic tools
    "AtomicUITools",
    # Config
    "WeChatConfig",
    "SessionConfig",
    # Exceptions
    "WeChatAutoError",
    "WeChatNotRunningError",
    "WeChatNotFoundError",
    "ChatNotFoundError",
    "ContactNotFoundError",
    "SendMessageError",
    "ElementNotFoundError",
    "OperationTimeoutError",
    "MomentsError",
    "EmojiNotFoundError",
    "SkillExecutionError",
    "AtomicToolError",
    "EnvironmentResetError",
]
