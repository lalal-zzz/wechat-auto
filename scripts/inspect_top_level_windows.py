"""Print non-sensitive structural metadata for visible large top-level windows."""
from __future__ import annotations

import ctypes
import json
from ctypes import wintypes as wt

u = ctypes.windll.user32


def main() -> int:
    rows = []
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def collect(hwnd, _param):
        if not u.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        length = u.GetWindowTextLengthW(hwnd)
        u.GetWindowTextW(hwnd, title, min(length + 1, 256))
        rect = wt.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(rect))
        area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        if area > 300_000:
            rows.append({"hwnd": int(hwnd), "class": cls.value,
                         "title_len": len(title.value), "area": area})
        return True

    u.EnumWindows(callback_type(collect), 0)
    print(json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
