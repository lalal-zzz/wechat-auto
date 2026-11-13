import pytest

from wechat_auto.storage import MomentStore


def test_moment_store_saves_and_reads(tmp_path):
    feed = {"id": "feed1", "username": "u", "nickname": "A", "create_time": 3,
            "text": "hello", "images": [], "videos": [], "likes": [], "comments": []}
    with MomentStore(tmp_path / "moments.sqlite3") as store:
        assert store.save([feed]) == 1
        assert store.fetch("u")[0]["text"] == "hello"


def test_media_id_cannot_replace_another_moment_or_kind(tmp_path):
    with MomentStore(tmp_path / 'moments.sqlite3') as store:
        store.save([{'id': key, 'username': 'wxid_test_one'} for key in ('m1', 'm2')])
        store.save_media('media1', 'm1', 'image', b'original')
        for moment, kind in [('m2', 'image'), ('m1', 'video')]:
            with pytest.raises(ValueError, match='different Moment'):
                store.save_media('media1', moment, kind, b'changed')
        assert store._connection.execute(
            'SELECT moment_id,kind,content FROM message_media WHERE media_id=?', ('media1',)
        ).fetchone() == ('m1', 'image', b'original')
        store.save_media('media1', 'm1', 'image', b'valid replacement')
