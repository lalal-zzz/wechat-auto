"""Refresh all local non-group contact rows and readable Moments, offline only."""
from __future__ import annotations

import argparse
import json
import logging

from wechat_auto.backends.collection_sync import refresh
from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles-db', default='data/wechat_contact_profiles.sqlite3')
    parser.add_argument('--moments-db', default='data/wechat_moments.sqlite3')
    parser.add_argument('--memory-db', default='data/wechat_memory.sqlite3')
    parser.add_argument('--output', default='data/moments_full_refresh')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        with open_dpapi_wechat_db('data/.secrets', database_names=('contact.db', 'sns.db')) as db:
            result = refresh(db, profiles_path=args.profiles_db, moments_path=args.moments_db,
                             memory_path=args.memory_db, output=args.output)
            print(json.dumps(result), flush=True)
    except Exception as exc:
        print(json.dumps({'success': False, 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
