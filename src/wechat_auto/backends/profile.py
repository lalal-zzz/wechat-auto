"""Read-only personal/contact profile adapter for the optional WeChat DB."""
from __future__ import annotations

import sqlite3

_ALIASES = {
    "name": ("name", "real_name", "display_name"),
    "wechat_id": ("wechat_id", "wxid", "username", "user_name"),
    "nickname": ("nickname", "nick_name"),
    "remark": ("remark", "remark_name"),
    "signature": ("signature", "sign", "description"),
    "avatar": ("avatar", "avatar_url", "head_image", "head_img", "big_head_url", "small_head_url"),
    "background_image": ("background_image", "background", "cover", "cover_url"),
    "alias": ("alias",),
    "avatar_md5": ("avatar_md5", "head_img_md5"),
    "original_name": ("original_name",),
    "display_name": ("display_name",),
    "group_display_name": ("group_display_name",),
}


class DatabaseProfileBackend:
    """Normalize profile fields without writing or decrypting data here.

    The optional database package has changed method names across releases;
    this adapter accepts the common variants and preserves the raw record.
    """

    def __init__(self, db):
        self._db = db

    @staticmethod
    def _normalize(record: dict) -> dict:
        if not isinstance(record, dict):
            raise TypeError("Profile record must be a dictionary")
        source = dict(record)
        identities = [source[key] for key in _ALIASES['wechat_id'] if source.get(key) not in (None, '')]
        if any(not isinstance(value, str) or not value.strip() for value in identities):
            raise ValueError("Profile stable identity must be nonempty text")
        identities = [value.strip() for value in identities]
        if len(set(identities)) > 1:
            raise ValueError("Conflicting profile stable identity fields")
        result = {key: next((source.get(alias) for alias in aliases
                             if source.get(alias) not in (None, "")), "")
                  for key, aliases in _ALIASES.items()}
        result["wechat_id"] = identities[0] if identities else ""
        nickname = result.get("nickname", "")
        result["nickname_core"] = nickname
        result["nickname_prefix"] = ""
        result["nickname_suffix"] = ""
        result["display_name"] = (result.get("display_name") or result.get("remark") or
                                   result.get("nickname") or result.get("wechat_id", ""))
        result["raw"] = source
        return result

    @staticmethod
    def _require_identity(profile: dict, expected: str | None = None) -> dict:
        identity = profile.get('wechat_id')
        if not identity or expected is not None and identity != expected:
            raise ValueError('Stable profile identity does not match requested account')
        return profile

    def _contact_row(self, username: str) -> dict | None:
        """Read confirmed contact.db fields when the optional adapter exposes them."""
        connection = self._open_contact_connection()
        if connection is None:
            return None
        try:
            row = connection.execute("""
                SELECT username,local_type,alias,nick_name,remark,description,
                       big_head_url,small_head_url,head_img_md5
                FROM contact WHERE username=? LIMIT 1
            """, (username,)).fetchone()
            if row is None:
                return None
            if hasattr(row, "keys"):
                return dict(row)
            return dict(zip(("username", "local_type", "alias", "nick_name", "remark", "description",
                             "big_head_url", "small_head_url", "head_img_md5"), row))
        except sqlite3.Error:
            # Contact schemas differ between WeChat releases.  A missing
            # optional column must not turn a read-only profile lookup into a
            # destructive migration or a failed history import.
            return None
        finally:
            connection.close()

    def _open_contact_connection(self):
        """Open the adapter's already-decrypted contact DB in read-only mode."""
        opener = getattr(self._db, "_contact_conn", None)
        if callable(opener):
            return opener()
        open_database = getattr(self._db, "_open", None)
        if not callable(open_database):
            return None
        for rel, path, _size in getattr(self._db, "_db_files", []):
            if str(path).replace("/", "\\").endswith("\\contact.db"):
                return open_database(rel)
        return None

    def _contact_rows(self) -> list[dict]:
        """Read every direct-contact row exposed by the local adapter.

        Group conversations are excluded by their stable ``@chatroom`` suffix.
        We intentionally preserve any other row returned by the local contact
        database: contact-type flags are version-specific and must not cause a
        real person to be silently dropped.
        """
        records = self._call_first(("get_contacts", "get_contact_list", "list_contacts"))
        if records is not None:
            if isinstance(records, (dict, str, bytes)):
                raise ValueError('Contact collection must contain profile records')
            items = list(records)
            if any(not isinstance(item, dict) for item in items):
                raise ValueError('Malformed contact collection; completeness is unknown')
            return [dict(item) for item in items]
        connection = self._open_contact_connection()
        if connection is None:
            raise NotImplementedError("This database adapter does not expose a contact list")
        try:
            rows = connection.execute("""
                SELECT username,local_type,alias,nick_name,remark,description,
                       big_head_url,small_head_url,head_img_md5
                FROM contact
                WHERE username IS NOT NULL AND username != ''
                ORDER BY username
            """).fetchall()
            keys = ("username", "local_type", "alias", "nick_name", "remark", "description",
                    "big_head_url", "small_head_url", "head_img_md5")
            return [dict(row) if hasattr(row, "keys") else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def _enrich(self, record: dict) -> dict:
        normalized = self._normalize(record)
        username = str(normalized.get("wechat_id", ""))
        row = self._contact_row(username) if username else None
        if row:
            normalized = self._normalize({**record, **row})
            normalized["avatar"] = row.get("big_head_url") or row.get("small_head_url") or ""
            normalized["avatar_md5"] = row.get("head_img_md5") or ""
            normalized["signature"] = row.get("description") or ""
            normalized["raw"] = {**record, **row}
        normalized["source"] = str(record.get("source") or "wechat_contact_db")
        return normalized

    def _call_first(self, names: tuple[str, ...], *args):
        for name in names:
            method = getattr(self._db, name, None)
            if callable(method):
                return method(*args)
        return None

    def get_self_profile(self) -> dict:
        # Some third-party adapters implement ``get_self_info`` but leak the
        # contact.db connection.  Prefer the stable account id plus our own
        # explicitly closed contact query when it is available.
        own_id = str(getattr(self._db, "wxid", "") or "").strip()
        if own_id:
            row = self._contact_row(own_id)
            if row:
                profile = self._normalize(row)
                profile["source"] = "wechat_contact_db"
                return self._require_identity(profile, own_id)
        record = self._call_first(("get_self_profile", "get_self_info", "get_account_info"))
        if record is None:
            raise NotImplementedError("This database adapter does not expose the self profile")
        return self._require_identity(self._enrich(record), own_id or None)

    def archive_self_profile(self, database_path: str) -> dict:
        """Read one profile snapshot and persist it to the local project DB."""
        from wechat_auto.storage import ProfileStore
        profile = self.get_self_profile()
        with ProfileStore(database_path) as store:
            result = store.save(profile, profile_type="self")
        return {"profile_type": "self", "database": database_path,
                "available_fields": [key for key, value in profile.items()
                                     if key != "raw" and value not in (None, "")],
                "media_downloaded": False, **result}

    def get_contact_profile(self, username: str) -> dict:
        if not isinstance(username, str) or not username.strip():
            raise ValueError("username must not be empty")
        username = username.strip()
        record = self._call_first(("get_contact_profile", "get_profile", "get_contact"), username)
        if record is None:
            matches = [item for item in self._db.search_contact(username)
                       if self._normalize(item)['wechat_id'] == username]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one stable profile match; found {len(matches)}")
            record = matches[0]
        self._require_identity(self._normalize(record), username)
        return self._require_identity(self._enrich(record), username)

    def get_group_members(self, group_id: str) -> list[dict]:
        """Read cached, explicitly scoped member identities without UI actions."""
        if (not isinstance(group_id, str) or not group_id.strip().endswith('@chatroom')
                or len(group_id.strip()) <= len('@chatroom')):
            raise ValueError('A stable group id ending in @chatroom is required')
        group_id = group_id.strip()
        method = getattr(self._db, "get_group_members", None)
        if not callable(method):
            raise NotImplementedError("This database adapter does not expose group members")
        records = method(group_id)
        if records is None or isinstance(records, (dict, str, bytes)):
            raise ValueError('Group member collection is malformed')
        members = []
        seen = set()
        for member in records:
            normalized = self._require_identity(self._normalize(member))
            username = normalized['wechat_id']
            if username.endswith('@chatroom') or username in seen:
                raise ValueError('Group member identity is duplicated or not a person')
            if any(member.get(key) not in (None, '', group_id) for key in ('group_id', 'chatroom_id')):
                raise ValueError('Member record belongs to a different group')
            seen.add(username)
            flag = member.get('is_owner')
            if flag is None:
                owner = None
            elif isinstance(flag, bool):
                owner = flag
            elif isinstance(flag, int) and flag in (0, 1):
                owner = bool(flag)
            elif isinstance(flag, str) and flag.casefold() in {'0', '1', 'false', 'true'}:
                owner = flag.casefold() in {'1', 'true'}
            else:
                raise ValueError('Group owner flag is not a recognized boolean')
            item = self._enrich({**member, 'wechat_id': username,
                                 'nickname': normalized['nickname'], 'display_name': '',
                                 'source': 'wechat_db', 'raw': dict(member)})
            self._require_identity(item, username)
            item['group_id'] = group_id
            item['group_display_name'] = member.get('group_display_name') or member.get('display_name', '')
            item['is_owner'] = owner
            members.append(item)
        return members

    def archive_contact_profile(self, username: str, database_path: str) -> dict:
        """Persist one contact snapshot; media values remain references only."""
        from wechat_auto.storage import ProfileStore
        profile = self.get_contact_profile(username)
        with ProfileStore(database_path) as store:
            result = store.save(profile, profile_type="contact")
        return {"profile_type": "contact", "wechat_id": profile["wechat_id"],
                "database": database_path,
                "available_fields": [key for key, value in profile.items()
                                     if key != "raw" and value not in (None, "")],
                "media_downloaded": False, **result}

    def get_all_contact_profiles(self, *, direct_contacts_only: bool = True) -> list[dict]:
        """Return normalized direct-contact profiles from the read-only DB.

        No UI actions, network calls, avatar downloads, or writes to WeChat
        occur here.  Results are deduplicated by stable ``wechat_id``.
        """
        profiles: list[dict] = []
        seen: set[str] = set()
        own_id = str(getattr(self._db, "wxid", "") or "").strip()
        for record in self._contact_rows():
            # ``_contact_rows`` already selected the enriched contact.db
            # fields.  Calling ``_enrich`` here would reopen/decrypt that
            # database once per contact.
            profile = self._normalize(record)
            profile["source"] = str(record.get("source") or "wechat_contact_db")
            wechat_id = str(profile.get("wechat_id", "")).strip()
            # In the current WeChat 4.x contact.db, local_type=3 represents
            # normal direct contacts.  Other rows include public accounts,
            # strangers, service/system records, and deleted entries.
            if (not wechat_id or wechat_id == own_id or wechat_id.endswith("@chatroom")
                    or wechat_id in seen
                    or (direct_contacts_only and int(record.get("local_type") or 0) != 3)):
                continue
            seen.add(wechat_id)
            profiles.append(profile)
        return profiles

    def archive_all_contact_profiles(self, database_path: str, *, direct_contacts_only: bool = True) -> dict:
        """Snapshot every available direct-contact profile into project SQLite.

        The summary intentionally contains counts only so scripts do not print
        friends' names, IDs, signatures, or avatar references to a terminal.
        """
        from wechat_auto.storage import ProfileStore

        profiles = self.get_all_contact_profiles(direct_contacts_only=direct_contacts_only)
        saved = 0
        changed = 0
        with ProfileStore(database_path) as store:
            for profile in profiles:
                result = store.save(profile, profile_type="contact")
                saved += 1
                changed += bool(result["changed_fields"])
        available = {
            field: sum(bool(profile.get(field)) for profile in profiles)
            for field in ("wechat_id", "alias", "nickname", "remark", "signature",
                          "avatar", "avatar_md5", "background_image")
        }
        return {"profile_type": "contact", "database": database_path,
                "scope": "direct_contacts" if direct_contacts_only else "all_contact_rows",
                "coverage_status": "cached_only", "server_contacts_complete": False,
                "contacts_seen": len(profiles), "snapshots_saved": saved,
                "profiles_changed": changed, "available_field_counts": available,
                "media_downloaded": False}

    def archive_local_avatars(self, database_path: str, *, direct_contacts_only: bool = True) -> dict:
        """Copy already-local avatar BLOBs into the project profile store.

        The head-image database is only read; no URL fetch or media download is
        attempted.  Restricting to the direct-contact ids keeps public-account
        and group avatar data out of this archive.
        """
        from wechat_auto.storage import ProfileStore

        allowed_ids = {
            item["wechat_id"] for item in self.get_all_contact_profiles(
                direct_contacts_only=direct_contacts_only
            )
        }
        connection = self._open_named_connection("head_image.db")
        if connection is None:
            return {"avatars_found": 0, "avatars_saved": 0, "bytes_saved": 0,
                    "media_downloaded": False, "available": False}
        try:
            rows = connection.execute("""
                SELECT username,image_buffer FROM head_image
                WHERE image_buffer IS NOT NULL AND length(image_buffer) > 0
            """).fetchall()
        finally:
            connection.close()
        saved = total_bytes = 0
        with ProfileStore(database_path) as store:
            for row in rows:
                username, image = str(row[0]), bytes(row[1])
                if username not in allowed_ids:
                    continue
                result = store.save_media(username, image, source="wechat_head_image_db")
                saved += 1
                total_bytes += result["bytes"]
        return {"avatars_found": saved, "avatars_saved": saved, "bytes_saved": total_bytes,
                "media_downloaded": False, "available": True}

    def _open_named_connection(self, file_name: str):
        open_database = getattr(self._db, "_open", None)
        if not callable(open_database):
            return None
        for rel, path, _size in getattr(self._db, "_db_files", []):
            if str(path).replace("/", "\\").endswith("\\" + file_name):
                return open_database(rel)
        return None

    def archive_group_members(self, group_id: str, database_path: str) -> dict:
        from wechat_auto.storage import ProfileStore

        profiles = self.get_group_members(group_id)
        group_id = group_id.strip()
        with ProfileStore(database_path) as store:
            results = store.save_group_members(profiles, group_id=group_id)
        return {'profile_type': 'group_member', 'group_id': group_id, 'database': database_path,
                'members': len(profiles), 'snapshots': [item['snapshot_id'] for item in results],
                'changed_fields': {item['wechat_id']: item['changed_fields'] for item in results},
                'coverage_status': 'cached_only', 'server_members_complete': False}
