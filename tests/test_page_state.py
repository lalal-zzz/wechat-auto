import pytest

from wechat_auto.primitives.page_state import classify_page


def box(text, x, y, score=.99):
    return {"text": text, "x": x, "y": y, "w": 50, "h": 20, "score": score}


def test_chat_and_content_panel_can_coexist():
    state = classify_page([box("发送", 550, 740), box("公众号", 820, 80)], (1000, 800))
    assert state["page"] == "chat"
    assert state["composer"]["state"] == "present"
    assert state["right_panel"]["types"] == ["official_account"]
    assert state["action_authorized"] is False


def test_video_panel_does_not_imply_chat_composer():
    state = classify_page([box("视频号", 820, 80)], (1000, 800))
    assert state["right_panel"]["state"] == "present"
    assert state["composer"]["state"] == "unknown"


def test_chat_message_words_do_not_become_panel_anchors():
    state = classify_page([box("公众号", 420, 350), box("发送", 420, 380)], (1000, 800))
    assert state["right_panel"]["state"] == "unknown"
    assert state["composer"]["state"] == "unknown"


def test_outgoing_bubble_on_right_does_not_imply_content_panel():
    state = classify_page([box("公众号", 820, 350)], (1000, 800))
    assert state["right_panel"]["state"] == "unknown"


def test_empty_capture_does_not_claim_controls_absent():
    state = classify_page([], (1000, 800))
    assert state["page"] == "unknown"
    assert state["composer"]["state"] == "unknown"


def test_low_confidence_anchors_are_ignored():
    state = classify_page([box("发送", 550, 740, .3)], (1000, 800))
    assert state["composer"]["state"] == "unknown"


def test_invalid_capture_dimensions_are_rejected():
    with pytest.raises(ValueError):
        classify_page([], (0, 800))


def test_personal_album_right_tab_preserves_central_profile_and_identity_boundary():
    geometry = {'right_panel_candidate': {'fraction': .65}, 'vertical_separators': []}
    profile = [box('微信号:public_id', 350, 180), box('发消息', 350, 650)]
    tab = box('朋友圈', 700, 65)
    for rows in ([box('置顶', 680, 500)], [box('10月', 690, 400), box('05', 690, 450)],
                 [box('129月', 690, 400), box('059月', 690, 600)]):
        state = classify_page(profile + [tab] + rows, (1000, 800), geometry=geometry)
        assert state['page'] == 'contact_profile'
        albums = [p for p in state['panels'] if p['key'] == 'moments_person']
        assert len(albums) == 1 and albums[0]['presentation'] == 'embedded_right_tab'
        assert state['action_authorized'] is False
    for items in (profile + [tab], [tab, box('置顶', 680, 500)],
                  profile + [tab, box('置顶', 400, 500)]):
        state = classify_page(items, (1000, 800), geometry=geometry)
        assert not any(p['key'] == 'moments_person' for p in state['panels'])


def test_scrolled_album_without_heading_requires_calendar_year_and_explicit_footer():
    items = [box('2026年', 24, 90), box('155月', 35, 295), box('254月', 35, 495),
             box('朋友仅展示最近半年的朋友圈', 190, 760)]
    state = classify_page(items, (660, 837))
    assert state['page'] == 'moments_person'
    assert state['page_candidates'][0]['verification'] == 'calendar_year_and_explicit_visibility_footer'
    assert state['action_authorized'] is False
    for missing in range(len(items)):
        reduced = [item for i, item in enumerate(items) if i != missing]
        if missing in (0, 3):
            assert classify_page(reduced, (660, 837))['page'] == 'unknown'
    assert classify_page([*items, box('发送', 550, 800)], (660, 837))['page'] != 'moments_person'
    assert classify_page(items, (660, 837), geometry={
        'composer_candidates': [{'window_fraction': [.25, .7, .7, .25]}]})['page'] != 'moments_person'
    moved = [{**item, 'x': 280} if i in (1, 2) else item for i, item in enumerate(items)]
    assert classify_page(moved, (660, 837))['page'] == 'unknown'
