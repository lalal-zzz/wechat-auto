"""Print only structural HWND metadata for Weixin diagnostics."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json

from wechat_auto.config import WeChatConfig
from wechat_auto.core.application import Application


def main() -> int:
    app = Application(WeChatConfig()).connect()
    user32 = ctypes.windll.user32
    children = []
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def collect(hwnd, _lparam):
        class_name = ctypes.create_unicode_buffer(256)
        rect = wt.RECT()
        user32.GetClassNameW(hwnd, class_name, 256)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        children.append({
            "hwnd": int(hwnd), "class": class_name.value,
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "visible": bool(user32.IsWindowVisible(hwnd)),
        })
        return True

    try:
        user32.EnumChildWindows(app.handle, callback_type(collect), 0)
        visible_children = [item for item in children if item["visible"]]
        render_children = [item for item in visible_children
                           if item["class"].startswith("MMUIRenderSubWindow")]
        contact_candidates = [item for item in visible_children
                              if item["class"] not in {"MMUIRenderSubWindowHW",
                                                       "MMUIRenderSubWindow"}]
        print(json.dumps({
            "main_hwnd": app.handle,
            "children": children,
            "visible_child_count": len(visible_children),
            "render_surface_count": len(render_children),
            "contact_level_handle_present": bool(contact_candidates),
            "contact_level_handle_reason": (
                "no_individual_child_window; contacts are drawn in the render surface"
                if not contact_candidates else "candidate_requires_manual_inspection"
            ),
        }, ensure_ascii=False))
        return 0
    finally:
        app.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
