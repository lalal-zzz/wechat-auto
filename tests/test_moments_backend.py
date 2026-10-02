from unittest.mock import MagicMock

import pytest

from wechat_auto.backends.wechat_moments_db import (
    DatabaseMomentsBackend,
    MomentMediaDownloadError,
)


def test_media_download_requires_confirmation():
    backend = object.__new__(DatabaseMomentsBackend)
    backend._moments = type("Moments", (), {"download_moment_media": lambda *_a, **_kw: ["x.png"]})()
    feed = {"id": "m", "nickname": "A", "images": [{"md5": "i"}], "videos": []}
    plan = backend.plan_media_download(feed)
    assert plan["requires_confirmation"] is True
    with pytest.raises(PermissionError):
        backend.download_media(feed, "C:\\out")
    assert backend.download_media(feed, "C:\\out", confirm=True) == ["x.png"]


@pytest.mark.parametrize('saved', [[], ['first.jpg']])
def test_incomplete_download_is_failure_without_automatic_retry(saved):
    backend = object.__new__(DatabaseMomentsBackend)
    backend._moments = MagicMock()
    backend._moments.download_moment_media.return_value = saved
    feed = {'images': [{'url': 'https://example.invalid/private-one'},
                       {'url': 'https://example.invalid/private-two'}], 'videos': []}
    with pytest.raises(MomentMediaDownloadError) as failure:
        backend.download_media(feed, 'output', confirm=True)
    assert failure.value.saved_paths == saved
    assert failure.value.expected == 2
    assert 'private' not in str(failure.value)
    backend._moments.download_moment_media.assert_called_once()


def test_empty_download_plan_never_calls_dependency():
    backend = object.__new__(DatabaseMomentsBackend)
    backend._moments = MagicMock()
    with pytest.raises(ValueError, match='no media'):
        backend.download_media({'images': [], 'videos': []}, 'output', confirm=True)
    backend._moments.download_moment_media.assert_not_called()


def test_full_local_timeline_read_has_no_latest_fifty_limit():
    backend = object.__new__(DatabaseMomentsBackend)
    backend._moments = MagicMock()
    backend._moments.get_moments.return_value = [{'id': str(n)} for n in range(75)]
    assert len(backend.read_all_available()) == 75
    backend._moments.get_moments.assert_called_once_with(limit=0, username=None)
    backend._moments.download_moment_media.assert_not_called()
