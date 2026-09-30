"""Tests for vision primitives (pure functions + conversion helpers)."""

import pytest

from wechat_auto.config import WeChatConfig
from wechat_auto.primitives.vision import (
    VisionAutomation,
    find_red_clusters,
    match_boxes,
    name_for_dot,
    normalize_text,
    parse_search_sections,
    scoped_search_matches,
)

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw


@pytest.mark.parametrize('heading', ['文章', '最近使用过的小程序', '搜索网络结果', '功能'])
def test_noncontact_search_section_cannot_supply_recipient(heading):
    boxes = [
        {'text': '联系人', 'x': 10, 'y': 20, 'w': 50, 'h': 20},
        {'text': heading, 'x': 10, 'y': 80, 'w': 100, 'h': 20},
        {'text': '张三', 'x': 10, 'y': 120, 'w': 50, 'h': 20},
    ]
    assert scoped_search_matches(boxes, '张三', 'contact')[0] == []

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


def test_search_sections_follow_observed_order_not_fixed_order():
    boxes = [
        box("群聊", 10, 10), box("项目", 30, 40),
        box("联系人", 10, 80), box("项目", 30, 110),
    ]
    sections = parse_search_sections(boxes)
    assert [item["section"] for item in sections] == ["group", "contact"]
    matches, order = scoped_search_matches(boxes, "项目", "contact")
    assert order == ["group", "contact"]
    assert [item["y"] for item in matches] == [110]


def test_scoped_search_never_returns_official_or_web_results_for_contact():
    boxes = [
        box("联系人", 10, 10), box("目标", 30, 40),
        box("公众号", 10, 80), box("目标", 30, 110),
        box("网络搜索", 10, 150), box("目标", 30, 180),
    ]
    matches, sections = scoped_search_matches(boxes, "目标", "contact")
    assert [item["y"] for item in matches] == [40]
    assert sections == ["contact", "official_account", "web"]


def test_scoped_search_never_returns_official_or_web_results_for_group():
    boxes = [
        box("群聊", 10, 10), box("目标群", 30, 40),
        box("服务号", 10, 80), box("目标群", 30, 110),
        box("搜一搜", 10, 150), box("目标群", 30, 180),
    ]
    matches, _ = scoped_search_matches(boxes, "目标群", "group")
    assert [item["y"] for item in matches] == [40]


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


def test_green_navigation_probe_does_not_use_ocr():
    vision = VisionAutomation(StubApp())
    image = Image.new("RGB", (100, 100), (30, 30, 30))
    ImageDraw.Draw(image).rectangle([45, 45, 55, 55], fill=(7, 193, 96))
    vision.capture = lambda region=None: image
    assert vision.is_green_at(.5, .5, radius=.1, min_pixels=10)


def test_avatar_template_match_is_bounded_and_no_ocr():
    import io
    image = Image.new("RGB", (400, 300), (30, 30, 30))
    avatar = Image.new("RGB", (80, 80), (20, 90, 160))
    draw = ImageDraw.Draw(avatar)
    draw.rectangle([20, 10, 60, 70], fill=(220, 180, 40))
    shown = avatar.resize((42, 42))
    image.paste(shown, (50, 120))
    payload = io.BytesIO()
    avatar.save(payload, format="PNG")
    vision = VisionAutomation(StubApp())
    vision.capture = lambda region=None: image
    match = vision.find_avatar(payload.getvalue(), region_fractions=(0, 0, .5, 1),
                               min_score=.6, min_margin=.01)
    assert match is not None
    assert match["ocr_used"] is False
