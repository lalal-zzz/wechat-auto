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
