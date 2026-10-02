"""Archive exact local cache media into project SQLite; never access the network."""
import argparse
import json
from pathlib import Path

from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db
from wechat_auto.backends.moments_media import archive_local_media
from wechat_auto.storage import MomentStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--database', default='data/wechat_moments.sqlite3')
    parser.add_argument('--output', type=Path, default=Path('data/moments_media'))
    args = parser.parse_args()
    with open_dpapi_wechat_db('data/.secrets', database_names=('sns.db',)) as db, MomentStore(args.database) as store:
        print(json.dumps(archive_local_media(db, args.manifest, store, args.output)))


if __name__ == '__main__':
    main()
