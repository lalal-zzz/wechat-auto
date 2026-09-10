from wechat_auto.engine.moments_monitor import MomentsMonitor


class _Backend:
    def __init__(self):
        self.feeds = [{"id": "old", "username": "u", "nickname": "A", "create_time": 1,
                       "text": "old", "images": [], "videos": [], "likes": [], "comments": []}]

    def read_latest(self, limit):
        return list(self.feeds)


def test_baseline_then_new_feed_creates_safe_action(tmp_path):
    backend = _Backend()
    monitor = MomentsMonitor(backend, str(tmp_path / "moments.sqlite3"), auto_like_usernames={"u"})
    assert monitor.bootstrap()["feeds_seen"] == 1
    backend.feeds.insert(0, {"id": "new", "username": "u", "nickname": "A", "create_time": 2,
                             "text": "new", "images": [], "videos": [], "likes": [], "comments": []})
    result = monitor.scan_once()
    assert len(result["new_feeds"]) == 1
    assert result["actions"][0]["auto_eligible"] is True
    assert result["actions"][0]["requires_foreground_verification"] is True
