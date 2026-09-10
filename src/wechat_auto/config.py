"""Configuration for wechat-auto package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WeChatConfig:
    """Configuration for WeChat automation."""

    # Window identification
    wechat_class_name: str = "Qt51514QWindowIcon"
    wechat_title: str = "微信"
    wechat_process_name: str = "Weixin"
    # This library attaches to an already-running, logged-in client.  Starting
    # Weixin from an automation process can create a second client/session.
    auto_start: bool = False
    executable_path: Optional[str] = None
    launch_wait_timeout: float = 15.0

    # Timeouts (in seconds)
    default_timeout: float = 10.0
    find_element_timeout: float = 5.0
    send_message_timeout: float = 10.0
    moments_load_timeout: float = 15.0
    search_timeout: float = 8.0
    page_load_timeout: float = 10.0

    # Delays (in seconds) — mimic human interaction speed
    action_delay: float = 0.3
    type_delay: float = 0.05
    click_delay: float = 0.1
    scroll_delay: float = 0.5
    between_messages_delay: float = 0.5
    after_send_delay: float = 0.3

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0

    # Keyboard shortcuts
    shortcut_search: str = "^f"  # Ctrl+F
    shortcut_paste: str = "^v"  # Ctrl+V
    shortcut_copy: str = "^c"  # Ctrl+C
    shortcut_send: str = "{ENTER}"
    shortcut_newline: str = "+{ENTER}"  # Shift+Enter
    shortcut_emoji: str = "^e"  # Ctrl+E (may vary)

    # UI element keywords (Chinese UI)
    kw_chat_list: str = "会话"
    kw_contacts: str = "通讯录"
    kw_moments: str = "朋友圈"
    kw_search_box: str = "搜索"
    kw_send_btn: str = "发送"
    kw_emoji_btn: str = "表情"
    kw_file_btn: str = "文件"
    kw_screenshot_btn: str = "截图"

    # Moments keywords
    kw_moments_like: str = "点赞"
    kw_moments_comment: str = "评论"
    kw_moments_unlike: str = "取消"

    # Menu / context menu keywords
    kw_quote: str = "引用"
    kw_copy_msg: str = "复制"
    kw_forward: str = "转发"
    kw_delete_msg: str = "删除"
    kw_reply: str = "回复"

    keyboard_search_mode: str = "click"  # 'click' or 'shortcut'
    keyboard_input_mode: str = "wmchar"  # 'winmsg' or 'wmchar'
    # Weixin 4.x action invariant: HWND executes, OCR observes/falls back.
    action_driver: str = "hwnd"
    ocr_fallback_enabled: bool = True

    # Optional log level
    log_level: str = "INFO"

    # Chat history
    history_scroll_steps: int = 5
    history_page_wait: float = 1.0


@dataclass
class SessionConfig:
    """Per-session runtime configuration (mutable at runtime)."""

    auto_activate: bool = True
    minimize_after: bool = False
    silent_mode: bool = False
    screenshot_on_error: bool = True
    screenshot_dir: Optional[str] = None

    # Custom overrides
    overrides: dict = field(default_factory=dict)

    def get(self, key: str, default=None):
        return self.overrides.get(key, default)

    def set(self, key: str, value) -> None:
        self.overrides[key] = value
