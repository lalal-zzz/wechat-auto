from wechat_auto.storage import MomentStore


def test_moment_store_saves_and_reads(tmp_path):
    feed = {"id": "feed1", "username": "u", "nickname": "A", "create_time": 3,
            "text": "hello", "images": [], "videos": [], "likes": [], "comments": []}
    with MomentStore(tmp_path / "moments.sqlite3") as store:
        assert store.save([feed]) == 1
        assert store.fetch("u")[0]["text"] == "hello"
