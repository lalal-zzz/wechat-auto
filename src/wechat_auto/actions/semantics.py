"""Stable project-owned semantic IDs for self-drawn Weixin pages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum

from wechat_auto.version import CONTACT_ACTION_PROTOCOL_VERSION


class PageId(IntEnum):
    UNKNOWN = 0
    LOGIN = 1
    LOCKED = 2
    CONNECTION_ERROR = 3
    MAIN_EMPTY = 10
    CHAT = 11
    GROUP_CHAT = 12
    SEARCH = 13
    CHAT_HISTORY = 14
    MESSAGE_MENU = 15
    EMOJI_PANEL = 16
    MEDIA_VIEWER = 17
    FILE_PREVIEW = 18
    DISCOVER = 19
    CONTACTS = 20
    CONTACT_PROFILE = 21
    CONTACT_MORE = 22
    CONTACT_REMARK = 23
    CONTACT_PERMISSIONS = 24
    CONTACT_TAGS = 25
    NEW_FRIENDS = 26
    CHAT_DETAILS = 27
    GROUP_LIST = 30
    GROUP_DETAILS = 31
    GROUP_MEMBERS = 32
    GROUP_ANNOUNCEMENT = 33
    GROUP_NAME = 34
    GROUP_INVITE = 35
    MOMENTS_FEED = 40
    MOMENTS_PERSON = 41
    MOMENTS_DETAIL = 42
    MOMENTS_COMMENT = 43
    MOMENTS_PUBLISH = 44
    MOMENTS_MENU = 45
    OFFICIAL_ACCOUNTS = 50
    ARTICLE = 51
    CHANNELS = 52
    CHANNELS_LIVE = 53
    WEB_SEARCH = 54
    MINI_PROGRAM = 55
    SETTINGS = 60
    FILE_TRANSFER = 61
    FAVORITES = 62
    MAIN_MENU = 63
    MINI_PROGRAM_LIST = 64
    SEARCH_SUGGESTIONS = 65
    CALL = 70
    CONFIRM_DIALOG = 90
    FILE_PICKER = 91
    ERROR_DIALOG = 92


ELEMENTS: dict[PageId, dict[int, str]] = {
    PageId.CONTACT_PROFILE: {
        1: "back", 2: "avatar", 3: "remark", 4: "wechat_id",
        5: "permissions", 6: "moments", 7: "message", 8: "video_call", 9: "more",
    },
    PageId.CONTACT_MORE: {1: "recommend", 2: "report", 3: "delete_contact"},
    PageId.CONTACT_REMARK: {1: "remark_input", 2: "save"},
    PageId.CONFIRM_DIALOG: {1: "cancel", 2: "confirm"},
}


def semantic_key(page: int | PageId, element: int) -> str:
    try:
        page_id = PageId(page)
        name = ELEMENTS[page_id][int(element)]
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Unknown semantic element {int(page):02d}.{int(element):02d}") from exc
    return f"{int(page_id):02d}.{int(element):02d}:{name}"


@dataclass(frozen=True)
class ContactActionPlan:
    username: str
    action: str
    ui_query: str
    visible_wechat_id: str = ""
    value: str = ""
    requires_confirmation: bool = True
    protocol_version: int = CONTACT_ACTION_PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return asdict(self)
