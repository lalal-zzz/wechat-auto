"""Contract for future high-level workflow skills.

Composite skills may read offline backends and orchestrate BasicSkill, but
must not introduce a second UI transport. No concrete composite is registered
in the default runtime yet.
"""
from __future__ import annotations

from typing import Any


class CompositeSkill:
    """Future workflow wrapper around one shared BasicSkill instance."""

    name = "composite"

    def __init__(self, basic_skill, *, conversation_backend=None, moments_backend=None):
        self.basic = basic_skill
        self.conversations = conversation_backend
        self.moments = moments_backend

    def execute(self, **params) -> Any:
        raise NotImplementedError(
            "High-level composite skills are intentionally not implemented yet"
        )
