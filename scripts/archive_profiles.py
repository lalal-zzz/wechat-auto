"""Archive self and every locally available direct-contact profile.

Reads the WeChat 4.x local database through the optional adapter and writes
only the project's SQLite snapshots.  No WeChat database, process memory, UI,
network resource, or avatar URL is modified/downloaded.  Stdout is a count-only
summary so private names, IDs, signatures, and avatar references are not leaked.
"""
from __future__ import annotations

import argparse
import json
import sys

from wechat_auto.backends import DatabaseProfileBackend
from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive local WeChat profiles safely")
    parser.add_argument("--database", default="data/wechat_contact_profiles.sqlite3",
                        help="project-local SQLite destination")
    parser.add_argument("--secret-dir", default="data/.secrets",
                        help="DPAPI-protected project key directory")
    parser.add_argument("--skip-self", action="store_true", help="do not archive the current account")
    args = parser.parse_args()
    try:
        with open_dpapi_wechat_db(
            args.secret_dir, database_names=("contact.db", "head_image.db")
        ) as db:
            profile_backend = DatabaseProfileBackend(db)
            contacts = profile_backend.archive_all_contact_profiles(args.database)
            avatars = profile_backend.archive_local_avatars(args.database)
            result = {"ok": True, "contacts": contacts, "avatars": avatars}
            if not args.skip_self:
                try:
                    self_result = profile_backend.archive_self_profile(args.database)
                    result["self"] = {
                        "archived": True,
                        "available_fields": self_result["available_fields"],
                        "changed_field_count": len(self_result["changed_fields"]),
                    }
                except NotImplementedError:
                    result["self"] = {"available": False, "reason": "adapter_does_not_expose_self_profile"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
