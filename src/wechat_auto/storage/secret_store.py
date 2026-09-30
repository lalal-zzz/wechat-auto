"""Machine-local secret storage for WeChat archive credentials.

Secrets are protected with Windows DPAPI and never printed or uploaded.  The
file is deliberately kept below the ignored ``data/.secrets`` directory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LocalSecretStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, value: dict[str, Any]) -> Path:
        try:
            import win32crypt
        except ImportError as exc:  # pragma: no cover - Windows dependency
            raise RuntimeError("Windows DPAPI dependency win32crypt is required") from exc
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        # pywin32 returns the protected blob directly on Windows.
        protected = win32crypt.CryptProtectData(payload, name, None, None, None, 0)
        path = self.directory / f"{name}.dpapi"
        path.write_bytes(protected)
        return path

    def load(self, name: str) -> dict[str, Any] | None:
        path = self.directory / f"{name}.dpapi"
        if not path.is_file():
            return None
        import win32crypt
        payload = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1]
        return json.loads(payload.decode("utf-8"))
