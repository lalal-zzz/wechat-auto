"""Local source-bound references for immutable profile snapshot evidence."""
import hashlib
import json
import os
import re
from pathlib import Path


def profile_source_key(path: str | Path) -> str:
    canonical = os.path.normcase(str(Path(path).resolve()))
    return hashlib.sha256(canonical.encode('utf-8', 'surrogatepass')).hexdigest()


def profile_content_hash(row) -> str:
    envelope = [row[key] for key in ('snapshot_id', 'profile_type', 'wechat_id', 'captured_at', 'profile_json', 'source')]
    text = json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()


def profile_reference(path: str | Path, snapshot_id: int, content_hash: str) -> str:
    return f'profile:{profile_source_key(path)}:{snapshot_id}:{content_hash}'


def parse_profile_reference(reference: str, path: str | Path) -> tuple[int, str] | None:
    match = re.fullmatch(r'profile:([0-9a-f]{64}):([1-9][0-9]{0,18}):([0-9a-f]{64})', reference)
    if not match or match[1] != profile_source_key(path):
        return None
    local_id = int(match[2])
    return (local_id, match[3]) if local_id <= 2**63-1 else None
