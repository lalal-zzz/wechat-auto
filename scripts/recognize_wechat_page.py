"""Download/load local OCR models and export a read-only page observation."""
from __future__ import annotations

import argparse
import html
import json
import time
from pathlib import Path

from PIL import Image

from wechat_auto.config import WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.primitives.page_catalog import PAGE_CATALOG_VERSION, list_page_catalog
from wechat_auto.primitives.page_controls import observe_tab_closes
from wechat_auto.primitives.page_geometry import observe_geometry
from wechat_auto.primitives.page_state import classify_page
from wechat_auto.primitives.vision import VisionAutomation, _get_ocr_engine
from wechat_auto.utils.screenshot import ScreenshotHelper


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, help="Read a local screenshot instead of the live window")
    parser.add_argument("--output", type=Path, default=Path("data/ocr/latest"))
    parser.add_argument("--engine", choices=["paddle", "rapid"], default="paddle")
    parser.add_argument("--geometry-only", action="store_true",
                        help="Only inspect structural boundaries; do not initialize OCR")
    parser.add_argument("--list-pages", action="store_true",
                        help="Enumerate page states and recognition coverage without loading OCR")
    args = parser.parse_args()
    if args.list_pages:
        print(json.dumps({"catalog_version": PAGE_CATALOG_VERSION,
                          "pages": list_page_catalog()}, ensure_ascii=False, indent=2))
        return 0
    config = WeChatConfig(ocr_engine=args.engine, ocr_allow_rapid_fallback=False)
    started = time.monotonic()
    engine = None if args.geometry_only else _get_ocr_engine(config)
    engine_name = engine.name if engine else "geometry_only"
    app = None
    try:
        if args.image:
            with Image.open(args.image) as source:
                image = source.convert("RGB")
        else:
            app = Application(config).connect()
            image = ScreenshotHelper().capture_window(app.handle)
        if image is None:
            raise RuntimeError("window_capture_unavailable")
        width, height = image.size
        observer = VisionAutomation(app or Application(config), config)
        boxes = [] if args.geometry_only else observer.recognize_image(image)
        state = classify_page(boxes, image.size, geometry=observe_geometry(image))
        observe_tab_closes(image, boxes, state)
        args.output.mkdir(parents=True, exist_ok=True)
        image.save(args.output / "capture.png")
        payload = {"engine": engine_name, "boxes": boxes, "state": state,
                   "elapsed_seconds": round(time.monotonic() - started, 3)}
        (args.output / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        overlays = "".join(
            f'<span style="left:{b["x"] / width * 100}%;top:{b["y"] / height * 100}%;'
            f'width:{b["w"] / width * 100}%;height:{b["h"] / height * 100}%" '
            f'title="{html.escape(b["text"], quote=True)} ({b["score"]:.2f})"></span>'
            for b in boxes)
        geometry_overlays = "".join(
            f'<span class="geometry" style="left:{b["x"] / width * 100}%;'
            f'top:{b["y"] / height * 100}%;width:{b["w"] / width * 100}%;'
            f'height:{b["h"] / height * 100}%" title="输入区域几何候选"></span>'
            for b in state["geometry"]["composer_candidates"])
        report = ('<!doctype html><meta charset="utf-8"><title>微信页面 OCR</title>'
                  '<style>body{font-family:system-ui;background:#fafafa;margin:24px}'
                  '.capture{position:relative;max-width:1400px}.capture img{width:100%}'
                  'span{position:absolute;border:1px solid #ff4d4f;box-sizing:border-box}'
                  'span.geometry{border:3px solid #2980ff;pointer-events:none}'
                  'pre{white-space:pre-wrap}</style><h1>微信页面 OCR 观察</h1>'
                  '<p>红框：OCR 文字；蓝框：传统视觉区域候选。悬停红框查看文字和置信度。</p>'
                  f'<div class="capture"><img src="capture.png">{overlays}{geometry_overlays}</div>'
                  f'<pre>{html.escape(json.dumps(state, ensure_ascii=False, indent=2))}</pre>')
        (args.output / "index.html").write_text(report, encoding="utf-8")
        print(json.dumps({"ok": True, "engine": engine_name, "box_count": len(boxes),
                          "page": state["page"], "composer": state["composer"]["state"],
                          "right_panel": state["right_panel"]["types"],
                          "output": str(args.output.resolve()),
                          "elapsed_seconds": payload["elapsed_seconds"]}, ensure_ascii=False))
        return 0
    finally:
        if app:
            app.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
