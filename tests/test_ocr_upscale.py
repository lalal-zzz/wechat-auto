from unittest.mock import PropertyMock, patch

import pytest
from PIL import Image

from wechat_auto.config import WeChatConfig
from wechat_auto.primitives.vision import VisionAutomation


def test_upscaled_crop_coordinates_map_back_to_original_window():
    class Engine:
        name = 'fake'

        def __call__(self, image):
            assert image.shape[:2] == (80, 200)
            return [([[20, 10], [100, 10], [100, 50], [20, 50]], '测试', .99)], None

    vision = VisionAutomation(None, WeChatConfig())
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=Engine()):
        boxes = vision.recognize_image(Image.new('RGB', (100, 40)),
                                       region=(300, 150, 100, 40),window_size=(1000, 700),upscale=2)
    assert (boxes[0]['x'],boxes[0]['y'],boxes[0]['w'],boxes[0]['h']) == (310,155,40,20)


def test_unsupported_ocr_scale_is_rejected():
    with pytest.raises(ValueError, match='upscale'):
        VisionAutomation(None, WeChatConfig()).recognize_image(Image.new('RGB',(100,40)),upscale=4)
