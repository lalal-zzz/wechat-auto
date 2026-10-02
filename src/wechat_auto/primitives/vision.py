"""Screenshot/OCR observation helpers.

Weixin 4.x renders its entire UI with the custom MMUI framework and exposes
NO useful UIA control tree in the tested environment. The current default
architecture uses this module only to observe and verify state, or to locate
a replacement coordinate. ``BasicSkill`` executes that coordinate by sending
messages to the top-level HWND. This module contains no mutation methods.

    window screenshot -> OCR / red-pixel localization -> coordinate actions

Coordinate conventions
----------------------
* **Image coordinates** ``(ix, iy)`` are pixels in the window capture, which
  covers the whole window including the non-client title bar.  The process
  is per-monitor DPI aware (``Application._ensure_dpi_awareness``), so these
  are physical pixels.
* Client/screen conversions for mouse actions are handled internally;
  callers only ever deal with image coordinates.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from wechat_auto.utils.screenshot import ScreenshotHelper

if TYPE_CHECKING:
    from PIL import Image

    from wechat_auto.config import WeChatConfig
    from wechat_auto.core.application import Application

logger = logging.getLogger(__name__)

#: Unread badge red in WeChat light/dark themes (~#FA5151 / #FF5050).
RED_BADGE_RGB = (250, 81, 81)
_RED_MIN_R = 180
_RED_MAX_GB = 140
_RED_MIN_DOMINANCE = 50

#: Module-level OCR engine singleton — model load costs ~1-2s and tens of
#: MB, so all VisionAutomation instances share one engine.
_OCR_ENGINES: dict[str, object] = {}
_OCR_FAIL_WARNED = False


class _PaddleOCRAdapter:
    name = "paddleocr"

    def __init__(self, config):
        from paddleocr import PaddleOCR
        self.engine = PaddleOCR(
            text_detection_model_name=getattr(config, "paddle_detection_model", "PP-OCRv5_mobile_det"),
            text_recognition_model_name=getattr(config, "paddle_recognition_model", "PP-OCRv5_mobile_rec"),
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu", enable_mkldnn=False,
        )

    def __call__(self, image):
        normalized = []
        # Vision feeds RGB screenshots; Paddle's ndarray input uses BGR.
        for output in self.engine.predict(input=image[:, :, ::-1].copy()):
            payload = getattr(output, "json", output)
            if callable(payload):
                payload = payload()
            if isinstance(payload, dict) and "res" in payload:
                payload = payload["res"]
            if not isinstance(payload, dict):
                continue
            texts = payload.get("rec_texts", ())
            scores = payload.get("rec_scores", ())
            polygons = payload.get("rec_polys", payload.get("dt_polys", ()))
            for polygon, text, score in zip(polygons, texts, scores):
                normalized.append([polygon, text, score])
        return normalized, None


class _RapidOCRAdapter:
    name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR()

    def __call__(self, image):
        return self.engine(image)


def _get_ocr_engine(config=None):
    requested = str(getattr(config, "ocr_engine", "paddle") or "paddle").lower()
    fallback = bool(getattr(config, "ocr_allow_rapid_fallback", True))
    cache_key = requested + (":fallback" if fallback else "")
    if cache_key in _OCR_ENGINES:
        return _OCR_ENGINES[cache_key]
    if requested == "paddle":
        try:
            engine = _PaddleOCRAdapter(config)
        except (ImportError, ModuleNotFoundError):
            if not fallback:
                raise
            engine = _RapidOCRAdapter()
    elif requested == "rapid":
        engine = _RapidOCRAdapter()
    else:
        raise ValueError("ocr_engine must be 'paddle' or 'rapid'")
    _OCR_ENGINES[cache_key] = engine
    return engine


def _warn_ocr_failure(exc: Exception) -> None:
    """Log OCR infrastructure failures once (not per scan)."""
    global _OCR_FAIL_WARNED
    if not _OCR_FAIL_WARNED:
        _OCR_FAIL_WARNED = True
        logger.warning("OCR unavailable (vision automation degraded): %s", exc)


def normalize_text(text: str) -> str:
    """Normalize OCR text for tolerant matching (strip all whitespace)."""
    return re.sub(r"\s+", "", text or "")


def match_boxes(boxes: list[dict], keyword: str, exact: bool = False) -> list[dict]:
    """Filter OCR boxes whose text matches ``keyword``.

    Matching is whitespace-insensitive; ``exact=False`` keeps boxes that
    *contain* the keyword (OCR routinely drops or merges characters).
    The returned list is sorted top-to-bottom, left-to-right.
    """
    key = normalize_text(keyword)
    if not key:
        return []
    hits = []
    for box in boxes:
        text = normalize_text(box.get("text", ""))
        if (exact and text == key) or (not exact and key in text):
            hits.append(box)
    hits.sort(key=lambda b: (b["y"], b["x"]))
    return hits


SEARCH_SECTION_LABELS: dict[str, tuple[str, ...]] = {
    "contact": ("联系人", "通讯录"),
    "group": ("群聊", "群组"),
    "official_account": ("公众号", "服务号"),
    "chat_history": ("聊天记录",),
    "mini_program": ("小程序", "最近使用过的小程序"),
    "channels": ("视频号",),
    "web": ("网络搜索", "搜索网络结果", "搜一搜", "AI搜索"),
    "article": ("文章",),
    "function": ("功能",),
}


def _search_section_name(text: str) -> str | None:
    compact = normalize_text(text)
    for name, labels in SEARCH_SECTION_LABELS.items():
        for label in labels:
            if compact == label or re.fullmatch(re.escape(label) + r"[（(]?\d+[）)]?", compact):
                return name
    return None


def parse_search_sections(boxes: list[dict]) -> list[dict]:
    """Group OCR result boxes under their observed Weixin search headings.

    No fixed section order is assumed: the returned order is the actual
    top-to-bottom order rendered for this query and current page.
    """
    ordered = sorted(boxes, key=lambda box: (box["y"], box["x"]))
    headers = [(index, _search_section_name(box.get("text", "")), box)
               for index, box in enumerate(ordered)]
    headers = [(index, name, box) for index, name, box in headers if name]
    sections: list[dict] = []
    for header_index, (index, name, header) in enumerate(headers):
        next_y = (headers[header_index + 1][2]["y"]
                  if header_index + 1 < len(headers) else float("inf"))
        items = [box for box in ordered[index + 1:]
                 if box["y"] < next_y and _search_section_name(box.get("text", "")) is None]
        sections.append({"section": name, "header": header, "items": items})
    return sections


def scoped_search_matches(boxes: list[dict], queries: str | list[str],
                          section: str) -> tuple[list[dict], list[str]]:
    """Return exact OCR matches only from one requested result category."""
    if section not in SEARCH_SECTION_LABELS:
        raise ValueError(f"Unsupported search section: {section}")
    values = [queries] if isinstance(queries, str) else queries
    normalized = {normalize_text(value) for value in values if normalize_text(value)}
    sections = parse_search_sections(boxes)
    matches = [box for block in sections if block["section"] == section
               for box in block["items"]
               if normalize_text(box.get("text", "")) in normalized]
    return matches, [block["section"] for block in sections]


def find_red_clusters(
    image: Image.Image,
    min_pixels: int = 10,
    min_size: int = 8,
    max_size: int = 40,
) -> list[dict]:
    """Locate red unread badge/dot clusters in a capture.

    ``min_size``/``max_size`` bound both bbox dimensions: badge dots are
    small round blobs; thin red slivers (emoji fragments, separators) and
    large red artwork are rejected.

    Returns:
        List of ``{"x", "y", "w", "h", "pixels"}`` in the image's own
        coordinate space, sorted top-to-bottom.
    """
    if image is None:
        return []
    try:
        rgb = image.convert("RGB")
    except Exception:
        return []
    width, height = rgb.size
    pixels = rgb.load()

    # Bucket red pixels on a coarse grid, then merge adjacent buckets so
    # clusters form without a full union-find.
    buckets: dict[tuple[int, int], list[tuple[int, int]]] = {}
    cell = 16
    for iy in range(0, height, 2):
        for ix in range(0, width, 2):
            r, g, b = pixels[ix, iy]
            if r >= _RED_MIN_R and g <= _RED_MAX_GB and b <= _RED_MAX_GB \
                    and r - max(g, b) >= _RED_MIN_DOMINANCE:
                buckets.setdefault((ix // cell, iy // cell), []).append((ix, iy))

    clusters: list[dict] = []
    visited: set[tuple[int, int]] = set()
    for key in buckets:
        if key in visited:
            continue
        stack, members = [key], []
        visited.add(key)
        while stack:
            cx, cy = stack.pop()
            members.extend(buckets[(cx, cy)])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nkey = (cx + dx, cy + dy)
                    if nkey in buckets and nkey not in visited:
                        visited.add(nkey)
                        stack.append(nkey)
        if len(members) * 4 < min_pixels:  # sampled every 2px -> x4 area
            continue
        xs = [p[0] for p in members]
        ys = [p[1] for p in members]
        cw = max(xs) - min(xs) + 2
        ch = max(ys) - min(ys) + 2
        if not (min_size <= cw <= max_size and min_size <= ch <= max_size):
            continue
        clusters.append({
            "x": min(xs), "y": min(ys), "w": cw, "h": ch,
            "pixels": len(members) * 4,
        })
    clusters.sort(key=lambda c: (c["y"], c["x"]))
    return clusters


def name_for_dot(dot: dict, text_boxes: list[dict], x_min: int = 0) -> str:
    """Pick the conversation name for an unread dot cluster.

    The name is the OCR text line just below/right of the dot within the
    same list row (dot sits on the avatar's top-right corner).
    """
    best = None
    for box in text_boxes:
        if box["x"] < x_min:
            continue
        cy = box["y"] + box["h"] / 2
        if (dot["y"] - 12 <= cy <= dot["y"] + 48
                and (best is None or box["y"] < best["y"])):
            best = box
    return best["text"].strip() if best else ""


class VisionAutomation:
    """Read a HWND screenshot and return OCR observations."""

    def __init__(
        self,
        application: Application,
        config: WeChatConfig | None = None,
        shot_dir: str | None = None,
    ):
        self._app = application
        self._config = config or application.config
        self._shots = ScreenshotHelper(shot_dir, enabled=bool(shot_dir)) if shot_dir else None
        self._capture = ScreenshotHelper(enabled=True)
        self._ocr_engine = None

    # ------------------------------------------------------------------
    # OCR engine (lazy; first call loads the models, ~1-2s)
    # ------------------------------------------------------------------

    @property
    def _ocr(self):
        return _get_ocr_engine(self._config)

    # ------------------------------------------------------------------
    # Capture & coordinate conversion
    # ------------------------------------------------------------------

    @property
    def hwnd(self) -> int:
        return self._app.handle

    def capture(self, region: tuple[int, int, int, int] | None = None) -> Image.Image | None:
        """Capture the window (optionally cropped to ``(x, y, w, h)`` region).

        Region is in image coordinates; the returned image is cropped.
        """
        if not self.hwnd:
            return None
        img = self._capture.capture_window(int(self.hwnd))
        if img is None:
            return None
        if region:
            x, y, w, h = region
            img = img.crop((x, y, x + w, y + h))
        return img

    def size(self) -> tuple[int, int]:
        """Window capture size in pixels (physical)."""
        img = self.capture()
        return (img.size[0], img.size[1]) if img else (0, 0)

    def is_green_at(self, fx: float, fy: float, *, radius: float = .022,
                    min_pixels: int = 12) -> bool:
        """Check a small navigation-icon area without loading the OCR engine."""
        if not 0.0 <= fx <= 1.0 or not 0.0 <= fy <= 1.0:
            raise ValueError("pixel probe coordinates must be window fractions")
        image = self.capture()
        if image is None:
            return False
        width, height = image.size
        rx = max(4, int(width * radius))
        ry = max(4, int(height * radius))
        cx, cy = int(width * fx), int(height * fy)
        left, top = max(0, cx - rx), max(0, cy - ry)
        right, bottom = min(width, cx + rx), min(height, cy + ry)
        pixels = image.convert("RGB").crop((left, top, right, bottom)).getdata()
        green = sum(1 for red, value, blue in pixels
                    if value >= 120 and value - red >= 35 and value - blue >= 20)
        return green >= min_pixels

    def find_avatar(self, avatar: bytes, *,
                    region_fractions: tuple[float, float, float, float] = (.05, .10, .25, .98),
                    min_score: float = .72, min_margin: float = .025) -> dict | None:
        """Locate one archived avatar in a bounded list region without OCR."""
        if not avatar:
            return None
        image = self.capture()
        if image is None:
            return None
        try:
            import cv2
            import numpy as np

            raw = np.frombuffer(avatar, dtype=np.uint8)
            template = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if template is None:
                return None
            screen = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            height, width = screen.shape[:2]
            fx0, fy0, fx1, fy1 = region_fractions
            x0, y0 = int(width * fx0), int(height * fy0)
            x1, y1 = int(width * fx1), int(height * fy1)
            search = screen[y0:y1, x0:x1]
            candidates: list[tuple[float, tuple[int, int], int, int]] = []
            for side in sorted({max(24, int(height * value))
                                for value in (.038, .042, .046, .050, .054)}):
                resized = cv2.resize(template, (side, side), interpolation=cv2.INTER_AREA)
                inset = max(2, side // 7)
                core = resized[inset:side - inset, inset:side - inset]
                if search.shape[0] < core.shape[0] or search.shape[1] < core.shape[1]:
                    continue
                scores = cv2.matchTemplate(search, core, cv2.TM_CCOEFF_NORMED)
                working = scores.copy()
                for _ in range(3):
                    _, score, _, location = cv2.minMaxLoc(working)
                    candidates.append((float(score), location, side, inset))
                    px, py = location
                    cv2.rectangle(working,
                                  (max(0, px - side), max(0, py - side)),
                                  (min(working.shape[1] - 1, px + side),
                                   min(working.shape[0] - 1, py + side)),
                                  -1.0, thickness=-1)
            if not candidates:
                return None
            candidates.sort(key=lambda item: item[0], reverse=True)
            best = candidates[0]
            score, (mx, my), side, inset = best
            alternatives = [item[0] for item in candidates[1:]
                            if abs(item[1][0] - mx) > side * .75
                            or abs(item[1][1] - my) > side * .75]
            second = max(alternatives, default=-1.0)
            if score < min_score or score - second < min_margin:
                return None
            center_x = x0 + mx + (side - 2 * inset) / 2
            center_y = y0 + my + (side - 2 * inset) / 2
            return {"x": center_x / width, "y": center_y / height,
                    "score": score, "margin": score - second,
                    "ocr_used": False}
        except Exception:
            return None

    def region_of(self, fx0: float, fy0: float, fx1: float, fy1: float) -> tuple[int, int, int, int]:
        """Convert fractional window rect to an ``(x, y, w, h)`` region.

        Anchors as window fractions keep working across window sizes and
        DPI settings; they were calibrated on Weixin 4.1.12 at 150%.
        """
        w, h = self.size()
        return (
            int(w * fx0), int(h * fy0),
            max(1, int(w * (fx1 - fx0))), max(1, int(h * (fy1 - fy0))),
        )

    # ------------------------------------------------------------------
    # OCR queries
    # ------------------------------------------------------------------

    def ocr(self, region: tuple[int, int, int, int] | None = None) -> list[dict]:
        """OCR the window (or region) into ``{"text","x","y","w","h","score"}`` boxes.

        Box coordinates are window-image coordinates even when ``region``
        is given (region origin is added back).
        """
        img = self.capture(region)
        if img is None:
            return []
        try:
            return self.recognize_image(img, region=region, window_size=self.size())
        except Exception as exc:
            _warn_ocr_failure(exc)
            return []

    def recognize_image(self, img: Image.Image, *,
                        region: tuple[int, int, int, int] | None = None,
                        window_size: tuple[int, int] | None = None) -> list[dict]:
        """Recognize a single captured frame; infrastructure errors are explicit."""
        ox = region[0] if region else 0
        oy = region[1] if region else 0
        import numpy as np

        result, _ = self._ocr(np.array(img.convert("RGB")))
        boxes: list[dict] = []
        for item in result or []:
            try:
                quad, text, score = item[0], item[1], item[2]
                xs = [int(p[0]) for p in quad]
                ys = [int(p[1]) for p in quad]
                boxes.append({
                    "text": str(text),
                    "x": min(xs) + ox, "y": min(ys) + oy,
                    "w": max(xs) - min(xs), "h": max(ys) - min(ys),
                    "score": float(score),
                    "engine": getattr(self._ocr, "name", "unknown"),
                    "region": list(region) if region else None,
                })
            except Exception:
                continue
        width, height = window_size or img.size
        if width > 0 and height > 0:
            for box in boxes:
                box["window_fraction"] = [
                    box["x"] / width, box["y"] / height,
                    box["w"] / width, box["h"] / height,
                ]
        return boxes

    def observe_page(self, *, include_ocr: bool = True) -> dict:
        """Return composable page states and OCR from the same HWND frame."""
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.primitives.page_state import classify_page

        image = self.capture()
        if image is None:
            return {"ok": False, "error": "window_capture_unavailable"}
        try:
            boxes = self.recognize_image(image) if include_ocr else []
        except Exception as exc:
            return {"ok": False, "error": "ocr_infrastructure_failure",
                    "error_type": type(exc).__name__}
        from wechat_auto.primitives.page_controls import observe_tab_closes

        state = classify_page(boxes, image.size, geometry=observe_geometry(image))
        observe_tab_closes(image, boxes, state)
        if state['page'] in {'contacts', 'contact_profile', 'new_friends'}:
            from wechat_auto.primitives.contact_section import observe_contact_section
            state['contact_section'] = observe_contact_section(image, boxes, state)
        return {"ok": True, "engine": self._ocr.name if include_ocr else "geometry_only",
                "boxes": boxes, "state": state}

    def find_text(
        self,
        keyword: str,
        region: tuple[int, int, int, int] | None = None,
        exact: bool = False,
        timeout: float = 0.0,
        settle: float = 0.5,
    ) -> list[dict]:
        """Find OCR boxes matching keyword, re-scanning until timeout."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            boxes = match_boxes(self.ocr(region), keyword, exact=exact)
            if boxes:
                return boxes
            if time.monotonic() >= deadline:
                return []
            time.sleep(settle)

    def wait_text_gone(
        self,
        keyword: str,
        region: tuple[int, int, int, int] | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """Wait until keyword no longer appears (popup dismissal check)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not match_boxes(self.ocr(region), keyword, exact=False):
                return True
            time.sleep(0.5)
        return False

    # ------------------------------------------------------------------
    # Verification helpers
    # ------------------------------------------------------------------

    def shot(self, skill: str, tag: str) -> str | None:
        """Save a verification screenshot when an artifact dir was configured."""
        if self._shots is None:
            return None
        return self._shots.shot_window(self.hwnd, skill, tag)
