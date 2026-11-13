from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw

from wechat_auto.primitives.attachment_observer import find_file_card


def sample(*, light=False, duplicate=False, name='wechat-auto...al-test.txt', size='39B', scale=1):
    image = Image.new('RGB', (1000, 700), (245,)*3 if light else (30,)*3)
    draw = ImageDraw.Draw(image)
    boxes = []
    for x in ([320, 645] if duplicate else [320]):
        draw.rounded_rectangle((x, 420, x+299, 499), radius=6,
                               fill=(215,)*3 if light else (55,)*3)
        boxes += [{'text': name, 'x': x+15, 'y': 435, 'w': 190, 'h': 18},
                  {'text': size, 'x': x+15, 'y': 465, 'w': 35, 'h': 15}]
    composer = {'x': 300, 'y': 400, 'w': 650, 'h': 260}
    if scale != 1:
        image = image.resize((round(image.width*scale), round(image.height*scale)), Image.Resampling.NEAREST)
        boxes = [{k: round(v*scale) if k in {'x', 'y', 'w', 'h'} else v for k, v in b.items()} for b in boxes]
        composer = {k: round(v*scale) for k, v in composer.items()}
    return image, boxes, composer


@pytest.mark.parametrize('light,scale', [(False, 1), (True, .75), (False, 1.5)])
def test_truncated_card_candidate_is_dynamic_but_not_identity(light, scale):
    image, boxes, composer = sample(light=light, scale=scale)
    result = find_file_card(image, boxes, composer, 'wechat-auto-functional-test.txt', 39)
    assert result['box'][0] == pytest.approx(320*scale, abs=2)
    assert not result['identity_verified'] and not result['full_name_visible']
    assert result['window_fraction'][0] == pytest.approx(.43, abs=.005)


@pytest.mark.parametrize('failure', ['duplicate', 'other_name', 'other_size', 'old_chat', 'no_card'])
def test_nonunique_or_unmatched_or_history_cards_do_not_supply_hover_point(failure):
    image, boxes, composer = sample(duplicate=failure == 'duplicate',
                                   name='other.txt' if failure == 'other_name' else 'wechat-auto...al-test.txt',
                                   size='40B' if failure == 'other_size' else '39B')
    if failure == 'old_chat':
        composer['y'] = 520
    elif failure == 'no_card':
        image = Image.new('RGB', image.size, (30,)*3)
    with pytest.raises(RuntimeError, match='absent or ambiguous'):
        find_file_card(image, boxes, composer, 'wechat-auto-functional-test.txt', 39)


def test_full_visible_name_still_does_not_authorize_send():
    name = 'wa-test.txt'
    image, boxes, composer = sample(name=name)
    result = find_file_card(image, boxes, composer, name, 39)
    assert result['full_name_visible'] and not result['identity_verified']


def test_post_cancel_shape_check_does_not_use_missing_ocr_as_absence():
    from wechat_auto.primitives.attachment_observer import (
        has_card_sized_rectangle,
        text_outside_card,
    )

    image, boxes, composer = sample()
    assert has_card_sized_rectangle(image, composer, 48)
    assert not has_card_sized_rectangle(Image.new('RGB', image.size, (30,)*3), composer, 48)
    boxes.append({'text': 'keep', 'x': 330, 'y': 550, 'w': 50, 'h': 20})
    assert text_outside_card(boxes, [320, 420, 300, 80]) == 'keep'


@pytest.mark.parametrize('failure', [None, 'identity', 'geometry', 'candidate'])
@pytest.mark.parametrize('action', ['hover_attachment_card', 'open_attachment_context_menu'])
def test_basic_hover_requires_current_identity_frame_and_card(mock_app, config, session, tmp_path, failure, action):
    from wechat_auto.actions.basic import BasicSkill

    image, boxes, composer = sample(name='other.txt' if failure == 'candidate' else 'wechat-auto...al-test.txt')
    payload = tmp_path / 'wechat-auto-functional-test.txt'
    payload.write_bytes(b'x'*39)
    mock_app.handle = 1
    metadata = {'hwnd': 1, 'pid': 2, 'rect': [0, 0, 1000, 700],
                'client_rect': [0, 0, 1000, 700], 'dpi': 96}
    mock_app.describe_window.return_value = {**metadata, 'dpi': 144} if failure == 'geometry' else metadata
    skill = BasicSkill(mock_app, config, session)
    skill._recipient_lease = None if failure == 'identity' else {'username': 'filehelper', 'metadata': metadata}
    skill._checked_recipient_composer = MagicMock(return_value=({'boxes': boxes}, 'attachment', composer))
    skill._vision_auto = MagicMock()
    skill.vision._last_observed_image = image
    skill._keyboard_only_auto = MagicMock()
    with patch('wechat_auto.actions.basic.time.sleep'):
        if failure:
            with pytest.raises((RuntimeError, PermissionError)):
                getattr(skill, action)('filehelper', str(payload))
            skill.keyboard_only.hover_window_fraction.assert_not_called()
            skill.keyboard_only.right_click_window_fraction.assert_not_called()
        else:
            result = getattr(skill, action)('filehelper', str(payload))
            assert not result['identity_verified'] and not result['sent']
            if action == 'hover_attachment_card':
                skill.keyboard_only.hover_window_fraction.assert_called_once()
                skill.keyboard_only.right_click_window_fraction.assert_not_called()
            else:
                skill.keyboard_only.right_click_window_fraction.assert_called_once()
                skill.keyboard_only.hover_window_fraction.assert_not_called()
    skill.keyboard_only.click_window_fraction.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()

@pytest.mark.parametrize('label,size', [
    ('39B', 39), ('0B', 0), ('1.5K', 1536), ('1.5KB', 1500), ('1.5KiB', 1536),
    ('2 KB', 2048), ('1.25M', 1310720), ('1.25MB', 1250000),
    ('1.25MiB', 1310720), ('1G', 1024**3), ('1GB', 1000**3), ('1TiB', 1024**4),
    ('1.4K', 1499), ('1.5K', 1549), ('1.5KiB', 1500),
])
def test_scaled_sizes_only_locate_unverified_candidates(label, size):
    from wechat_auto.primitives.attachment_observer import file_size_label_matches

    assert file_size_label_matches(label, size)
    image, boxes, composer = sample(size=label)
    result = find_file_card(image, boxes, composer, 'wechat-auto-functional-test.txt', size)
    assert not result['identity_verified']
    assert result['size_display_approximate'] is (not label.casefold().endswith('b') or label.casefold() != f'{size}b')


@pytest.mark.parametrize('label,size', [
    ('40B', 39), ('39.0B', 39), ('0.5K', 512), ('1.5K', 1800),
    ('1.5KiB', 1400), ('1MB', 1024), ('-1K', 1024), ('1e3B', 1000),
    ('1,024B', 1024), ('1.2345KB', 1234), ('1K total', 1024),
    ('1XB', 1024), ('NaNKB', 1024), ('1KB', -1), ('1KB', True), ('1KB', 1024.0),
])
def test_invalid_or_inconsistent_size_labels_are_not_candidates(label, size):
    from wechat_auto.primitives.attachment_observer import file_size_label_matches

    assert not file_size_label_matches(label, size)


def test_rounded_display_never_resolves_duplicate_cards():
    image, boxes, composer = sample(duplicate=True, size='1.5K')
    with pytest.raises(RuntimeError, match='ambiguous'):
        find_file_card(image, boxes, composer, 'wechat-auto-functional-test.txt', 1536)


@pytest.mark.parametrize('caret', [False, True])
def test_selected_card_inner_and_outer_edges_are_one_candidate(caret):
    image, boxes, composer = sample(size='1.5K')
    draw = ImageDraw.Draw(image)
    draw.rectangle((320, 420, 665, 516), fill=(46, 84, 60))
    draw.rectangle((323, 423, 662, 513), fill=(48, 70, 60))
    if caret:
        draw.rectangle((666, 420, 668, 516), fill=(0, 190, 96))
    result = find_file_card(image, boxes, composer, 'wechat-auto-functional-test.txt', 1536)
    assert not result['identity_verified']
    assert result['box'][0] == pytest.approx(323, abs=4)
