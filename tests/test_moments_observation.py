import pytest
from PIL import Image, ImageDraw

from wechat_auto.primitives.moments_observation import (
    merge_album_sections,
    observe_album_sections,
)


def box(text, x=620, y=180):
    return {'text': text, 'score': .99, 'x': x, 'y': y, 'w': 80, 'h': 20}


def frame():
    return Image.new('RGB', (1000, 800), 'white')


STATE = {'panels': [{'key': 'moments_person', 'presentation': 'embedded_right_tab'}],
         'region_bounds': {'right_content': [.6, .1, 1, 1], 'right_panel_header': [.6, 0, 1, .1]}}


@pytest.mark.parametrize('period,expected', [('三天', 'three_days'), ('半年', 'six_months'), ('一个月', 'one_month')])
def test_pinned_is_independent_of_regular_visibility(period, expected):
    result = observe_album_sections(frame(), [box('置顶'), box(f'朋友仅展示最近{period}的朋友圈', y=600)], STATE)
    pinned, regular = result['sections']
    assert pinned['status'] == 'observed'
    assert pinned['visibility_window'] == 'unknown'
    assert regular['status'] == 'restricted'
    assert regular['visibility_window'] == expected
    assert not result['access_denied']


def test_profile_text_outside_album_does_not_set_section_visibility():
    result = observe_album_sections(frame(), [box('置顶', x=100), box('朋友仅展示最近三天的朋友圈', x=100)], STATE)
    assert all(row['status'] == 'unknown' for row in result['sections'])


def test_photos_change_fingerprint_even_when_ocr_does_not():
    image = frame()
    first = observe_album_sections(image, [box('置顶')], STATE)
    ImageDraw.Draw(image).rectangle((700, 250, 900, 450), fill='black')
    second = observe_album_sections(image, [box('置顶')], STATE)
    assert first['content_fingerprint'] != second['content_fingerprint']
    ImageDraw.Draw(image).rectangle((100, 250, 500, 450), fill='black')
    assert observe_album_sections(image, [box('置顶')], STATE)['content_fingerprint'] == second['content_fingerprint']


def test_scroll_does_not_erase_prior_pinned_or_time_limit_observation():
    current = {}
    merge_album_sections(current, observe_album_sections(
        frame(), [box('置顶'), box('朋友仅展示最近半年的朋友圈', y=600)], STATE)['sections'])
    merge_album_sections(current, observe_album_sections(frame(), [box('5月'), box('25', y=250)], STATE)['sections'])
    assert current['pinned']['status'] == 'observed'
    assert current['regular']['status'] == 'restricted'
    assert current['regular']['visibility_window'] == 'six_months'


def test_old_dates_alone_do_not_prove_visibility_setting():
    result = observe_album_sections(frame(), [box('2020年5月'), box('25', y=250)], STATE)
    assert result['sections'][1]['visibility_window'] == 'unknown'
    assert result['sections'][1]['status'] == 'observed'
    assert not result['access_denied']


@pytest.mark.parametrize('text,expected', [('129月', 'observed'), ('059月', 'observed'),
                                         ('11月', 'unknown'), ('9913月', 'unknown')])
def test_combined_date_boxes_observe_regular_layout_without_inventing_dates(text, expected):
    result = observe_album_sections(frame(), [box(text)], STATE)
    assert result['sections'][1]['status'] == expected
    assert result['sections'][1]['visibility_window'] == 'unknown'
