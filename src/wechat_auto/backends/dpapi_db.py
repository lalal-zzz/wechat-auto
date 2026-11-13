"""Open WeChat's local DB from already-known DPAPI-protected key material.

This module deliberately never scans WeChat process memory for keys.  It can
perform a one-time migration of an *existing* local ``wechatauto`` key cache
to the project's Windows-DPAPI secret store, then creates decrypted SQLite
working files only inside a temporary directory.
"""
from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from wechat_auto.backends.replica_import import replica_module
from wechat_auto.storage import LocalSecretStore

SECRET_NAME = "wechat_db_keys"


def _validate_keys(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise RuntimeError("No usable local WeChat database key cache")
    result: dict[str, str] = {}
    for rel, encoded in value.items():
        if not isinstance(rel, str) or not isinstance(encoded, str):
            raise TypeError("Invalid local WeChat database key cache")
        relative = PureWindowsPath(rel)
        if (not rel or relative.drive or relative.root or '..' in relative.parts
                or any(ord(ch) < 32 for ch in rel)):
            raise RuntimeError("Invalid local WeChat database key cache")
        try:
            decoded = bytes.fromhex(encoded)
        except ValueError as exc:
            raise RuntimeError("Invalid local WeChat database key cache") from exc
        if not decoded:
            raise RuntimeError("Invalid local WeChat database key cache")
        result[rel] = encoded
    return result


def migrate_existing_key_cache(secret_dir: str | Path) -> dict:
    """Protect one existing adapter cache with DPAPI; never print its contents."""
    store = LocalSecretStore(secret_dir)
    existing = store.load(SECRET_NAME)
    if existing is not None:
        return existing
    cache_root = Path(tempfile.gettempdir()) / "wechatauto_db"
    caches = sorted(cache_root.glob("*/keys.json"))
    if len(caches) != 1:
        raise RuntimeError("Expected exactly one existing local WeChat key cache")
    try:
        keys = _validate_keys(json.loads(caches[0].read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Cannot read existing local WeChat key cache") from exc
    payload = {"account": caches[0].parent.name, "keys": keys}
    store.save(SECRET_NAME, payload)
    return payload


@contextmanager
def open_dpapi_wechat_db(
    secret_dir: str | Path, *, database_names: tuple[str, ...] = ("contact.db",),
    include_message_family: bool = False,
) -> Iterator[object]:
    """Yield a read-only adapter DB built from DPAPI keys, without key scans."""
    module = replica_module('wechatauto.db')
    WeChatDB, auto_detect_db_dir = module.WeChatDB, module.auto_detect_db_dir

    payload = LocalSecretStore(secret_dir).load(SECRET_NAME)
    if payload is None:
        payload = migrate_existing_key_cache(secret_dir)
    if not isinstance(payload, dict):
        raise TypeError('Invalid local WeChat account configuration')
    keys = _validate_keys(payload.get("keys"))
    account = str(payload.get("account", "")).strip()
    account_path = PureWindowsPath(account)
    if (not account or account in {'.', '..'} or account_path.name != account
            or account_path.drive or account.endswith('.') or any(ord(ch) < 32 for ch in account)):
        raise RuntimeError('Invalid local WeChat account configuration')
    db_dir = auto_detect_db_dir()
    if not db_dir or not account:
        raise RuntimeError("Cannot locate the local WeChat account database")

    # ``WeChatDB.__init__`` scans memory and writes a plaintext cache when a
    # key is absent.  Build only the state required by its read-only query
    # methods, validate every key up front, and keep decrypted DB copies in a
    # TemporaryDirectory that is removed on exit.
    with tempfile.TemporaryDirectory(prefix="wechat-auto-profile-") as workdir:
        db = WeChatDB.__new__(WeChatDB)
        db.db_dir = db_dir
        db.account = account
        db.account_dir = str(Path(db_dir) / account)
        db.workdir = workdir
        db.keys_file = "<dpapi-managed>"
        db._keys = {rel: bytes.fromhex(encoded) for rel, encoded in keys.items()}
        # Do not spend minutes validating every historical message partition
        # when the caller needs a small, explicit set of read-only databases.
        wanted = {name.casefold() for name in database_names}
        db._db_files = [item for item in db._collect_db_files()
                        if (Path(item[1]).name.casefold() in wanted
                            or (include_message_family
                                and "message" in {
                                    part.casefold() for part in Path(item[1]).parts
                                }))]
        if not db._db_files:
            raise RuntimeError("Requested local WeChat database is unavailable")
        db.master_key = None
        db.cfg_dword = None
        db.unkeyed = [rel for rel, _, _ in db._db_files if not db._key_works(rel)]
        if db.unkeyed:
            raise RuntimeError("DPAPI key cache does not cover every current WeChat database")
        yield db
