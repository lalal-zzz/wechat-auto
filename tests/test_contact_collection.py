from unittest.mock import MagicMock

import pytest

from wechat_auto.memory.collection import MomentsCollection
from wechat_auto.memory.contact_state import ContactState
from wechat_auto.memory.store import MemoryStore


def test_directional_status_history_and_evidence_not_ui_failure(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        states = ContactState(store)
        kwargs = {'source': 'user_confirmation', 'evidence_ref': 'correction_1',
                  'observation_key': 'one', 'confirmed': True}
        states.record(p, 'local_block', 'blocked', **kwargs)
        states.record(p, 'local_block', 'blocked', **kwargs)
        state = states.get(p)
        assert len(state['history']) == 1
        assert state['automatic_send_blocked']
        assert state['current']['peer_block'] == 'unknown'
        states.record(p, 'moments_access', 'restricted', source='ui_observation',
                      evidence_ref='capture', observation_key='two')
        states.record(p, 'local_block', 'unblocked', **{**kwargs, 'observation_key': 'three'})
        assert not states.get(p)['automatic_send_blocked']
        assert states.get(p)['current']['peer_contact'] == 'unknown'
        with pytest.raises(PermissionError):
            states.record(p, 'peer_contact', 'removed', source='ui_observation',
                          evidence_ref='search_failed', observation_key='four', confirmed=True)
        with pytest.raises(ValueError):
            states.record(p, 'local_block', 'unblocked', **kwargs)


def test_full_snapshot_idempotency_and_continuing_absence(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        store.reconcile_snapshot('person', [p], snapshot_id='a', observed_at='2026-09-01T00:00:00+00:00')
        for key, time in [('b', '2026-09-02T00:00:00+00:00'),
                          ('c', '2026-09-02T12:00:00+00:00'), ('d', '2026-09-03T00:00:00+00:00')]:
            result = store.reconcile_snapshot('person', [], snapshot_id=key, observed_at=time)
            again = store.reconcile_snapshot('person', [], snapshot_id=key, observed_at=time)
            assert again['duplicate']
            assert again['statuses'] == result['statuses']
        assert result['statuses'][p] == 'inferred_removed'
        store.reconcile_snapshot('person', [p], snapshot_id='partial', complete=False)
        assert store._connection.execute('SELECT status FROM people WHERE person_id=?', (p,)).fetchone()[0] == 'inferred_removed'
        with pytest.raises(ValueError):
            store.reconcile_snapshot('person', [p], snapshot_id='d')


def test_coverage_history_preserved_and_cannot_claim_complete(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        c = MomentsCollection(store)
        c.record(p, 'local_db', observation_key='one', status='cached_only', count=3)
        c.record(p, 'ui_load', observation_key='two', status='restricted', pages=1)
        c.record(p, 'local_db', observation_key='three', status='cached_only', count=5)
        assert len(c.get(p)['history']) == 3
        assert c.get(p)['current']['local_db']['count'] == 5
        assert not c.get(p)['server_history_complete']
        with pytest.raises(ValueError):
            c.record(p, 'local_db', observation_key='four', status='complete')


def test_queue_stops_blocked_person_without_ui(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        c = MomentsCollection(store)
        c.enqueue([p, p])
        ContactState(store).record(p, 'peer_block', 'blocked', source='user_confirmation',
                                  evidence_ref='review', observation_key='block', confirmed=True)
        skill = MagicMock()
        with pytest.raises(PermissionError):
            c.run_one(p, skill, sync_after_load=MagicMock())
        skill.load_contact_moments.assert_not_called()
        assert c.queue()[0]['status'] == 'pending'


def test_queue_refreshes_after_load_and_preserves_failed_retry(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        c = MomentsCollection(store)
        c.enqueue([p])
        source = MagicMock()
        source.get_profile.return_value = {'alias': 'public_id', 'nickname': 'name'}
        skill = MagicMock()
        skill.load_contact_moments.side_effect = RuntimeError('private label')
        with pytest.raises(RuntimeError):
            c.run_one(p, skill, sync_after_load=source)
        source.refresh.assert_not_called()
        assert c.queue()[0]['last_error'] == 'RuntimeError'
        assert 'private label' not in str(c.get(p))
        skill.load_contact_moments.side_effect = None
        skill.load_contact_moments.return_value = {'receipt_id': 'receipt', 'coverage_status': 'stalled',
                                                  'stop_reason': 'unchanged_visible_text', 'pages': 2}
        result = c.run_one(p, skill, sync_after_load=source)
        source.refresh.assert_called_once()
        assert result['coverage']['status'] == 'stalled'
        assert len(c.get(p)['history']) == 2
        assert c.queue()[0]['status'] == 'partial'


def test_missing_alias_never_touches_window(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        c = MomentsCollection(store)
        c.enqueue([p])
        source, skill = MagicMock(), MagicMock()
        source.get_profile.return_value = {'nickname': 'name'}
        with pytest.raises(ValueError):
            c.run_one(p, skill, sync_after_load=source)
        skill.load_contact_moments.assert_not_called()


def test_missing_person_can_reverify_album_but_cannot_send_or_restore(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        store.observe_presence('person', p, present=False, snapshot_key='old_archive')
        collection = MomentsCollection(store)
        collection.enqueue([p])
        source, skill = MagicMock(), MagicMock()
        source.get_profile.return_value = {'alias': 'public_id', 'nickname': 'name'}
        skill.load_contact_moments.return_value = {
            'receipt_id': 'reviewed_album', 'coverage_status': 'partial',
            'stop_reason': 'page_budget', 'pages': 1,
        }
        result = collection.run_one(p, skill, sync_after_load=source)
        skill.load_contact_moments.assert_called_once_with(
            'name', 'public_id', max_pages=5, wechat_id='wxid_test_test')
        assert result['identity_review_required_before_load']
        state = ContactState(store).get(p)
        assert state['presence'] == 'missing'
        assert state['automatic_send_blocked']
        assert not state['moments_load_blocked']
        assert store._connection.execute(
            'SELECT count(*) FROM entity_status_events WHERE entity_id=?', (p,)
        ).fetchone()[0] == 1


@pytest.mark.parametrize('presence', ['unknown', 'inferred_removed', 'confirmed_removed', 'merged'])
def test_album_review_still_stops_unsafe_presence(tmp_path, presence):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        store._connection.execute('UPDATE people SET status=? WHERE person_id=?', (presence, p))
        store._connection.commit()
        collection = MomentsCollection(store)
        collection.enqueue([p])
        source, skill = MagicMock(), MagicMock()
        with pytest.raises(PermissionError):
            collection.run_one(p, skill, sync_after_load=source)
        source.get_profile.assert_not_called()
        skill.load_contact_moments.assert_not_called()


def test_interrupted_queue_requires_explicit_recovery(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        c = MomentsCollection(store)
        c.enqueue([p])
        store._connection.execute("UPDATE moments_load_queue SET status='running'")
        store._connection.commit()
        with pytest.raises(ValueError):
            c.run_one(p, MagicMock(), sync_after_load=MagicMock())
        assert c.recover_interrupted(p)
        assert c.queue()[0]['status'] == 'failed'


def test_identity_merge_keeps_collection_and_directional_history(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p, other = store.ensure_person('wxid_test_first'), store.ensure_person('wxid_test_second')
        c = MomentsCollection(store)
        c.enqueue([other])
        c.record(other, 'local_db', observation_key='coverage', status='cached_only', count=2)
        ContactState(store).record(other, 'local_block', 'blocked', source='user_confirmation',
                                  evidence_ref='review', observation_key='block', confirmed=True)
        candidate = store.propose_identity_merge(p, other, 'same person confirmed')
        store.decide_identity_merge(candidate, confirm=True)
        assert ContactState(store).get(p)['current']['local_block'] == 'blocked'
        assert c.get(p)['current']['local_db']['count'] == 2
        assert c.queue()[0]['status'] == 'merged'


def test_ui_loader_rejects_alias_absence_and_failed_navigation(tmp_path):
    from wechat_auto.actions.basic import BasicSkill
    from wechat_auto.config import SessionConfig, WeChatConfig
    app = MagicMock()
    app.list_windows.return_value = []
    skill = BasicSkill(app, WeChatConfig(), SessionConfig())
    skill.page_operation = MagicMock(return_value={'success': False})
    with pytest.raises(ValueError):
        skill.load_contact_moments('name', '')
    skill.page_operation.assert_not_called()
    with pytest.raises(RuntimeError, match='Contacts navigation failed'):
        skill.load_contact_moments('name', 'alias')
    skill.page_operation.assert_called_once_with('open_contacts')


def test_section_coverage_survives_reopen_and_identity_merge(tmp_path):
    path = tmp_path / 'm.db'
    sections = [
        {'section': 'pinned', 'status': 'observed', 'visibility_window': 'unknown', 'visibility_hint': ''},
        {'section': 'regular', 'status': 'restricted', 'visibility_window': 'three_days',
         'visibility_hint': '朋友仅展示最近三天的朋友圈'},
    ]
    with MemoryStore(path) as store:
        p, other = store.ensure_person('wxid_test_first'), store.ensure_person('wxid_test_second')
        c = MomentsCollection(store)
        old = c.record(other, 'local_db', observation_key='old', status='cached_only', count=10)
        assert all(row['status'] == 'unknown' for row in old['sections'])
        row = c.record(other, 'ui_load', observation_key='new', status='partial', sections=sections)
        assert c.record(other, 'ui_load', observation_key='new', status='partial', sections=sections[::-1]) == row
        candidate = store.propose_identity_merge(p, other, 'same person confirmed')
        store.decide_identity_merge(candidate, confirm=True)
    with MemoryStore(path) as store:
        result = MomentsCollection(store).get(p)
        assert result['current']['ui_load']['sections'] == sections
        assert len(result['history']) == 2
        assert not result['server_history_complete']
        assert store._connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_pinned_cannot_inherit_regular_time_limit(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        c = MomentsCollection(store)
        with pytest.raises(ValueError):
            c.record(p, 'ui_load', observation_key='bad', status='partial', sections=[{
                'section': 'pinned', 'status': 'restricted', 'visibility_window': 'six_months', 'visibility_hint': ''}])
        assert c.get(p)['history'] == []


def test_regular_time_limit_does_not_mark_whole_album_inaccessible(tmp_path):
    with MemoryStore(tmp_path / 'm.db') as store:
        p = store.ensure_person('wxid_test_test')
        c = MomentsCollection(store)
        c.enqueue([p])
        source, skill = MagicMock(), MagicMock()
        source.get_profile.return_value = {'alias': 'public_id', 'nickname': 'name'}
        section = {'section': 'regular', 'status': 'restricted', 'visibility_window': 'six_months',
                   'visibility_hint': '朋友仅展示最近半年的朋友圈'}
        skill.load_contact_moments.return_value = {
            'receipt_id': 'sections', 'coverage_status': 'stalled', 'pages': 2,
            'stop_reason': 'unchanged_album_frame', 'section_coverage': [section]}
        result = c.run_one(p, skill, sync_after_load=source)
        assert result['coverage']['sections'][1] == section
        assert ContactState(store).get(p)['current']['moments_access'] == 'unknown'


@pytest.mark.parametrize('fingerprints,expected,pages', [
    (['a', 'b', 'c'], 'partial', 3), (['a', 'a', 'a'], 'stalled', 2)])
def test_loader_uses_album_frames_and_keeps_loading_under_regular_limit(monkeypatch, fingerprints, expected, pages):
    from wechat_auto.actions.basic import BasicSkill
    from wechat_auto.config import SessionConfig, WeChatConfig
    app = MagicMock()
    app.handle = 1
    app.for_window.return_value = app
    skill = BasicSkill(app, WeChatConfig(), SessionConfig())
    skill.inspect_windows = MagicMock(return_value=[])
    skill.page_operation = MagicMock(return_value={'success': True})
    skill.open_contact_profile = MagicMock()
    skill._verify_contact_alias = MagicMock()
    skill.resolve_target_window = MagicMock(return_value={
        'ok': True, 'target': {'hwnd': 1, 'presentation': 'embedded_right_tab'}})
    skill.scroll = MagicMock()
    observer = MagicMock()
    sections = [
        {'section': 'pinned', 'status': 'observed', 'visibility_window': 'unknown', 'visibility_hint': ''},
        {'section': 'regular', 'status': 'restricted', 'visibility_window': 'six_months',
         'visibility_hint': '朋友仅展示最近半年的朋友圈'},
    ]
    observer.observe_page.side_effect = [
        {'ok': True, 'state': {'page': 'moments_person'}, 'album_observation': {
            'sections': sections, 'content_fingerprint': key,
            'body_bounds': [.6, .1, 1, 1], 'access_denied': False}}
        for key in fingerprints + [fingerprints[-1]]]
    observer.shot.return_value = ''
    monkeypatch.setattr('wechat_auto.primitives.vision.VisionAutomation', MagicMock(return_value=observer))
    monkeypatch.setattr('wechat_auto.actions.basic.time.sleep', lambda delay: None)
    result = skill.load_contact_moments('name', 'alias', max_pages=3)
    assert result['coverage_status'] == expected
    assert result['pages'] == pages
    assert result['section_coverage'] == sections
    assert skill.scroll.call_count == pages
    assert skill.scroll.call_args.args == pytest.approx((.8, .73, 4))
    assert skill.scroll.call_args.kwargs == {'embedded_content': True}
    assert not result['server_history_complete']
