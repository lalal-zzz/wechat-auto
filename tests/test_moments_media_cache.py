import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from wechat_auto.backends.moments_media import (
    archive_local_media,
    download_approved_item,
)
from wechat_auto.storage import MomentStore


def test_sharded_hash_import_and_missing_media_do_not_access_network(tmp_path):
    digest = 'ab' + '1' * 30
    folder = tmp_path / 'cache/2026-10/Sns/Img/ab'
    folder.mkdir(parents=True)
    Image.new('RGB', (8, 8), 'red').save(folder / digest[2:], format='PNG')
    manifest = tmp_path / 'manifest.jsonl'
    manifest.write_text('\n'.join(json.dumps({'item_id': key, 'moment_id': 'm1', 'kind': 'image',
                                             'media': {'md5': md5, 'url': 'https://example.invalid'}})
                                  for key, md5 in [('ok', digest), ('missing', '2'*32)]), encoding='utf-8')
    with MomentStore(tmp_path / 'moments.db') as store:
        store.save([{'id': 'm1', 'username': 'wxid_test_1'}])
        result = archive_local_media(SimpleNamespace(account_dir=tmp_path), manifest, store, tmp_path / 'results')
        assert result['archived'] == 1 and result['cache_missing'] == 1
        assert result['network_requests'] == 0
        row = store._connection.execute('SELECT content FROM message_media WHERE media_id=?', ('ok',)).fetchone()
        assert row[0].startswith(b'\x89PNG')
        archive_local_media(SimpleNamespace(account_dir=tmp_path), manifest, store, tmp_path / 'results')
        assert store._connection.execute('SELECT count(*) FROM message_media').fetchone()[0] == 1


def item():
    data = {'moment_id': 'm1', 'kind': 'image', 'index': 0,
            'media': {'url': 'https://example.invalid/private-image'}}
    data['item_id'] = hashlib.sha256(json.dumps([data['moment_id'], data['kind'], data['index'], data['media']],
                                              sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return data


def test_remote_requires_confirmation_and_unchanged_review(tmp_path, monkeypatch):
    import urllib.request

    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Network must not run'))
    with MomentStore(tmp_path / 'm.db') as store:
        store.save([{'id': 'm1', 'username': 'wxid_test_1'}])
        with pytest.raises(PermissionError):
            download_approved_item(item(), store)
        changed = item()
        changed['media']['url'] = 'https://example.invalid/changed'
        with pytest.raises(ValueError, match='identity changed'):
            download_approved_item(changed, store, confirm=True)


def test_one_confirmed_remote_image_is_validated_and_saved(tmp_path, monkeypatch):
    import urllib.request

    content = BytesIO()
    Image.new('RGB', (6, 6), 'blue').save(content, format='PNG')
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: BytesIO(content.getvalue()))
    with MomentStore(tmp_path / 'm.db') as store:
        store.save([{'id': 'm1', 'username': 'wxid_test_1'}])
        result = download_approved_item(item(), store, confirm=True)
        assert result['success'] and not result['automatic_retry']
        row = store._connection.execute('SELECT content,source FROM message_media').fetchone()
        assert row == (content.getvalue(), 'confirmed_remote_download')


@pytest.mark.parametrize('failure', ['http', 'timeout', 'invalid_image', 'empty'])
def test_remote_failure_does_not_retry_or_modify_existing_media(tmp_path, monkeypatch, failure):
    import urllib.error
    import urllib.request

    request = MagicMock()
    if failure == 'http':
        request.side_effect = urllib.error.HTTPError('https://example.invalid', 403, 'synthetic', {}, None)
    elif failure == 'timeout':
        request.side_effect = TimeoutError('synthetic')
    else:
        request.return_value = BytesIO(b'invalid image' if failure == 'invalid_image' else b'')
    monkeypatch.setattr(urllib.request, 'urlopen', request)
    with MomentStore(tmp_path / 'm.db') as store:
        store.save([{'id': 'm1', 'username': 'wxid_test_one'}])
        reviewed = item()
        store.save_media(reviewed['item_id'], 'm1', 'image', b'original')
        result = download_approved_item(reviewed, store, confirm=True)
        assert not result['success'] and not result['automatic_retry']
        assert request.call_count == 1
        assert store._connection.execute('SELECT content FROM message_media').fetchone()[0] == b'original'


def test_unsupported_kind_is_rejected_before_network(tmp_path, monkeypatch):
    import urllib.request

    request = MagicMock()
    monkeypatch.setattr(urllib.request, 'urlopen', request)
    with MomentStore(tmp_path / 'm.db') as store:
        reviewed = item()
        reviewed['kind'] = 'unsupported'
        with pytest.raises(ValueError, match='image/video'):
            download_approved_item(reviewed, store, confirm=True)
    request.assert_not_called()
