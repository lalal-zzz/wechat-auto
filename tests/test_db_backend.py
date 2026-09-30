import pytest

from wechat_auto.backends import DatabaseConversationBackend, DatabaseProfileBackend


class _DB:
    def search_contact(self, query):
        return [{"username": "room@chatroom", "nick_name": "群", "remark": ""}]

    def get_messages(self, username, limit):
        return [{"sort_seq": 4, "content": "later"}, {"sort_seq": 2, "content": "earlier"}]

    def get_new_messages(self, username, since, limit):
        return [
            {"sort_seq": 3, "sender_id": 2, "content": "self"},
            {"sort_seq": 4, "sender_id": 7, "content": "inbound"},
        ]

    def get_profile(self, username):
        return {"username": username, "nick_name": "张三", "signature": "保持好奇",
                "avatar_url": "avatar.webp", "background": "cover.webp"}

    def get_self_profile(self):
        return {"wxid": "wxid_test_me", "nickname": "我", "sign": "你好"}

    def get_contacts(self):
        return [
            {"username": "wxid_test_a", "nick_name": "甲", "description": "签名 A", "local_type": 3,
             "big_head_url": "avatar-a.webp", "head_img_md5": "md5-a"},
            {"username": "wxid_test_b", "nick_name": "乙", "remark": "同学", "local_type": 3},
            {"username": "group@chatroom", "nick_name": "群聊"},
            {"username": "wxid_test_a", "nick_name": "重复"},
        ]


def test_poll_preserves_watermark_and_filters_self_messages():
    backend = DatabaseConversationBackend(_DB())
    result = backend.poll("room@chatroom", 2)
    assert result["watermark"] == 4
    assert [m["content"] for m in result["messages"]] == ["inbound"]


def test_contact_action_plan_is_bound_to_exact_internal_username():
    class ContactDB(_DB):
        def search_contact(self, query):
            return [
                {"username": "wxid_test_friend", "alias": "public-id",
                 "nick_name": "昵称", "remark": "备注"},
                {"username": "wxid_test_other", "nick_name": "备注"},
            ]

    backend = DatabaseConversationBackend(ContactDB())
    plan = backend.plan_contact_action("wxid_test_friend", "set_remark", value="新备注")
    assert plan["username"] == "wxid_test_friend"
    assert plan["ui_query"] == "备注"
    assert plan["visible_wechat_id"] == "public-id"
    assert plan["requires_confirmation"] is True
    with pytest.raises(ValueError, match="Expected one contact"):
        backend.plan_contact_action("wxid_test_missing", "delete_contact")


def test_drafts_are_not_sent_without_explicit_confirmation():
    backend = DatabaseConversationBackend(_DB())
    result = backend.build_reply_drafts("room@chatroom", 2, lambda msg, ctx: "draft")
    assert result["drafts"][0]["draft"] == "draft"
    with pytest.raises(PermissionError):
        backend.dispatch_draft("draft", lambda text: text)
    assert backend.dispatch_draft("draft", lambda text: text, confirm=True) == "draft"


def test_sync_when_notified_uses_persisted_cursor(tmp_path):
    backend = DatabaseConversationBackend(_DB())
    result = backend.sync_when_notified("room@chatroom", str(tmp_path / "history.sqlite3"))
    assert result["watermark"] == 4
    assert result["rows_added"] == 2


def test_initial_import_is_bounded_and_sets_cursor(tmp_path):
    backend = DatabaseConversationBackend(_DB())
    result = backend.initial_import("room@chatroom", str(tmp_path / "history.sqlite3"), batch_size=10)
    assert result["messages_read"] == 2
    assert result["complete"] is True


def test_message_media_normalizer_reads_inline_and_local_media(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"png-data")
    media = DatabaseConversationBackend._message_media({
        "image_path": str(image),
        "media": [{"kind": "voice", "data": b"voice-data", "type": "voice"}],
        "video_path": "https://example.invalid/video.mp4",
    })
    assert sorted(item["kind"] for item in media) == ["image", "voice"]
    assert {item["data"] for item in media} == {b"png-data", b"voice-data"}


def test_profile_backend_normalizes_contact_and_self_fields():
    backend = DatabaseProfileBackend(_DB())
    contact = backend.get_contact_profile("wxid_test_friend")
    assert contact["wechat_id"] == "wxid_test_friend"
    assert contact["nickname"] == "张三"
    assert contact["signature"] == "保持好奇"
    assert contact["background_image"] == "cover.webp"
    assert backend.get_self_profile()["wechat_id"] == "wxid_test_me"


def test_profile_store_persists_media_references_and_text(tmp_path):
    from wechat_auto.storage import ProfileStore
    path = tmp_path / "profiles.sqlite3"
    profile = {"wechat_id": "wxid_test_me", "nickname": "我", "signature": "签名",
               "avatar": "C:/cache/avatar.jpg", "background_image": "cover.webp",
               "raw": {"source": "test"}}
    with ProfileStore(path) as store:
        store.save(profile, profile_type="self")
    with ProfileStore(path) as store:
        saved = store.get("wxid_test_me", profile_type="self")
    assert saved["signature"] == "签名"
    assert saved["avatar"] == "C:/cache/avatar.jpg"
    assert saved["background_image"] == "cover.webp"


def test_profile_store_records_snapshots_and_field_changes(tmp_path):
    from wechat_auto.storage import ProfileStore
    path = tmp_path / "profiles.sqlite3"
    with ProfileStore(path) as store:
        first = store.save({"wechat_id": "wxid_test_friend", "nickname": "小王",
                            "remark": "同事", "source": "wechat_db"}, profile_type="contact")
        second = store.save({"wechat_id": "wxid_test_friend", "nickname": "王某",
                             "remark": "同事", "source": "wechat_db"}, profile_type="contact")
        changes = store.changes("wxid_test_friend")
        history = store.history("wxid_test_friend")
    assert first["changed_fields"] == ["nickname", "remark"]
    assert "nickname" in second["changed_fields"]
    assert any(item["field"] == "nickname" and item["old"] == "小王"
               and item["new"] == "王某" for item in changes)
    assert len(history) == 2


def test_profile_backend_archives_all_direct_contacts_without_media_download(tmp_path):
    backend = DatabaseProfileBackend(_DB())
    result = backend.archive_all_contact_profiles(str(tmp_path / "profiles.sqlite3"))
    assert result["contacts_seen"] == 2
    assert result["snapshots_saved"] == 2
    assert result["scope"] == "direct_contacts"
    assert result["available_field_counts"]["signature"] == 1
    assert result["available_field_counts"]["avatar"] == 1
    assert result["media_downloaded"] is False


def test_profile_store_saves_avatar_blobs_locally(tmp_path):
    from wechat_auto.storage import ProfileStore
    with ProfileStore(tmp_path / "profiles.sqlite3") as store:
        result = store.save_media("wxid_test_friend", b"local-avatar", source="test")
        loaded = store.get_media("wxid_test_friend")
    assert result["bytes"] == len(b"local-avatar")
    assert loaded["content"] == b"local-avatar"
    assert result["updated"] is True


def test_signature_observation_records_changes_without_erasing_on_ocr_miss(tmp_path):
    from wechat_auto.storage import ProfileStore
    with ProfileStore(tmp_path / "profiles.sqlite3") as store:
        store.save({"wechat_id": "wxid_test_friend", "nickname": "朋友", "raw": {}}, profile_type="contact")
        store.watch_contact("wxid_test_friend", "朋友")
        observed = store.record_signature_observation("wxid_test_friend", "第一版")
        missed = store.record_signature_observation("wxid_test_friend", None)
        current = store.get("wxid_test_friend")
        changes = store.changes("wxid_test_friend")
    assert observed["observed"] is True
    assert missed["status"] == "signature_not_visible"
    assert current["signature"] == "第一版"
    assert any(item["field"] == "signature" for item in changes)


def test_watchlist_can_resolve_one_archived_contact_by_display_name(tmp_path):
    from wechat_auto.storage import ProfileStore
    with ProfileStore(tmp_path / "profiles.sqlite3") as store:
        store.save({"wechat_id": "wxid_test_friend", "nickname": "朋友", "raw": {}}, profile_type="contact")
        store.watch_contact_by_display_name("朋友")
        watched = store.watched_contacts()
    assert len(watched) == 1
    assert watched[0]["contact_query"] == "朋友"


def test_watchlist_entry_can_be_disabled_without_deleting_profile(tmp_path):
    from wechat_auto.storage import ProfileStore
    path = tmp_path / "profiles.sqlite3"
    with ProfileStore(path) as store:
        store.save({"wechat_id": "wxid_test_friend", "nickname": "朋友"},
                   profile_type="contact")
        store.watch_contact("wxid_test_friend", "朋友")
        assert store.disable_watched_contact("wxid_test_friend", status="stale_query") is True
        assert store.watched_contacts() == []
        assert store.get("wxid_test_friend") is not None
