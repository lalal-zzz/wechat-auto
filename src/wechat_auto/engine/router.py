"""Small explicit registry for current skills."""
from __future__ import annotations

from typing import Any, Callable

from wechat_auto.exceptions import SkillExecutionError


class SkillRouter:
    def __init__(self):
        self._skill_registry: dict[str, Callable] = {}

    def register_skill(self, name: str, handler: Callable) -> None:
        self._skill_registry[name] = handler

    def route(self, intent: str, params: dict) -> Any:
        handler = self._skill_registry.get(intent)
        if handler is None:
            raise SkillExecutionError(f"No handler found for intent '{intent}'")
        try:
            return handler(**params)
        except Exception as exc:
            raise SkillExecutionError(f"Skill '{intent}' failed: {exc}") from exc

    @property
    def available_skills(self) -> list[str]:
        return list(self._skill_registry)
