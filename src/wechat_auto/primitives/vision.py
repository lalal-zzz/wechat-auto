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
from typing import TYPE_CHECKING, Optional

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
_OCR_ENGINE = None
_OCR_FAIL_WARNED = False


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


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


def find_red_clusters(
    image: "Image.Image",
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
        if dot["y"] - 12 <= cy <= dot["y"] + 48:
            if best is None or box["y"] < best["y"]:
                best = box
    return best["text"].strip() if best else ""


class VisionAutomation:
    """Read a HWND screenshot and return OCR observations."""

    def __init__(
        self,
        application: "Application",
        config: Optional["WeChatConfig"] = None,
        shot_dir: Optional[str] = None,
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
        return _get_ocr_engine()

    # ------------------------------------------------------------------
    # Capture & coordinate conversion
    # ------------------------------------------------------------------

    @property
    def hwnd(self) -> int:
        return self._app.handle

    def capture(self, region: Optional[tuple[int, int, int, int]] = None) -> Optional["Image.Image"]:
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

    def ocr(self, region: Optional[tuple[int, int, int, int]] = None) -> list[dict]:
        """OCR the window (or region) into ``{"text","x","y","w","h","score"}`` boxes.

        Box coordinates are window-image coordinates even when ``region``
        is given (region origin is added back).
        """
        img = self.capture(region)
        if img is None:
            return []
        ox = region[0] if region else 0
        oy = region[1] if region else 0
        try:
            import numpy as np

            result, _ = self._ocr(np.array(img))
        except Exception as exc:
            _warn_ocr_failure(exc)
            return []
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
                })
            except Exception:
                continue
        return boxes

    def find_text(
        self,
        keyword: str,
        region: Optional[tuple[int, int, int, int]] = None,
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
        region: Optional[tuple[int, int, int, int]] = None,
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

    def shot(self, skill: str, tag: str) -> Optional[str]:
        """Save a verification screenshot when an artifact dir was configured."""
        if self._shots is None:
            return None
        return self._shots.shot_window(self.hwnd, skill, tag)
