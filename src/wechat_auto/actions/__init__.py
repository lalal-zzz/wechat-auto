"""Public UI action API."""

from wechat_auto.actions.base import BaseSkill
from wechat_auto.actions.basic import BasicSkill
from wechat_auto.actions.semantics import ContactActionPlan, PageId, semantic_key

__all__ = [
    "BaseSkill",
    "BasicSkill",
    "ContactActionPlan",
    "PageId",
    "semantic_key",
]
