"""Interactive real screenshot audit. Navigation only; all actions use BasicSkill.

JSON lines on stdin: {"action":"capture","label":"baseline"},
{"action":"navigation","page":"contacts"}, {"action":"click","x":.03,"y":.34},
{"action":"escape"}, {"action":"capture","hwnd":123}, {"action":"quit"}.
Private images and full OCR stay in data/; stdout contains only structural metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.primitives.page_controls import observe_tab_closes
from wechat_auto.primitives.page_geometry import observe_geometry
from wechat_auto.primitives.page_state import classify_page
from wechat_auto.primitives.vision import VisionAutomation
from wechat_auto.utils.screenshot import ScreenshotHelper


def perform_command(app, config, cmd):
    action = cmd.get("action", "capture")
    target = app.for_window(int(cmd["hwnd"])) if cmd.get("hwnd") else app
    skill = BasicSkill(target, config, SessionConfig(auto_activate=not bool(cmd.get("hwnd"))))
    if cmd.get("hwnd"):
        # Qt popup menus disappear when SetForegroundWindow is
        # called on them. Deliver HWND messages without activation.
        skill.keyboard_only.foreground_mode = "never"
    if action == "navigation":
        skill.open_navigation(cmd["page"])
    elif action == "click":
        skill.click(float(cmd["x"]), float(cmd["y"]))
    elif action == "escape":
        skill.press_key("escape")
    elif action == "resize":
        return skill.resize_window(int(cmd["width"]), int(cmd["height"]))
    elif action == "drag_divider":
        return skill.drag_divider(tuple(cmd["start"]), tuple(cmd["end"]))
    elif action == "search":
        skill.prepare_search(cmd["query"])
    elif action == "search_content":
        receipt = skill.open_search_content(cmd["query"])
        return receipt
    elif action == "page_operation":
        receipt = BasicSkill(app, config, SessionConfig()).page_operation(
            cmd["operation"], hwnd=cmd.get("hwnd"), expected_page=cmd.get("expected_page"))
        return receipt
    elif action != "capture":
        raise ValueError("Only read-only navigation audit actions are supported")

def main():
    # PowerShell pipes UTF-8, while Windows Python can default to the ANSI
    # code page. JSON command streams use UTF-8 to preserve search queries.
    if not sys.stdin.isatty():
        sys.stdin.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/ui_audit/live"))
    args = parser.parse_args()
    config = WeChatConfig(ocr_engine="paddle", ocr_allow_rapid_fallback=False,
                         ocr_verify_enabled=True)
    app = Application(config).connect()
    observer = VisionAutomation(app, config)
    cache = {}
    index = 0
    args.output.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"ready": True, "windows": app.list_windows()}), flush=True)
    try:
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
                action = cmd.get("action", "capture")
                if action == "quit":
                    break
                receipt = None
                action_error = None
                try:
                    receipt = perform_command(app, config, cmd)
                except Exception as exc:
                    action_error = {"type": type(exc).__name__, "message": str(exc)}
                time.sleep(.6)
                index += 1
                folder = args.output / f"s{index:03d}"
                folder.mkdir(exist_ok=True)
                rows = []
                for window in app.list_windows():
                    image = ScreenshotHelper().capture_window(window["hwnd"])
                    if image is None or min(image.size) < 80:
                        continue
                    digest = hashlib.sha256(image.tobytes()).hexdigest()
                    if digest not in cache:
                        cache[digest] = observer.recognize_image(image)
                    boxes = cache[digest]
                    state = classify_page(boxes, image.size, geometry=observe_geometry(image))
                    observe_tab_closes(image, boxes, state)
                    stem = "main" if window["is_main"] else str(window["hwnd"])
                    image.save(folder / f"{stem}.png")
                    (folder / f"{stem}.json").write_text(json.dumps(
                        {"window": window, "boxes": boxes, "state": state},
                        ensure_ascii=False, indent=2), encoding="utf-8")
                    rows.append({**window, "page": state["page"],
                                 "overlays": [x["key"] for x in state["overlays"]],
                                 "panels": [x["key"] for x in state["panels"]],
                                 "content_windows": [x["key"] for x in state["content_windows"]],
                                 "box_count": len(boxes)})
                record = {"step": index, "command": cmd, "windows": rows,
                          "folder": str(folder.resolve()), "receipt": receipt, "action_error": action_error}
                with (args.output / "steps.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(json.dumps({**record, "command": {k: v for k, v in cmd.items() if k != "query"},
                                  "action_error": action_error["type"] if action_error else None},
                                 ensure_ascii=False), flush=True)
            except Exception as exc:
                # Exceptions may contain private target text; expose type only.
                print(json.dumps({"ok": False, "error": type(exc).__name__}), flush=True)
    finally:
        app.disconnect()


if __name__ == "__main__":
    main()
