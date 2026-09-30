import sqlite3

from wechat_auto.storage.sticker_preferences import (
    StickerCatalog,
    StickerPreferenceAnalyzer,
)


def _history(path):
    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE messages(username TEXT,local_id INTEGER,sender_id TEXT,create_time INTEGER)
    """)
    connection.execute("""
        CREATE TABLE emoji_semantics(username TEXT,local_id INTEGER,direction TEXT,
            hint TEXT,md5 TEXT,product_id TEXT)
    """)
    rows = [
        ("friend", 1, "2", 1_000), ("friend", 2, "2", 1_100),
        ("friend", 3, "2", 1_200), ("other", 4, "2", 1_300),
    ]
    connection.executemany("INSERT INTO messages VALUES(?,?,?,?)", rows)
    semantics = [
        ("friend", 1, "sent", "加油", "a", ""),
        ("friend", 2, "sent", "加油", "a", ""),
        ("friend", 3, "sent", "晚安", "b", ""),
        ("other", 4, "sent", "加油", "c", ""),
    ]
    connection.executemany("INSERT INTO emoji_semantics VALUES(?,?,?,?,?,?)", semantics)
    connection.commit()
    connection.close()


def test_recommend_is_conversation_specific(tmp_path):
    path = tmp_path / "history.sqlite3"
    _history(path)
    result = StickerPreferenceAnalyzer(path).recommend(
        "friend", intent="加油", now=1_300, limit=2
    )
    assert [item["sticker_id"] for item in result] == ["a", "b"]
    assert result[0]["uses"] == 2
    assert all(item["sticker_id"] != "c" for item in result)


def test_catalog_requires_verified_item(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    with StickerCatalog(path) as catalog:
        catalog.register("a", hint="加油", cell=(.4, .5), layout_size=(1000, 800))
        assert catalog.resolve("a") is None
        catalog.register("a", hint="加油", cell=(.4, .5), layout_size=(1000, 800),
                         verified=True)
        assert catalog.resolve("a")["cell"] == (.4, .5)
