"""SkillRouter - decision routing with tiered degradation."""

from __future__ import annotations

import logging
from typing import Any, Callable

from wechat_auto.exceptions import SkillExecutionError, AtomicToolError

logger = logging.getLogger(__name__)


class SkillRouter:
    """Routes intents to Tier 1 skills, degrading to Tier 2 atomic tools on failure.

    Implements Step 2 (Decide & Route) of the closed-loop workflow:
    - Priority: Tier 1 high-level skill packages (90% scenarios)
    - Fallback: Tier 2 atomic UI tools (10% edge cases)
    """

    def __init__(self):
        self._skill_registry: dict[str, Callable] = {}
        self._atomic_tools = None  # Lazy reference to AtomicUITools

    def register_skill(self, name: str, handler: Callable) -> None:
        """Register a Tier 1 skill handler.

        Args:
            name: Skill identifier (e.g. "send_text_message").
            handler: Callable that executes the skill.
        """
        self._skill_registry[name] = handler
        logger.debug("Registered skill: %s", name)

    def set_atomic_tools(self, tools) -> None:
        """Set the Tier 2 atomic tools fallback.

        Args:
            tools: AtomicUITools instance.
        """
        self._atomic_tools = tools

    def route(self, intent: str, params: dict) -> Any:
        """Route an intent to the appropriate execution layer.

        Args:
            intent: The action identifier (maps to a registered skill name).
            params: Parameters to pass to the skill/tool.

        Returns:
            Result of the skill/tool execution.

        Raises:
            SkillExecutionError: If both Tier 1 and Tier 2 fail.
        """
        # Step 1: Try Tier 1 skill
        if intent in self._skill_registry:
            try:
                logger.info("Routing to Tier 1 skill: %s", intent)
                return self._skill_registry[intent](**params)
            except Exception as exc:
                logger.warning(
                    "Tier 1 skill '%s' failed: %s. Degrading to Tier 2.", intent, exc
                )

        # Step 2: Degrade to Tier 2 atomic tools
        if self._atomic_tools is not None:
            try:
                logger.info("Routing to Tier 2 atomic tools for: %s", intent)
                return self._execute_atomic(intent, params)
            except Exception as exc:
                raise SkillExecutionError(
                    f"Both Tier 1 and Tier 2 failed for intent '{intent}': {exc}"
                ) from exc

        raise SkillExecutionError(
            f"No handler found for intent '{intent}' and no atomic tools available."
        )

    def _execute_atomic(self, intent: str, params: dict) -> Any:
        """Execute via Tier 2 atomic tools.

        Maps intent names to atomic tool methods.
        """
        tool_map = {
            "click": self._atomic_tools.click,
            "input_text": self._atomic_tools.input_text,
            "right_click": self._atomic_tools.right_click,
            "scroll": self._atomic_tools.scroll,
            "send_keyboard_shortcut": self._atomic_tools.send_keyboard_shortcut,
            "close_window": self._atomic_tools.close_window,
            "get_ui_tree": self._atomic_tools.get_ui_tree,
        }

        if intent in tool_map:
            return tool_map[intent](**params)

        raise AtomicToolError(f"Unknown atomic intent: {intent}")

    @property
    def available_skills(self) -> list[str]:
        """List all registered Tier 1 skill names."""
        return list(self._skill_registry.keys())
