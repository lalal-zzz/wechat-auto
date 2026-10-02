"""Directional relationship observations; never mutate the WeChat client."""
from __future__ import annotations

import hashlib
import json

from wechat_auto.memory.store import _now

RELATIONS = {'local_contact', 'local_block', 'peer_contact', 'peer_block', 'moments_access'}
VALUES = {
    'local_contact': {'present', 'removed', 'unknown'},
    'local_block': {'blocked', 'unblocked', 'unknown'},
    'peer_contact': {'removed', 'unknown'},
    'peer_block': {'blocked', 'unknown'},
    'moments_access': {'visible', 'restricted', 'unavailable', 'unknown'},
}


class ContactState:
    def __init__(self, store):
        self.store = store
        self.db = store._connection

    def record(self, person_id: str, relation: str, value: str, *, source: str,
               evidence_ref: str, observation_key: str, confirmed: bool = False,
               observed_at: str = '') -> dict:
        """Accept attributable reviewed evidence or an explicit user correction.

        OCR callers may only record access observations. Removal/blocking signals
        need review; this API does not pretend an unimplemented parser exists.
        """
        if relation not in RELATIONS or value not in VALUES[relation]:
            raise ValueError('Unsupported directional relationship state')
        if not evidence_ref or not observation_key:
            raise ValueError('An evidence reference and stable observation key are required')
        if source not in {'user_confirmation', 'reviewed_system_signal', 'ui_observation'}:
            raise ValueError('Unsupported status source')
        if (relation != 'moments_access' and value != 'unknown'
                and (not confirmed or source == 'ui_observation')):
            raise PermissionError('Removal/blocking requires an explicitly reviewed signal')
        if not self.db.execute('SELECT 1 FROM people WHERE person_id=?', (person_id,)).fetchone():
            raise ValueError('Unknown person')
        payload = [person_id, relation, value, source, evidence_ref, confirmed]
        fingerprint = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        existing = self.db.execute('SELECT * FROM contact_state_history WHERE observation_key=?',
                                   (observation_key,)).fetchone()
        if existing:
            if existing['fingerprint'] != fingerprint:
                raise ValueError('Observation key reused with different evidence')
            return dict(existing)
        now = observed_at or _now()
        with self.db:
            self.db.execute('INSERT INTO contact_state_history VALUES(?,?,?,?,?,?,?,?,?)',
                            (observation_key, person_id, relation, value, source,
                             evidence_ref, int(confirmed), now, fingerprint))
        self.store.mark_dirty('person', person_id, reason='contact_state_change')
        return dict(self.db.execute('SELECT * FROM contact_state_history WHERE observation_key=?',
                                    (observation_key,)).fetchone())

    def get(self, person_id: str) -> dict:
        rows = [dict(row) for row in self.db.execute(
            'SELECT * FROM contact_state_history WHERE person_id=? ORDER BY observed_at,rowid',
            (person_id,))]
        current = {relation: 'unknown' for relation in RELATIONS}
        for row in rows:
            current[row['relation']] = row['value']
        presence = self.db.execute('SELECT status FROM people WHERE person_id=?', (person_id,)).fetchone()
        stop = (not presence or presence[0] in {'missing', 'inferred_removed', 'confirmed_removed', 'unknown'}
                or current['local_contact'] == 'removed' or current['local_block'] == 'blocked'
                or current['peer_contact'] == 'removed' or current['peer_block'] == 'blocked')
        return {'person_id': person_id, 'presence': presence[0] if presence else 'unknown',
                'current': current, 'history': rows, 'automatic_send_blocked': bool(stop),
                'identity_verification_still_required': True}
