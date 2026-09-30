from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from wechat_auto.config import WeChatConfig
from wechat_auto.primitives.page_geometry import observe_geometry
from wechat_auto.primitives.page_state import classify_page
from wechat_auto.primitives.vision import VisionAutomation


@pytest.mark.parametrize("background,border,theme", [
    ((30, 30, 30), (100, 100, 100), "dark"),
    ((245, 245, 245), (160, 160, 160), "light"),
])
def test_empty_input_border_is_detected_in_both_themes(background, border, theme):
    image = Image.new("RGB", (1000, 800), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((280, 570, 970, 780), outline=border, width=2)
    geometry = observe_geometry(image)
    assert geometry["theme"] == theme
    assert geometry["composer_candidates"]
    state = classify_page([], image.size, geometry=geometry)
    assert state["composer"]["state"] == "candidate"
    assert state["action_authorized"] is False


def test_content_panel_separator_adapts_right_region():
    image = Image.new("RGB", (1000, 800), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((620, 0, 999, 799), fill=(245, 245, 245))
    geometry = observe_geometry(image)
    assert geometry["right_panel_candidate"]
    state = classify_page([
        {"text": "公众号", "x": 640, "y": 60, "w": 40, "h": 20, "score": .99}
    ], image.size, geometry=geometry)
    assert state["right_panel"]["types"] == ["official_account"]


def test_flat_blank_page_has_no_input_candidate():
    geometry = observe_geometry(Image.new("RGB", (1000, 800), (30, 30, 30)))
    assert geometry["composer_candidates"] == []
    assert geometry["right_panel_candidate"] is None


def test_geometry_only_observer_never_loads_ocr():
    observer = VisionAutomation(None, WeChatConfig())
    with (
        patch.object(observer, "capture", return_value=Image.new("RGB", (1000, 800))),
        patch("wechat_auto.primitives.vision._get_ocr_engine") as loader,
    ):
        result = observer.observe_page(include_ocr=False)
    assert result["ok"] is True
    assert result["engine"] == "geometry_only"
    loader.assert_not_called()
