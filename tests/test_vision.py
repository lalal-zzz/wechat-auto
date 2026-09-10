"""Tests for vision primitives (pure functions + conversion helpers)."""

import pytest

from wechat_auto.config import WeChatConfig
from wechat_auto.primitives.vision import (
    VisionAutomation,
    find_red_clusters,
    match_boxes,
    name_for_dot,
    normalize_text,
)

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class StubApp:
    def __init__(self):
        self.config = WeChatConfig()
        self.handle = 0


def make_image(size=(300, 200), dots=(), sliver_at=None):
    """Dark-theme-like image with optional red dot blobs (10x10)."""
    img = Image.new("RGB", size, (30, 30, 30))
    draw = ImageDraw.Draw(img)
    for (x, y) in dots:
        draw.ellipse([x, y, x + 10, y + 10], fill=(250, 81, 81))
    if sliver_at:
        x, y = sliver_at
        draw.rectangle([x, y, x + 40, y + 3], fill=(250, 81, 81))
    return img


def box(text, x, y, w=50, h=20):
    return {"text": text, "x": x, "y": y, "w": w, "h": h, "score": 0.99}


# ---------------------------------------------------------------------------
# normalize_text / match_boxes
# ---------------------------------------------------------------------------

def test_normalize_text_strips_all_whitespace():
    assert normalize_text(" 文 件 传输助手 ") == "文件传输助手"
    assert normalize_text(None) == ""


def test_match_boxes_exact_requires_full_equality():
    boxes = [box("文件传输助手", 0, 0), box("文件传输助手已读功能", 0, 40)]
    hits = match_boxes(boxes, "文件传输助手", exact=True)
    assert len(hits) == 1
    assert hits[0]["y"] == 0


def test_match_boxes_contains_and_sorted_top_down():
    boxes = [box("打开文件传输助手", 0, 80), box("文件传输助手x", 0, 20)]
    hits = match_boxes(boxes, "文件传输助手", exact=False)
    assert [b["y"] for b in hits] == [20, 80]


def test_match_boxes_empty_keyword_returns_empty():
    assert match_boxes([box("abc", 0, 0)], "  ", exact=False) == []


# ---------------------------------------------------------------------------
# find_red_clusters
# ---------------------------------------------------------------------------

def test_find_red_clusters_finds_badge_dots():
    img = make_image(dots=[(50, 40), (50, 130)])
    clusters = find_red_clusters(img)
    ys = sorted(c["y"] for c in clusters)
    assert len(clusters) == 2
    assert ys[0] == pytest.approx(40, abs=4)
    assert ys[1] == pytest.approx(130, abs=4)


def test_find_red_clusters_rejects_thin_slivers():
    """Emoji fragments / separator-like thin red lines are not badges."""
    img = make_image(sliver_at=(60, 100))
    assert find_red_clusters(img) == []


def test_find_red_clusters_rejects_oversized_blobs():
    img = Image.new("RGB", (300, 200), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 150, 150], fill=(250, 81, 81))
    assert find_red_clusters(img) == []


def test_find_red_clusters_empty_image_returns_empty():
    assert find_red_clusters(make_image()) == []
    assert find_red_clusters(None) == []


# ---------------------------------------------------------------------------
# name_for_dot
# ---------------------------------------------------------------------------

def test_name_for_dot_maps_nearest_row_name():
    dot = {"x": 80, "y": 40, "w": 12, "h": 14}
    boxes = [
        box("公众号", 95, 50),
        box("21:04", 300, 52),
        box("[31条]擒龙光神：注意", 95, 80),
    ]
    assert name_for_dot(dot, boxes) == "公众号"


def test_name_for_dot_returns_empty_when_no_row():
    dot = {"x": 80, "y": 40, "w": 12, "h": 14}
    assert name_for_dot(dot, [box("远处", 95, 500)]) == ""


# ---------------------------------------------------------------------------
# VisionAutomation coordinate helpers (capture mocked)
# ---------------------------------------------------------------------------

def test_region_of_converts_fractions():
    vision = VisionAutomation(StubApp())
    vision.capture = lambda region=None: Image.new("RGB", (1000, 500))
    assert vision.region_of(0.1, 0.2, 0.5, 0.8) == (100, 100, 400, 300)


def test_size_returns_zero_without_window():
    vision = VisionAutomation(StubApp())  # handle=0 -> capture None
    assert vision.size() == (0, 0)
