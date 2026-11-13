"""Archive exact local Moments cache hits without any network fallback."""
from __future__ import annotations

import json
import re
from pathlib import Path


def download_approved_item(item: dict, archive, *, confirm: bool = False) -> dict:
    """Fetch one reviewed manifest item, validate it, and persist its BLOB."""
    if not confirm:
        raise PermissionError('One exact media item requires explicit confirmation')
    if (item.get('kind') not in {'image', 'video'} or not isinstance(item.get('index'), int)
            or item['index'] < 0):
        raise ValueError('Reviewed image/video kind and nonnegative item index required')
    import hashlib
    import urllib.error
    import urllib.parse
    import urllib.request

    expected = hashlib.sha256(json.dumps([item['moment_id'], item['kind'], item['index'], item['media']],
                                        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if expected != item['item_id'] or archive.get(item['moment_id']) is None:
        raise ValueError('Reviewed media identity changed or Moment absent')
    url = str(item['media'].get('url') or '')
    if urllib.parse.urlsplit(url).scheme not in {'https', 'http'}:
        raise ValueError('Media URL unavailable or unsupported')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0)'})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(64 * 1024 * 1024 + 1)
        if not data or len(data) > 64 * 1024 * 1024:
            return {'success': False, 'reason': 'empty_or_size_limit', 'automatic_retry': False}
        if item['kind'] == 'image':
            from io import BytesIO

            from PIL import Image
            with Image.open(BytesIO(data)) as image:
                image.verify()
        elif item['kind'] != 'video' or len(data) < 12 or data[4:8] != b'ftyp':
            return {'success': False, 'reason': 'invalid_media_format', 'automatic_retry': False}
        archive.save_media(item['item_id'], item['moment_id'], item['kind'], data, source='confirmed_remote_download')
        return {'success': True, 'bytes': len(data), 'automatic_retry': False}
    except urllib.error.HTTPError as exc:
        return {'success': False, 'reason': 'http_error', 'http_status': exc.code, 'automatic_retry': False}
    except (OSError, ValueError, SyntaxError):
        return {'success': False, 'reason': 'network_or_format_error', 'automatic_retry': False}


def archive_local_media(db, manifest: Path, archive, output: Path) -> dict:
    """Never match by file size or truncated hash; retain per-item failures."""
    root = Path(db.account_dir) / 'cache'
    index: dict[tuple[str, str], list[Path]] = {}
    for kind, folder in (('image', 'Img'), ('video', 'Video')):
        for path in root.glob(f'*/Sns/{folder}/*/*'):
            if path.is_file():
                digests = re.findall(r'[a-fA-F0-9]{32}', path.stem)
                # WeChat stores a 32-digit hash as a two-digit bucket plus
                # a 30-digit filename. Reconstruct it, never fuzzy-match it.
                if re.fullmatch(r'[a-fA-F0-9]{2}', path.parent.name) and re.fullmatch(r'[a-fA-F0-9]{30}', path.stem):
                    digests.append(path.parent.name + path.stem)
                for digest in digests:
                    index.setdefault((kind, digest.lower()), []).append(path)
    rows = [json.loads(line) for line in manifest.read_text(encoding='utf-8').splitlines() if line.strip()]
    output.mkdir(parents=True, exist_ok=True)
    counts = {'items': len(rows), 'archived': 0, 'cache_missing': 0, 'ambiguous': 0,
              'invalid_format': 0, 'read_failed': 0, 'network_requests': 0}
    records = []
    for row in rows:
        digest = str(row['media'].get('md5') or '').lower()
        paths = index.get((row['kind'], digest), []) if re.fullmatch(r'[a-f0-9]{32}', digest) else []
        status = 'cache_missing' if not paths else 'ambiguous' if len(paths) > 1 else 'archived'
        if status == 'archived':
            try:
                data = paths[0].read_bytes()
                if row['kind'] == 'image':
                    from io import BytesIO

                    from PIL import Image
                    with Image.open(BytesIO(data)) as image:
                        image.verify()
                elif len(data) < 12 or data[4:8] != b'ftyp':
                    status = 'invalid_format'
                if status == 'archived':
                    archive.save_media(row['item_id'], row['moment_id'], row['kind'], data)
            except OSError:
                status = 'read_failed'
            except (ValueError, SyntaxError):
                status = 'invalid_format'
        counts[status] += 1
        records.append({'item_id': row['item_id'], 'moment_id': row['moment_id'], 'status': status,
                        'requires_confirmation': status != 'archived' and bool(row['media'].get('url'))})
    (output / 'local_media_status.json').write_text(json.dumps(records), encoding='utf-8')
    (output / 'local_media_summary.json').write_text(json.dumps(counts), encoding='utf-8')
    return counts
