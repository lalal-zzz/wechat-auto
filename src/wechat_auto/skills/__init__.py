"""Skills module - Tier 1 high-level composite skill packages."""

from wechat_auto.skills.base import BaseSkill
from wechat_auto.skills.messaging import MessagingSkill
from wechat_auto.skills.emoji import EmojiSkill
from wechat_auto.skills.quote import QuoteSkill
from wechat_auto.skills.history import HistorySkill
from wechat_auto.skills.contact import ContactSkill
from wechat_auto.skills.moments import MomentsSkill
from wechat_auto.skills.unread import UnreadSkill
from wechat_auto.skills.group_at import GroupAtSkill
from wechat_auto.skills.channels import ChannelsSkill

__all__ = [
    "BaseSkill",
    "MessagingSkill",
    "EmojiSkill",
    "QuoteSkill",
    "HistorySkill",
    "ContactSkill",
    "MomentsSkill",
    "UnreadSkill",
    "GroupAtSkill",
    "ChannelsSkill",
]
