import numpy as np
import pytest
from PIL import Image

from wechat_auto.primitives.navigation_templates import TEMPLATES
from wechat_auto.primitives.page_controls import find_navigation_control


def sidebar(size, *, position=(42, 300), scale=1, light=False, duplicate=False):
    _width, height = size
    image = Image.new('RGB', size, (210, 210, 210) if light else (65, 65, 65))
    image.paste((245, 245, 245) if light else (35, 35, 35), (0, 0, 130, height))
    mask = np.array([[255 if x == '1' else 0 for x in row]
                     for row in TEMPLATES['open_contacts']], dtype=np.uint8)
    glyph = Image.fromarray(mask).resize((round(mask.shape[1] * scale), round(mask.shape[0] * scale)),
                                       Image.Resampling.NEAREST)
    image.paste((95, 95, 95) if light else (150, 150, 150), position, glyph)
    if duplicate:
        image.paste((95, 95, 95) if light else (150, 150, 150), (position[0], position[1] + 110), glyph)
    return image, glyph.size


@pytest.mark.parametrize('size,scale,light', [((900, 650), .75, False), ((1410, 904), 1, False),
                                            ((2175, 1135), 1.25, True), ((2352, 1214), 1.5, False)])
def test_current_glyph_location_survives_window_size_dpi_and_theme(size, scale, light):
    image, glyph_size = sidebar(size, scale=scale, light=light)
    c = find_navigation_control(image, 'open_contacts')
    assert abs(c['x'] - (42 + glyph_size[0] / 2)) <= 2
    assert abs(c['y'] - (300 + glyph_size[1] / 2)) <= 2
    assert c['frame_size'] == list(size)
    assert c['method'] == 'opencv_multiscale_glyph'


def test_repositioned_icon_is_detected_instead_of_reusing_previous_fraction():
    first, _ = sidebar((1410, 904), position=(42, 300))
    moved, _ = sidebar((1900, 1000), position=(68, 410))
    a, b = (find_navigation_control(image, 'open_contacts') for image in (first, moved))
    assert b['x'] - a['x'] == pytest.approx(26, abs=2)
    assert b['y'] - a['y'] == pytest.approx(110, abs=2)
    assert a['window_fraction'] != b['window_fraction']


def test_missing_duplicate_and_unimplemented_controls_do_not_supply_coordinates():
    empty = Image.new('RGB', (1000, 800), 'black')
    with pytest.raises(RuntimeError):
        find_navigation_control(empty, 'open_contacts')
    image, _ = sidebar((1000, 800), duplicate=True)
    with pytest.raises(RuntimeError, match='ambiguous'):
        find_navigation_control(image, 'open_contacts')
    with pytest.raises(RuntimeError, match='not implemented'):
        find_navigation_control(image, 'open_contact_more')
