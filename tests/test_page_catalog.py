from wechat_auto.actions.semantics import PageId
from wechat_auto.primitives.page_catalog import list_page_catalog
from wechat_auto.primitives.page_state import classify_page


def box(text, x=400, y=200):
    return {"text": text, "x": x, "y": y, "w": 80, "h": 20, "score": .99}


def test_every_named_page_has_one_catalog_entry():
    pages = list_page_catalog()
    ids = [p["page_id"] for p in pages]
    assert len(ids) == len(set(ids))
    assert set(ids) == {int(p) for p in PageId if p != PageId.UNKNOWN}
    assert len({p["key"] for p in pages}) == len(pages)


def test_contacts_and_profile_require_multiple_independent_anchors():
    state = classify_page([box("通讯录", x=120), box("新的朋友", x=120, y=250)], (1000, 800))
    assert state["page"] == "contacts"
    state = classify_page([box("微信号"), box("发消息", y=450)], (1000, 800))
    assert state["page_id"] == int(PageId.CONTACT_PROFILE)
    assert classify_page([box("发消息")], (1000, 800))["page"] == "unknown"


def test_moments_page_and_action_menu_are_separate_layers():
    state = classify_page([
        box("朋友圈", y=60), box("今天"), box("赞", x=800, y=300),
        box("评论", x=800, y=350),
    ], (1000, 800))
    assert state["page"] == "moments_feed"
    assert {m["key"] for m in state["overlays"]} >= {"moments_menu"}
    assert state["action_authorized"] is False


def test_chat_under_confirmation_dialog_preserves_both():
    state = classify_page([
        box("发送", x=800, y=750), box("取消", y=400), box("确定", y=400, x=500),
    ], (1000, 800))
    assert state["page"] == "chat"
    assert {m["key"] for m in state["overlays"]} == {"confirm_dialog"}


def test_group_settings_and_notice_are_not_private_contact_profile():
    state = classify_page([
        box("群聊名称"), box("群公告", y=250), box("我在本群的昵称", y=300),
    ], (1000, 800))
    assert state["page"] == "unknown"
    assert {m["key"] for m in state["panels"]} == {"group_details"}


def test_templates_required_are_never_marked_verified():
    pages = list_page_catalog()
    assert all(p["verification"] == "needs_real_capture" for p in pages
               if p["recognition"] == "template_required")
