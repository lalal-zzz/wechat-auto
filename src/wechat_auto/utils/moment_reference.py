"""Source- and record-bound immutable Moment version references."""
import hashlib
import json
import re
from pathlib import Path

from wechat_auto.utils.profile_reference import profile_source_key

VERSION_COLUMNS = ('version_id', 'observed_at', 'verification_status', 'id', 'username',
                   'nickname', 'create_time', 'text', 'images_json', 'videos_json',
                   'likes_json', 'comments_json', 'raw_json')


def validate_moment_subject(row):
    raw = json.loads(row['raw_json'])
    if (not isinstance(raw, dict) or not isinstance(raw.get('username'), str)
            or raw['username'].strip() != row['username']
            or str(raw.get('id') or raw.get('tid') or '').strip() != row['id']):
        raise ValueError('Moment version subject identity mismatch')


def moment_version_hash(row) -> str:
    text = json.dumps([row[key] for key in VERSION_COLUMNS], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()


def moment_reference(path: str | Path, version_id: int, digest: str) -> str:
    return f'moment:{profile_source_key(path)}:{version_id}:{digest}'


def parse_moment_reference(reference: str, path: str | Path) -> tuple[int, str] | None:
    match = re.fullmatch(r'moment:([0-9a-f]{64}):([1-9][0-9]{0,18}):([0-9a-f]{64})', reference)
    if not match or match[1] != profile_source_key(path):
        return None
    version = int(match[2])
    return (version, match[3]) if version <= 2**63-1 else None
