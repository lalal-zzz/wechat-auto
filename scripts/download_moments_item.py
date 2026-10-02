"""Review or download exactly one manifest item after explicit user confirmation."""
import argparse
import json
from pathlib import Path

from wechat_auto.backends.moments_media import download_approved_item
from wechat_auto.storage import MomentStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--item-id', required=True)
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--database', default='data/wechat_moments.sqlite3')
    parser.add_argument('--output', type=Path, default=Path('data/moments_media/download_receipts'))
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.manifest.read_text(encoding='utf-8').splitlines() if line.strip()]
    items = [row for row in rows if row['item_id'] == args.item_id]
    if len(items) != 1:
        parser.error('Exact unique item required')
    if not args.confirm:
        print(json.dumps({'item_id': args.item_id, 'kind': items[0]['kind'], 'requires_confirmation': True,
                          'network_requests': 0}))
        return
    with MomentStore(args.database) as store:
        result = download_approved_item(items[0], store, confirm=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / (args.item_id + '.json')).write_text(json.dumps(result), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
