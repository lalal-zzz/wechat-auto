"""Compact, versioned Markdown views over structured memory."""
from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path

from wechat_auto.memory.store import MemoryStore


class MarkdownMemory:
    def __init__(self, root: str | Path, store: MemoryStore):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store

    @staticmethod
    def _safe(value: str) -> str:
        text = str(value).strip()
        if not text or text in {".", ".."} or any(ch in text for ch in '<>:"/\\|?*'):
            raise ValueError(f"unsafe memory path component: {value!r}")
        return text

    def _directory(self, scope_type: str, scope_id: str, period: str = "") -> Path:
        plural = {"person": "people", "conversation": "conversations", "group": "groups",
                  "relationship": "relationships"}.get(scope_type)
        if plural is None:
            raise ValueError(f"unsupported memory scope: {scope_type}")
        base = self.root / plural / self._safe(scope_id)
        if period:
            if scope_type != "conversation":
                raise ValueError("period views are supported only for conversations")
            base = base / "months" / self._safe(period)
        return base

    def write(self, scope_type: str, scope_id: str, content: str, *, period: str = "",
              input_fingerprint: str, expected_parent: int | None = None) -> dict:
        body = content.strip() + "\n"
        if len(body) < 4:
            raise ValueError("memory Markdown must not be empty")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        current = self.store.current_version(scope_type, scope_id, period)
        if current and current["content_hash"] == digest and current["input_fingerprint"] == input_fingerprint:
            return {"changed": False, "version": current["version"],
                    "path": current["markdown_path"], "content_hash": digest}
        parent = int(current["version"]) if current else 0
        if expected_parent is not None and parent != expected_parent:
            raise RuntimeError(f"stale Markdown parent: expected {expected_parent}, current {parent}")
        version = parent + 1
        directory = self._directory(scope_type, scope_id, period)
        versions = directory / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        version_path = versions / f"v{version:06d}.md"
        current_path = directory / "current.md"
        self._atomic_write(version_path, body)
        self._atomic_write(current_path, body)
        try:
            recorded = self.store.record_version(
                scope_type, scope_id, period, content_hash=digest,
                markdown_path=str(version_path), input_fingerprint=input_fingerprint,
                expected_parent=expected_parent,
            )
        except Exception:
            version_path.unlink(missing_ok=True)
            if current:
                previous = Path(str(current["markdown_path"]))
                if previous.is_file():
                    self._atomic_write(current_path, previous.read_text(encoding="utf-8"))
            else:
                current_path.unlink(missing_ok=True)
            raise
        return {"changed": True, "version": recorded, "path": str(current_path),
                "version_path": str(version_path), "content_hash": digest}

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temp, path)

    def read_current(self, scope_type: str, scope_id: str, period: str = "") -> str:
        path = self._directory(scope_type, scope_id, period) / "current.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def read_version(self, scope_type: str, scope_id: str, version: int,
                     period: str = "") -> str:
        path = self._directory(scope_type, scope_id, period) / "versions" / f"v{version:06d}.md"
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    def compare(self, scope_type: str, scope_id: str, left: int, right: int,
                period: str = "") -> str:
        before = self.read_version(scope_type, scope_id, left, period).splitlines()
        after = self.read_version(scope_type, scope_id, right, period).splitlines()
        return "\n".join(difflib.unified_diff(
            before, after, fromfile=f"v{left:06d}.md", tofile=f"v{right:06d}.md", lineterm=""
        ))

    def list_periods(self, conversation_id: str) -> list[str]:
        base = self._directory("conversation", conversation_id) / "months"
        if not base.is_dir():
            return []
        return sorted(path.name for path in base.iterdir()
                      if path.is_dir() and (path / "current.md").is_file())
