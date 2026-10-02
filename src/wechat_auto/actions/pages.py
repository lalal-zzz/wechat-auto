"""Versioned page capabilities and deterministic, guarded navigation contracts."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass

from wechat_auto.primitives.page_catalog import PAGES

PAGE_ACTION_VERSION = 4


@dataclass(frozen=True)
class PageOperation:
    name: str
    sources: tuple[str, ...]
    targets: tuple[str, ...] = ()
    method: str = "visual_control"
    anchors: tuple[str, ...] = ()
    confirmation_required: bool = False
    executable: bool = True
    require_source_exit: bool = False


MAIN_PAGES = ("chat", "group_chat", "file_transfer", "contacts", "contact_profile",
              "discover", "moments_feed", "channels", "web_search", "mini_program_list",
              "official_accounts", "favorites", "new_friends", "main_without_selected_chat")
OPERATIONS = (
    PageOperation("open_contacts", MAIN_PAGES, ("contacts", "contact_profile", "new_friends")),
    PageOperation("open_chats", MAIN_PAGES, ("chat", "group_chat", "file_transfer", "main_without_selected_chat")),
    PageOperation("open_discover", MAIN_PAGES, ("discover", "moments_feed", "channels", "web_search", "mini_program_list")),
    PageOperation("open_main_menu", MAIN_PAGES, ("main_menu",)),
    PageOperation("open_moments", ("discover", "channels", "web_search", "mini_program_list"),
                  ("moments_feed",), "ocr", ("朋友圈",)),
    PageOperation("open_channels", ("discover", "moments_feed", "web_search", "mini_program_list"),
                  ("channels",), "ocr", ("视频号",)),
    PageOperation("open_web_search", ("discover", "moments_feed", "channels", "mini_program_list"),
                  ("web_search",), "ocr", ("搜一搜",)),
    PageOperation("open_mini_programs", ("discover", "moments_feed", "channels", "web_search"),
                  ("mini_program_list",), "ocr", ("小程序",)),
    PageOperation("open_contact_more", ("contact_profile",), ("contact_more",)),
    PageOperation("open_contact_moments", ("contact_profile",), ("moments_person",),
                  "ocr", ("朋友圈", "相册")),
    PageOperation("open_remark_editor", ("contact_more",), ("contact_remark",), "ocr", ("设置备注和标签",)),
    PageOperation("open_permissions", ("contact_more",), ("contact_permissions",), "ocr", ("设置朋友权限",)),
    PageOperation("open_settings", ("main_menu",), ("settings",), "ocr", ("设置",)),
    PageOperation("open_favorites", MAIN_PAGES, ("favorites",)),
    PageOperation("open_group_details", ("group_chat",), ("group_details",)),
    PageOperation("open_chat_details", ("chat", "file_transfer"), ("chat_details",)),
    PageOperation("open_history", ("chat", "group_chat", "file_transfer"), ("chat_history",)),
    PageOperation("open_emoji_panel", ("chat", "group_chat", "file_transfer"), ("emoji_panel",)),
    PageOperation("close_content_tab", ("web_search", "article", "channels", "mini_program", "official_accounts"),
                  MAIN_PAGES, method="tab_close", require_source_exit=True),
    # Editor cancellation discards local draft fields; explicit UI cancel only.
    PageOperation("cancel", ("contact_remark", "contact_permissions", "contact_tags",
                             "moments_comment", "group_name", "group_announcement", "group_invite"),
                  method="ocr_cancel", anchors=("取消",)),
    PageOperation("dismiss", ("contact_more", "main_menu", "message_menu", "moments_menu"),
                  method="escape"),
    PageOperation("close", ("settings", "media_viewer", "file_preview", "moments_person",
                            "moments_detail", "channels", "mini_program", "chat_history"),
                  method="wm_close"),
)

MUTATIONS = {
    "chat": ("send_text", "send_file", "send_sticker"),
    "group_chat": ("send_text", "send_file", "send_sticker", "invite_member", "leave_group"),
    "file_transfer": ("send_text", "send_file", "send_sticker"),
    "contact_more": ("delete_contact", "set_star", "block_contact", "recommend_contact"),
    "contact_remark": ("save_remark",), "contact_permissions": ("save_permissions",),
    "contact_tags": ("save_tags",), "moments_feed": ("like", "comment", "download_media"),
    "moments_person": ("like", "comment", "download_media"),
    "moments_publish": ("publish",), "moments_comment": ("send_comment",),
    "channels": ("like", "follow", "share", "comment", "download_media"),
    "group_announcement": ("publish_announcement",), "group_name": ("save_group_name",),
    "group_invite": ("invite_member",), "call": ("accept_call", "end_call"),
}


def page_keys(state: dict) -> set[str]:
    """Include layered observations; auxiliary windows commonly have no base page."""
    keys = {state.get("page", "unknown")}
    for layer in ("page_candidates", "panels", "overlays", "content_windows"):
        keys.update(item["key"] for item in state.get(layer, []))
    keys.discard("unknown")
    return keys


def resolve_operation(name: str, state: dict) -> tuple[PageOperation, str]:
    operation = next((item for item in OPERATIONS if item.name == name), None)
    if operation is None:
        raise ValueError("Unsupported page operation; mutations use dedicated confirmed tools")
    sources = page_keys(state) & set(operation.sources)
    if not sources:
        raise RuntimeError("Page operation precondition failed")
    # A popup must not permit navigation/clicking through its underlying main page.
    blocking = {item["key"] for item in state.get("overlays", [])}
    if blocking and not (sources & blocking):
        raise RuntimeError("A blocking popup must be cancelled or dismissed first")
    source = state["page"] if state.get("page") in sources else min(sources)
    return operation, source


def list_page_capabilities() -> dict:
    return {"version": PAGE_ACTION_VERSION, "pages": [
        {"page_id": int(spec.page_id), "key": spec.key,
         "operations": [asdict(op) for op in OPERATIONS if spec.key in op.sources],
         "confirmed_mutations": [{"name": name, "confirmation_required": True,
                                   "page_executor_enabled": False}
                                  for name in MUTATIONS.get(spec.key, ())],
         "observation_available": True, "coordinates_from_current_frame": True}
        for spec in PAGES]}


def plan_page_route(source: str, target: str) -> list[str]:
    """Shortest declared route. Runtime still observes and verifies every step."""
    known = {spec.key for spec in PAGES}
    if source not in known or target not in known:
        raise ValueError("Unknown source or target page")
    queue = deque([(source, [])])
    visited = {source}
    while queue:
        node, route = queue.popleft()
        if node == target:
            return route
        for operation in OPERATIONS:
            if node not in operation.sources or not operation.executable:
                continue
            # Additional targets accept remembered child states at runtime;
            # they are not destinations this action can explicitly select.
            for next_page in operation.targets[:1]:
                if next_page not in visited:
                    visited.add(next_page)
                    queue.append((next_page, route + [operation.name]))
    raise RuntimeError("No declared navigation contract connects these page families")
