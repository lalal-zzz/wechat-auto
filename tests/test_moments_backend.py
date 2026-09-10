import pytest

from wechat_auto.backends.wechat_moments_db import DatabaseMomentsBackend


def test_media_download_requires_confirmation():
    backend = object.__new__(DatabaseMomentsBackend)
    backend._moments = type("Moments", (), {"download_moment_media": lambda *_a, **_kw: ["x.png"]})()
    feed = {"id": "m", "nickname": "A", "images": [{"md5": "i"}], "videos": []}
    plan = backend.plan_media_download(feed)
    assert plan["requires_confirmation"] is True
    with pytest.raises(PermissionError):
        backend.download_media(feed, "C:\\out")
    assert backend.download_media(feed, "C:\\out", confirm=True) == ["x.png"]
