from unittest.mock import MagicMock

import pytest

from wechat_auto.engine.search_router import SearchRouter


def test_search_router_keeps_ocr_out_of_safe_hot_path():
    backend = MagicMock()
    backend.plan_search.return_value = {"safe_without_ocr": True}
    basic = MagicMock()
    basic._config.ocr_verify_enabled = False
    basic.open_chat.return_value = {"ocr_used": False, "transport": "hwnd", "opened": True}
    router = SearchRouter(backend, basic)

    result = router.open_chat("朋友", expected_username="wxid_test_friend",
                              target_kind="contact")

    assert result["ocr_used"] is False
    basic.open_chat.assert_called_once_with(
        "朋友", target_kind="contact", scene="contacts", ui_query="朋友"
    )


def test_search_router_rejects_ambiguous_plan_before_ui():
    backend = MagicMock()
    backend.plan_search.return_value = {"safe_without_ocr": False}
    basic = MagicMock()
    basic._config.ocr_verify_enabled = False
    router = SearchRouter(backend, basic)

    with pytest.raises(ValueError):
        router.open_chat("同名", expected_username="room@chatroom",
                         target_kind="group")
    basic.open_chat.assert_not_called()


def test_search_router_reports_stale_or_blocked_possibilities_after_failed_verification():
    backend = MagicMock()
    backend.plan_search.return_value = {"safe_without_ocr": True}
    basic = MagicMock()
    basic._config.ocr_verify_enabled = False
    basic.open_chat.return_value = {"ocr_used": False, "transport": "hwnd", "opened": True}
    result = SearchRouter(backend, basic).try_open_chat(
        "朋友", expected_username="wxid_test_friend", target_kind="contact",
        verifier=lambda _query: False,
    )
    assert result["ok"] is False
    assert result["status"] == "ui_target_not_verified"
    assert "blocked" in result["possible_reasons"]
