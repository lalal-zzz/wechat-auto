"""Machine-local secret storage for WeChat archive credentials.

Secrets are protected with Windows DPAPI and never printed or uploaded.  The
file is deliberately kept below the ignored ``data/.secrets`` directory.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class LocalSecretStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name)
                or name.split('.')[0].upper() in {
                    'CON', 'PRN', 'AUX', 'NUL',
                    *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10)),
                }):
            raise ValueError('Secret name must be a portable filename without directory components')
        return self.directory / f"{name}.dpapi"

    def save(self, name: str, value: dict[str, Any]) -> Path:
        path = self._path(name)
        try:
            import win32crypt
        except ImportError as exc:  # pragma: no cover - Windows dependency
            raise RuntimeError("Windows DPAPI dependency win32crypt is required") from exc
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        # pywin32 returns the protected blob directly on Windows.
        protected = win32crypt.CryptProtectData(payload, name, None, None, None, 0)
        descriptor, temporary = tempfile.mkstemp(prefix='.secret-', suffix='.tmp', dir=self.directory)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(protected)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return path

    def load(self, name: str) -> dict[str, Any] | None:
        path = self._path(name)
        if not path.is_file():
            return None
        import win32crypt
        payload = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1]
        return json.loads(payload.decode("utf-8"))
