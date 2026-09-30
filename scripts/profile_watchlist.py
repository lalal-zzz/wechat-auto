"""Manage the local fixed-contact signature watchlist without printing IDs."""
from __future__ import annotations

import argparse
import json

from wechat_auto.storage import ProfileStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage fixed profile observation contacts")
    parser.add_argument("--database", default="data/wechat_contact_profiles.sqlite3")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add", help="add one uniquely matched archived contact")
    add.add_argument("--contact", required=True, help="exact nickname, remark, alias, display name, or WeChat id")
    subparsers.add_parser("count", help="show only the enabled watchlist count")
    args = parser.parse_args()
    with ProfileStore(args.database) as store:
        if args.command == "add":
            store.watch_contact_by_display_name(args.contact)
        count = len(store.watched_contacts())
    print(json.dumps({"ok": True, "watchlist_count": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
