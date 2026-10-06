import pytest
from PIL import Image, ImageDraw

from wechat_auto.primitives.page_controls import observe_tab_closes
from wechat_auto.primitives.page_geometry import observe_geometry


@pytest.mark.parametrize('background,field', [(30, 65), (245, 215)])
def test_unfocused_low_contrast_search_field_is_detected(background, field):
    image = Image.new('RGB', (1686, 1135), (background,) * 3)
    ImageDraw.Draw(image).rounded_rectangle((120, 64, 397, 104), radius=8,
                                            fill=(field,) * 3)
    candidates = observe_geometry(image)['search_field_candidates']
    assert len(candidates) == 1
    assert abs(candidates[0]['x'] - 120) <= 2
    assert abs(candidates[0]['w'] - 277) <= 3


def test_webpage_card_edge_does_not_override_composer_adjacent_divider():
    image = Image.new('RGB', (1000, 800), (30,) * 3)
    draw = ImageDraw.Draw(image)
    draw.rectangle((600, 40, 999, 799), fill=(50,) * 3)
    draw.rectangle((730, 110, 950, 700), fill=(20,) * 3)
    draw.rounded_rectangle((250, 580, 585, 780), radius=8, outline=(100,) * 3, width=2)
    geometry = observe_geometry(image)
    assert len([s for s in geometry['vertical_separators'] if s['x'] > 590]) >= 2
    assert abs(geometry['right_panel_candidate']['x'] - 600) <= 2
    assert geometry['right_panel_candidate']['corroborated_by'] == 'composer_right_edge'


@pytest.mark.parametrize('background,ink', [(30, 180), (245, 70)])
def test_cross_candidates_follow_short_and_long_tab_labels_in_both_themes(background, ink):
    for gap in (50, 120):
        image = Image.new('RGB', (600, 160), (background,) * 3)
        draw = ImageDraw.Draw(image)
        cx, cy = 220 + gap, 65
        draw.line((cx - 8, cy - 8, cx + 8, cy + 8), fill=(ink,) * 3, width=2)
        draw.line((cx - 8, cy + 8, cx + 8, cy - 8), fill=(ink,) * 3, width=2)
        boxes = [{'x': 120, 'y': 55, 'w': 100, 'h': 20}]
        state = {'right_panel': {'tabs': [{'evidence_box_index': 0}]}}
        observe_tab_closes(image, boxes, state)
        control = state['right_panel']['tabs'][0]['close_candidate']
        assert abs(control['x'] - cx) <= 3 and abs(control['y'] - cy) <= 3


def test_two_close_glyphs_are_ambiguous_and_do_not_produce_a_control():
    image = Image.new('RGB', (600, 160), (30,) * 3)
    draw = ImageDraw.Draw(image)
    for cx in (270, 340):
        draw.line((cx - 8, 57, cx + 8, 73), fill=(180,) * 3, width=2)
        draw.line((cx - 8, 73, cx + 8, 57), fill=(180,) * 3, width=2)
    state = {'right_panel': {'tabs': [{'evidence_box_index': 0}]}}
    observe_tab_closes(image, [{'x': 120, 'y': 55, 'w': 100, 'h': 20}], state)
    assert 'close_candidate' not in state['right_panel']['tabs'][0]


def test_profile_album_entry_uses_current_thumbnail_strip_and_rejects_ambiguity():
    import numpy as np
    from wechat_auto.primitives.page_controls import find_contact_album_entry

    image = Image.new('RGB', (1000, 800), (30, 30, 30))
    label = {'x': 260, 'y': 250, 'w': 48, 'h': 16}
    rng = np.random.default_rng(5)
    texture = Image.fromarray(rng.integers(0, 255, size=(38, 220, 3), dtype=np.uint8))
    image.paste(texture, (360, 240))
    control = find_contact_album_entry(image, label, right=650)
    assert 358 <= control['x'] <= 362
    assert control['window_fraction'][0] == pytest.approx(.47, abs=.005)
    assert control['method'] == 'current_profile_label_and_thumbnail_texture'
    with pytest.raises(RuntimeError, match='absent or ambiguous'):
        find_contact_album_entry(Image.new('RGB', (1000, 800), (30, 30, 30)), label)
    image.paste(texture, (700, 240))
    with pytest.raises(RuntimeError, match='absent or ambiguous'):
        find_contact_album_entry(image, label)
