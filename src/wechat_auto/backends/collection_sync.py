"""Refresh all local non-group contact rows and readable Moments, offline only."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db
from wechat_auto.backends.profile import DatabaseProfileBackend
from wechat_auto.backends.wechat_moments_db import DatabaseMomentsBackend
from wechat_auto.memory import MemoryStore
from wechat_auto.memory.collection import MomentsCollection
from wechat_auto.memory.indexer import ArchiveIndexer
from wechat_auto.storage import MomentStore, ProfileStore


def profile_changed(previous, profile):
    if previous is None:
        return True
    ignored = {'profile_type', 'wechat_id', 'source', 'updated_at'}
    return any(previous.get(key, '') != value for key, value in profile.items() if key not in ignored)


def refresh(db, *, profiles_path, moments_path, memory_path, output):
    """Source reads are complete before writes; historical archive rows stay intact."""
    started = time.monotonic()
    # local_type varies across client versions; full archival must not
    # silently discard real people using an unverified type=3 assumption.
    profiles = DatabaseProfileBackend(db).get_all_contact_profiles(direct_contacts_only=False)
    if not profiles:
        raise RuntimeError('Current contact snapshot is empty; refresh stopped')
    usernames = {p['wechat_id'] for p in profiles}
    all_feeds = DatabaseMomentsBackend(db).read_all_available()
    feeds = [feed for feed in all_feeds if feed.get('username') in usernames]
    run_id = 'full_' + uuid.uuid4().hex[:12]
    folder = Path(output) / run_id
    folder.mkdir(parents=True, exist_ok=False)
    changed_profiles = 0
    changed_moments = []
    manifest = []
    with ProfileStore(profiles_path) as archive:
        for profile in profiles:
            previous = archive.get(profile['wechat_id'])
            # An empty DB field is not proof that a field observed on the
            # verified UI was cleared. Retain UI provenance across local sync.
            if previous and previous.get('raw', {}).get('ui_fields'):
                raw = dict(profile.get('raw', {}))
                raw['ui_fields'] = previous['raw']['ui_fields']
                profile['raw'] = raw
                for field, observation in raw['ui_fields'].items():
                    if not profile.get(field):
                        profile[field] = observation['value']
            if profile_changed(previous, profile):
                archive.save(profile, profile_type='contact')
                changed_profiles += 1
    with MomentStore(moments_path) as archive:
        for feed in feeds:
            ident = str(feed.get('id') or feed.get('tid') or '')
            if not ident:
                raise ValueError('Moment has no stable identity')
            current = archive._connection.execute('SELECT raw_json FROM moments WHERE id=?', (ident,)).fetchone()
            if current is None or json.loads(current[0]) != feed:
                archive.save([feed])
                changed_moments.append(feed)
            for kind, key in (('image', 'images'), ('video', 'videos')):
                for index, media in enumerate(feed.get(key) or []):
                    fingerprint = hashlib.sha256(json.dumps(
                        [ident, kind, index, media], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    manifest.append({'item_id': fingerprint, 'moment_id': ident,
                                     'username': feed['username'], 'kind': kind, 'index': index,
                                     'media': media, 'status': 'pending_confirmation' if media.get('url') else 'unavailable',
                                     'downloaded': False, 'requires_confirmation': True})
    with MemoryStore(memory_path) as memory:
        indexer = ArchiveIndexer(memory)
        snapshots = indexer.index_profile_snapshots(profiles_path)
        feeds_by_author = defaultdict(list)
        for feed in feeds:
            feeds_by_author[feed['username']].append(feed)
        coverage = MomentsCollection(memory)
        for profile in profiles:
            person = memory.ensure_person(profile['wechat_id'], display_name=profile.get('display_name', ''),
                                          source='current_contact_snapshot', mark_active=False)
            for key in ('nickname', 'remark', 'alias', 'original_name'):
                memory.add_alias(person, key, str(profile.get(key) or ''), source='current_contact_snapshot')
            coverage.record(person, 'local_db', observation_key=f'{run_id}:{person}',
                            status='cached_only', count=len(feeds_by_author[profile['wechat_id']]),
                            reason='local_cache_not_server_history', evidence_ref=str(folder / 'summary.json'))
        # Unclassified contact rows can include retained/deleted/system records.
        # Archive availability is not proof of current friendship or deletion.
        for feed in changed_moments:
            person = memory.ensure_person(feed['username'], source='moments_archive', mark_active=False)
            memory.mark_dirty('person', person, 'moment_refresh', str(feed.get('id') or feed.get('tid')))
            memory.enqueue_job('person_analysis', 'person', person, priority=40)
        indexed = indexer.index_moments(moments_path)
    with (folder / 'media_manifest.jsonl').open('w', encoding='utf-8') as file:
        for item in manifest:
            file.write(json.dumps(item, ensure_ascii=False) + '\n')
    summary = {'run_id': run_id, 'contact_rows': len(profiles), 'profiles_changed': changed_profiles,
               'local_moments_total': len(all_feeds), 'contact_moments': len(feeds),
               'contact_authors_with_moments': len({f['username'] for f in feeds}),
               'moments_changed': len(changed_moments), 'new_moments_indexed': indexed['moments_seen'],
               'profile_snapshots_indexed': snapshots['snapshots_seen'], 'presence_audit_applied': False,
               'images': sum(m['kind'] == 'image' for m in manifest),
               'videos': sum(m['kind'] == 'video' for m in manifest),
               'pending_media': sum(m['status'] == 'pending_confirmation' for m in manifest),
               'unavailable_media': sum(m['status'] == 'unavailable' for m in manifest),
               'network_requests': 0, 'media_downloaded': 0, 'failures': 0,
               'source_scope': 'all_non_group_contact_rows_and_locally_available_moments',
               'updated_at': datetime.now(timezone.utc).isoformat(),
               'elapsed_seconds': round(time.monotonic() - started, 3)}
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


class LocalCollectionSource:
    """Open fresh DPAPI-keyed readonly copies for every collection stage."""
    def __init__(self, *, profiles_path='data/wechat_contact_profiles.sqlite3',
                 moments_path='data/wechat_moments.sqlite3', memory_path='data/wechat_memory.sqlite3',
                 output='data/moments_full_refresh', secrets='data/.secrets'):
        self.paths = {'profiles_path': profiles_path, 'moments_path': moments_path,
                      'memory_path': memory_path, 'output': output}
        self.secrets = secrets

    def get_profile(self, username):
        with open_dpapi_wechat_db(self.secrets, database_names=('contact.db',)) as db:
            return DatabaseProfileBackend(db).get_contact_profile(username)

    def refresh(self):
        with open_dpapi_wechat_db(self.secrets, database_names=('contact.db', 'sns.db')) as db:
            return refresh(db, **self.paths)
