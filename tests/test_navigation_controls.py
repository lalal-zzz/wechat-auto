import numpy as np
import pytest
from PIL import Image

from wechat_auto.primitives.navigation_templates import TEMPLATES
from wechat_auto.primitives.page_controls import (
    NavigationControlError,
    find_navigation_control,
    observe_empty_chat,
    observe_selected_contacts,
)


@pytest.mark.parametrize('scale,light', [(1, False), (.75, True), (1.5, False)])
def test_empty_chat_requires_selected_glyph_and_unique_public_logo(scale, light):
    from wechat_auto.primitives.empty_chat_logo import EMPTY_CHAT_LOGO

    background = 240 if light else 30
    image = Image.new('RGB', (1000, 800), (background,)*3)
    image.paste((210,)*3 if light else (65,)*3, (100, 0, 300, 800))
    glyph = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                     for row in TEMPLATES['open_chats']], dtype=np.uint8))
    image.paste((0, 180, 100), (35, 150), glyph)
    logo = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                    for row in EMPTY_CHAT_LOGO], dtype=np.uint8))
    image.paste((background-25,)*3 if light else (background+25,)*3, (600, 350), logo)
    image = image.resize((round(1000*scale), round(800*scale)), Image.Resampling.NEAREST)
    def state():
        return {'page':'unknown', 'composer':{}, 'region_bounds':{'conversation_header':[.3]}}
    observed = state()
    observe_empty_chat(image, observed)
    assert observed['page'] == 'main_without_selected_chat'
    assert observed['selected_navigation']['verification'] == 'selected_chat_glyph_and_empty_logo'
    blocked = state(); blocked['composer']['geometry_candidates'] = [{}]
    observe_empty_chat(image, blocked)
    assert blocked['page'] == 'unknown'
    image.paste((background,)*3, (round(600*scale),round(350*scale),round(730*scale),round(460*scale)))
    missing = state()
    observe_empty_chat(image, missing)
    assert missing['page'] == 'unknown'


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


@pytest.mark.parametrize('operation', ['open_chats', 'open_discover'])
def test_similar_sidebar_silhouettes_require_a_strong_distinct_winner(operation):
    image = Image.new('RGB', (1000, 800), (65, 65, 65))
    image.paste((35, 35, 35), (0, 0, 100, 800))
    positions = {'open_chats': (35, 150), 'open_discover': (35, 330)}
    for name, position in positions.items():
        glyph = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                         for row in TEMPLATES[name]], dtype=np.uint8))
        image.paste((150, 150, 150), position, glyph)
    control = find_navigation_control(image, operation)
    assert abs(control['y'] - (positions[operation][1] + len(TEMPLATES[operation])/2)) <= 2
    glyph = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                     for row in TEMPLATES[operation]], dtype=np.uint8))
    image.paste((150, 150, 150), (35, 500), glyph)
    with pytest.raises(NavigationControlError, match='ambiguous'):
        find_navigation_control(image, operation)


def test_a_compass_cross_match_cannot_substitute_for_the_absent_chat_icon():
    image = Image.new('RGB', (1000, 800), (65, 65, 65))
    image.paste((35, 35, 35), (0, 0, 100, 800))
    glyph = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                     for row in TEMPLATES['open_discover']], dtype=np.uint8))
    image.paste((150, 150, 150), (35, 300), glyph)
    with pytest.raises(NavigationControlError, match='absent or ambiguous'):
        find_navigation_control(image, 'open_chats')


@pytest.mark.parametrize('scale,light', [(1, False), (.75, True), (1.5, False)])
@pytest.mark.parametrize('duplicate', [False, True, 'badged'])
def test_unread_badge_is_unknown_pixels_and_duplicate_chats_still_stop(scale, light, duplicate):
    from PIL import ImageDraw

    background = 245 if light else 35
    image = Image.new('RGB', (1000, 800), (210,)*3 if light else (65,)*3)
    image.paste((background,)*3, (0, 0, 100, 800))
    for operation, y in [('open_chats', 150), ('open_discover', 330)]:
        glyph = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                         for row in TEMPLATES[operation]], dtype=np.uint8))
        image.paste((70,)*3 if light else (160,)*3, (35, y), glyph)
        if operation == 'open_chats':
            if duplicate:
                image.paste((70,)*3 if light else (160,)*3, (35, 500), glyph)
            draw = ImageDraw.Draw(image)
            draw.ellipse((61, 148, 80, 167), fill=(250, 70, 75))
            draw.text((67, 150), '1', fill='white')
            if duplicate == 'badged':
                draw.ellipse((61, 498, 80, 517), fill=(250, 70, 75))
                draw.text((67, 500), '2', fill='white')
    image = image.resize((round(1000*scale), round(800*scale)), Image.Resampling.NEAREST)
    if duplicate:
        with pytest.raises(NavigationControlError, match='ambiguous'):
            find_navigation_control(image, 'open_chats')
    else:
        control = find_navigation_control(image, 'open_chats')
        assert control['x'] == pytest.approx(53*scale, abs=2)
        assert control['y'] == pytest.approx(168*scale, abs=2)


def test_badge_on_compass_does_not_create_chat_evidence():
    from PIL import ImageDraw

    image = Image.new('RGB', (1000, 800), (65,)*3)
    image.paste((35,)*3, (0, 0, 100, 800))
    glyph = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                     for row in TEMPLATES['open_discover']], dtype=np.uint8))
    image.paste((160,)*3, (35, 150), glyph)
    ImageDraw.Draw(image).ellipse((61, 148, 80, 167), fill=(250, 70, 75))
    with pytest.raises(NavigationControlError, match='absent or ambiguous'):
        find_navigation_control(image, 'open_chats')


def test_large_badge_cannot_replace_missing_chat_shape():
    from PIL import ImageDraw

    image = Image.new('RGB', (1000, 800), (65,)*3)
    image.paste((35,)*3, (0, 0, 100, 800))
    glyph = Image.fromarray(np.array([[255 if v == '1' else 0 for v in row]
                                     for row in TEMPLATES['open_chats']], dtype=np.uint8))
    image.paste((160,)*3, (35, 150), glyph)
    ImageDraw.Draw(image).ellipse((40, 148, 76, 182), fill=(250, 70, 75))
    with pytest.raises(NavigationControlError, match='absent or ambiguous'):
        find_navigation_control(image, 'open_chats')


def test_selected_contacts_glyph_observes_page_without_tree_headers():
    image, _ = sidebar((1410, 904))
    rgb = np.array(image)
    rgb[(rgb[:, :, 0] == 150) & (rgb[:, :, 1] == 150)] = (0, 180, 100)
    state = {'page': 'unknown', 'overlays': [], 'panels': [], 'content_windows': [],
             'action_authorized': False}
    observe_selected_contacts(Image.fromarray(rgb), state)
    assert state['page'] == 'contacts'
    assert state['selected_navigation']['verification'] == 'current_selected_green_glyph'
    assert not state['action_authorized']


def test_inactive_ambiguous_or_blocked_contacts_glyph_never_promotes_page():
    inactive, _ = sidebar((1410, 904))
    state = {'page': 'unknown'}
    observe_selected_contacts(inactive, state)
    assert state['page'] == 'unknown'
    rgb = np.array(inactive)
    rgb[(rgb[:, :, 0] == 150) & (rgb[:, :, 1] == 150)] = (0, 180, 100)
    active = Image.fromarray(rgb)
    for blocker in ('overlays', 'panels', 'content_windows'):
        state = {'page': 'unknown', blocker: [{'key': 'unknown_content'}]}
        observe_selected_contacts(active, state)
        assert state['page'] == 'unknown'
    duplicate, _ = sidebar((1410, 904), duplicate=True)
    rgb = np.array(duplicate)
    rgb[(rgb[:, :, 0] == 150) & (rgb[:, :, 1] == 150)] = (0, 180, 100)
    state = {'page': 'unknown'}
    observe_selected_contacts(Image.fromarray(rgb), state)
    assert state['page'] == 'unknown'
