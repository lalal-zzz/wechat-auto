from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from wechat_auto.primitives.composer_templates import EMOJI_BUTTON
from wechat_auto.primitives.page_controls import (
    NavigationControlError,
    find_composer_emoji_control,
)


@pytest.mark.parametrize('scale,light',[(.75,True),(1,False),(1.5,False)])
def test_smile_is_detected_from_current_composer_and_theme(scale,light):
    background = 245 if light else 30
    stroke = 80 if light else 170
    image = Image.new('RGB',(1200,900),(background,)*3)
    glyph=Image.fromarray(np.array([[255 if v=='1' else 0 for v in row]
                                   for row in EMOJI_BUTTON],dtype=np.uint8))
    glyph=glyph.resize((round(glyph.width*scale),round(glyph.height*scale)),Image.Resampling.NEAREST)
    image.paste((stroke,)*3,(450,810),glyph)
    geometry={'composer_candidates':[{'x':420,'y':600,'w':650,'h':290}]}
    with patch('wechat_auto.primitives.page_geometry.observe_geometry',return_value=geometry):
        result=find_composer_emoji_control(image)
    assert result['x']==pytest.approx(450+glyph.width/2,abs=2)
    assert result['y']==pytest.approx(810+glyph.height/2,abs=2)
    image.paste((stroke,)*3,(600,810),glyph)
    with patch('wechat_auto.primitives.page_geometry.observe_geometry',return_value=geometry), \
            pytest.raises(NavigationControlError,match='ambiguous'):
        find_composer_emoji_control(image)


def test_no_composer_cannot_supply_smile_coordinates():
    with patch('wechat_auto.primitives.page_geometry.observe_geometry',return_value={'composer_candidates':[]}), \
            pytest.raises(NavigationControlError,match='composer'):
        find_composer_emoji_control(Image.new('RGB',(1000,800)))
