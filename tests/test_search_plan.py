import pytest

from wechat_auto.backends.search_plan import build_search_plan


def test_contacts_scene_ignores_same_named_group():
    candidates = [
        {"username": "wxid_test_friend", "nick_name": "同名", "local_type": 3},
        {"username": "room@chatroom", "nick_name": "同名"},
    ]
    plan = build_search_plan(candidates, "同名", target_kind="contact", scene="contacts")
    assert plan.safe_without_ocr is True
    assert plan.exact_target_count == 1


def test_main_group_search_rejects_higher_priority_same_named_contact():
    candidates = [
        {"username": "wxid_test_friend", "remark": "项目", "local_type": 3},
        {"username": "room@chatroom", "nick_name": "项目"},
    ]
    plan = build_search_plan(candidates, "项目", target_kind="group", scene="main")
    assert plan.safe_without_ocr is False
    assert plan.higher_priority_exact_count == 1


def test_main_group_search_is_safe_without_contact_collision():
    candidates = [{"username": "room@chatroom", "nick_name": "项目"}]
    plan = build_search_plan(candidates, "项目", target_kind="group", scene="main")
    assert plan.safe_without_ocr is True
    assert plan.selection_steps == 0


def test_stable_id_can_supply_missing_adapter_kind():
    candidates = [{"username": "wxid_test_friend", "nick_name": "朋友",
                   "_known_target_kind": "contact"}]
    plan = build_search_plan(candidates, "朋友", target_kind="contact", scene="main")
    assert plan.safe_without_ocr is True


def test_scene_rejects_unsupported_target_kind():
    with pytest.raises(ValueError):
        build_search_plan([], "项目", target_kind="group", scene="contacts")


def test_partial_group_alias_requires_one_database_candidate():
    one = [{"username": "room@chatroom", "nick_name": "科技改变🐶🐶方式 2.0"}]
    assert build_search_plan(one, "方式 2.0", target_kind="group",
                             allow_partial=True).safe_without_ocr is True
    two = one + [{"username": "other@chatroom", "nick_name": "另一方式 2.0"}]
    assert build_search_plan(two, "方式 2.0", target_kind="group",
                             allow_partial=True).safe_without_ocr is False
