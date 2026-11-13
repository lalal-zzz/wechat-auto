from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from wechat_auto.engine.moments_monitor import MomentsMonitor
from wechat_auto.storage import MomentStore


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
    assert result['actions'][0]['requires_confirmation'] is True


def test_known_moment_edits_are_archived_without_new_like_request(tmp_path):
    backend = _Backend()
    path = tmp_path / 'moments.sqlite3'
    monitor = MomentsMonitor(backend, str(path))
    monitor.bootstrap()
    backend.feeds[0] = {**backend.feeds[0], 'text': 'edited', 'comments': [{'username': 'reply', 'content': 'comment'}]}
    result = monitor.scan_once()
    assert result['rows_saved'] == 1
    assert result['new_feeds'] == [] and result['actions'] == []
    with MomentStore(path) as store:
        row = store._connection.execute('SELECT text,comments_json FROM moments WHERE id=?', ('old',)).fetchone()
        assert row[0] == 'edited' and 'comment' in row[1]
        assert store._connection.execute('SELECT count(*) FROM moment_versions WHERE id=?', ('old',)).fetchone()[0] == 2
    restarted = MomentsMonitor(backend, str(path))
    assert restarted.scan_once()['rows_saved'] == 0
    assert restarted.scan_once()['actions'] == []



def test_existing_author_collision_rolls_back_whole_scan(tmp_path):
    backend = _Backend()
    path = tmp_path / 'moments.sqlite3'
    monitor = MomentsMonitor(backend, str(path))
    monitor.bootstrap()
    original = dict(backend.feeds[0])
    backend.feeds = [{**original, 'id': 'new', 'create_time': 2},
                     {**original, 'username': 'different-author', 'text': 'conflicting'}]
    with pytest.raises(ValueError, match='different author'):
        monitor.scan_once()
    with MomentStore(path) as store:
        assert store.get('new') is None
        assert store.get('old')['username'] == 'u'
        assert store.get('old')['text'] == 'old'


def test_duplicate_input_produces_one_action_request(tmp_path):
    backend = _Backend()
    backend.feeds *= 2
    result = MomentsMonitor(backend, str(tmp_path / 'moments.sqlite3')).scan_once()
    assert len(result['new_feeds']) == len(result['actions']) == 1


def test_concurrent_monitors_only_one_reports_new_moment(tmp_path, monkeypatch):
    backend = _Backend()
    path = str(tmp_path / 'moments.sqlite3')
    # Initialize before the race; both legacy readers must observe absence
    # before either saves. An atomic save no longer needs this separate lookup.
    with MomentStore(path):
        pass
    barrier = Barrier(2)
    original = MomentStore.existing_ids

    def racing_lookup(self, ids):
        result = original(self, ids)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(MomentStore, 'existing_ids', racing_lookup)
    atomic_barrier = Barrier(2)
    original_save = MomentStore.save_with_new_ids

    def racing_save(self, feeds):
        atomic_barrier.wait(timeout=10)
        return original_save(self, feeds)

    monkeypatch.setattr(MomentStore, 'save_with_new_ids', racing_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(MomentsMonitor(backend, path).scan_once) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert sum(len(result['actions']) for result in results) == 1
    assert sum(result['rows_saved'] for result in results) == 1


def test_normalized_duplicate_uses_final_archived_payload(tmp_path):
    backend = _Backend()
    backend.feeds = [{**backend.feeds[0], 'id': ' same ', 'username': ' u ', 'text': 'first'},
                     {**backend.feeds[0], 'id': 'same', 'text': 'last'}]
    path = tmp_path / 'moments.sqlite3'
    result = MomentsMonitor(backend, str(path)).scan_once()
    assert len(result['actions']) == 1
    assert result['actions'][0]['moment_id'] == 'same'
    assert result['actions'][0]['username'] == 'u'
    assert result['new_feeds'][0]['text'] == 'last'
    with MomentStore(path) as store:
        assert store.get('same')['text'] == 'last'
