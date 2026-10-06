"""Resumable per-person, per-path Moments coverage (not server completeness)."""
from __future__ import annotations

import hashlib
import json

from wechat_auto.memory.store import _now


class MomentsCollection:
    def __init__(self, store):
        self.store = store
        self.db = store._connection

    def record(self, person_id: str, path: str, *, observation_key: str, status: str,
               count: int = 0, pages: int = 0, reason: str = '', evidence_ref: str = '',
               oldest_at: str = '', newest_at: str = '', sections: list[dict] | None = None) -> dict:
        if path not in {'local_db', 'ui_load'}:
            raise ValueError('Unknown collection path')
        if status not in {'cached_only', 'partial', 'restricted', 'unavailable', 'stalled', 'failed'}:
            raise ValueError('Unknown coverage status; full server coverage cannot be certified')
        if count < 0 or pages < 0 or not observation_key:
            raise ValueError('Invalid coverage observation')
        if not self.db.execute('SELECT 1 FROM people WHERE person_id=?', (person_id,)).fetchone():
            raise ValueError('Unknown person')
        data = [person_id, path, status, count, pages, reason, evidence_ref, oldest_at, newest_at]
        normalized = []
        for item in sections or []:
            row = {key: item.get(key, '') for key in
                   ('section', 'status', 'visibility_window', 'visibility_hint')}
            if (row['section'] not in {'pinned', 'regular'} or
                    row['status'] not in {'unknown', 'observed', 'restricted'} or
                    row['visibility_window'] not in {'unknown', 'three_days', 'one_month', 'six_months'} or
                    (row['section'] == 'pinned' and row['visibility_window'] != 'unknown')):
                raise ValueError('Invalid Moments section observation')
            if any(previous['section'] == row['section'] for previous in normalized):
                raise ValueError('Duplicate Moments section')
            normalized.append(row)
        normalized.sort(key=lambda row: row['section'])
        fingerprint = hashlib.sha256(json.dumps(
            data if sections is None else [*data, normalized]).encode()).hexdigest()
        old = self.db.execute('SELECT * FROM moments_coverage WHERE observation_key=?', (observation_key,)).fetchone()
        if old:
            if old['fingerprint'] != fingerprint:
                raise ValueError('Coverage key reused with different data')
            return self._with_sections(dict(old))
        with self.db:
            self.db.execute('INSERT INTO moments_coverage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                            (observation_key, *data, _now(), fingerprint))
            self.db.executemany('INSERT INTO moments_section_coverage VALUES(?,?,?,?,?)',
                                [(observation_key, row['section'], row['status'],
                                  row['visibility_window'], row['visibility_hint']) for row in normalized])
        return self._with_sections(dict(self.db.execute('SELECT * FROM moments_coverage WHERE observation_key=?',
                                    (observation_key,)).fetchone()))

    def _with_sections(self, row: dict) -> dict:
        observed = {item['section']: dict(item) for item in self.db.execute(
            'SELECT section,status,visibility_window,visibility_hint FROM moments_section_coverage '
            'WHERE observation_key=?', (row['observation_key'],))}
        row['sections'] = [observed.get(section, {
            'section': section, 'status': 'unknown', 'visibility_window': 'unknown', 'visibility_hint': ''
        }) for section in ('pinned', 'regular')]
        return row

    def get(self, person_id: str) -> dict:
        history = [self._with_sections(dict(r)) for r in self.db.execute(
            'SELECT * FROM moments_coverage WHERE person_id=? ORDER BY observed_at,rowid', (person_id,))]
        current = {}
        for row in history:
            current[row['path']] = row
        return {'person_id': person_id, 'current': current, 'history': history,
                'server_history_complete': False}

    def enqueue(self, person_ids: list[str]) -> dict:
        # Do not treat all contact.db rows as eligible friends: service/system
        # accounts and retained deleted contacts need an explicit eligibility review.
        added = 0
        with self.db:
            for person in set(person_ids):
                row = self.db.execute('SELECT person_type FROM people WHERE person_id=?', (person,)).fetchone()
                if not row or row[0] != 'contact':
                    raise ValueError('Queue accepts known contact people only')
                added += self.db.execute("INSERT OR IGNORE INTO moments_load_queue VALUES(?, 'pending', '', ?)",
                                         (person, _now())).rowcount
        return {'added': added, 'existing_entries_preserved': True}

    def queue(self) -> list[dict]:
        return [dict(r) for r in self.db.execute('SELECT * FROM moments_load_queue ORDER BY updated_at,person_id')]

    def run_one(self, person_id: str, skill, *, sync_after_load, max_pages: int = 5) -> dict:
        from wechat_auto.memory.contact_state import ContactState
        if not 1 <= max_pages <= 30:
            raise ValueError('max_pages must be between 1 and 30')
        entry = self.db.execute('SELECT status FROM moments_load_queue WHERE person_id=?', (person_id,)).fetchone()
        if not entry or entry[0] not in {'pending', 'failed', 'partial'}:
            raise ValueError('Contact is not queued or already running')
        contact_state = ContactState(self.store).get(person_id)
        if contact_state['moments_load_blocked']:
            raise PermissionError('Contact state requires review before UI loading')
        identity = self.db.execute("SELECT identity_value FROM person_identities WHERE person_id=? AND identity_type='wxid'",
                                   (person_id,)).fetchall()
        if len(identity) != 1:
            raise ValueError('Stable contact identity absent or ambiguous')
        with self.db:
            updated = self.db.execute("UPDATE moments_load_queue SET status='running',updated_at=? "
                                      "WHERE person_id=? AND status IN ('pending','failed','partial')",
                                      (_now(), person_id)).rowcount
        if updated != 1:
            raise RuntimeError('Contact queue entry already claimed')
        try:
            profile = sync_after_load.get_profile(identity[0][0])
            alias = profile.get('alias', '')
            label = profile.get('remark') or profile.get('nickname') or alias
            if not alias or not label:
                raise ValueError('Visible identity field absent; no UI action taken')
            result = skill.load_contact_moments(label, alias, max_pages=max_pages,
                                                wechat_id=identity[0][0])
            # Reopen the readonly DB after UI loading, not the old decrypted snapshot.
            sync = sync_after_load.refresh()
            coverage = self.record(person_id, 'ui_load', observation_key=result['receipt_id'],
                                   status=result['coverage_status'], pages=result['pages'],
                                   reason=result['stop_reason'], evidence_ref=result.get('evidence_ref', ''),
                                   sections=result.get('section_coverage'))
            if result['coverage_status'] == 'restricted':
                ContactState(self.store).record(
                    person_id, 'moments_access', 'restricted', source='ui_observation',
                    evidence_ref=result.get('evidence_ref') or result['receipt_id'],
                    observation_key='access:' + result['receipt_id'])
            status = 'partial'
            return {'coverage': coverage, 'sync': sync, 'server_history_complete': False,
                    'identity_review_required_before_load': contact_state['moments_identity_review_required'],
                    'requires_navigation_restore': result.get('requires_navigation_restore', True)}
        except Exception as exc:
            status = 'failed'
            # Private exception messages can contain labels: persist only the type.
            reason = type(exc).__name__
            from uuid import uuid4
            self.record(person_id, 'ui_load', observation_key=uuid4().hex,
                        status='failed', reason=reason)
            raise
        finally:
            with self.db:
                self.db.execute('UPDATE moments_load_queue SET status=?,last_error=?,updated_at=? WHERE person_id=?',
                                (status, locals().get('reason', ''), _now(), person_id))

    def recover_interrupted(self, person_id: str) -> bool:
        """Explicit recovery after verifying the previous collector process ended."""
        with self.db:
            return bool(self.db.execute("UPDATE moments_load_queue SET status='failed',last_error='interrupted',updated_at=? "
                                        "WHERE person_id=? AND status='running'", (_now(), person_id)).rowcount)
