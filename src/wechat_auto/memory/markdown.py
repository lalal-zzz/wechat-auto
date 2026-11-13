"""Compact, versioned Markdown views over structured memory."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import local
from uuid import uuid4

from wechat_auto.memory.store import MemoryStore


class MarkdownMemory:
    def __init__(self, root: str | Path, store: MemoryStore):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store
        self._publication_state = local()

    @contextmanager
    def publication(self, scope_type: str, scope_id: str, period: str = ""):
        """Hold the target lock through a caller's complete database commit."""
        directory = self._directory(scope_type, scope_id, period)
        directory.mkdir(parents=True, exist_ok=True)
        held = getattr(self._publication_state, 'held', set())
        if directory in held:
            yield
            return
        with self._write_lock(directory):
            self._publication_state.held = held | {directory}
            try:
                yield
            finally:
                self._publication_state.held = held

    def _rollback_publication(self, result: dict, previous_body: str | None):
        if not result.get('changed'):
            return
        current = Path(result['path'])
        version = Path(result['version_path'])
        if not current.resolve().is_relative_to(self.root) or not version.resolve().is_relative_to(self.root):
            raise ValueError('Publication rollback is outside the Memory root')
        if previous_body is None:
            current.unlink(missing_ok=True)
        else:
            self._atomic_write(current, previous_body)
        version.unlink(missing_ok=True)

    def recover_publication(self, scope_type: str, scope_id: str, period: str = "") -> dict:
        """Preserve unindexed files in work/analysis and restore only indexed text."""
        with self.publication(scope_type, scope_id, period), self.store.atomic():
            directory = self._directory(scope_type, scope_id, period)
            current = self.store.current_version(scope_type, scope_id, period)
            body = self.read_current(scope_type, scope_id, period) if current else None
            indexed = {int(row[0]) for row in self.store._connection.execute(
                'SELECT version FROM analysis_versions WHERE scope_type=? AND scope_id=? AND period=?',
                (scope_type, scope_id, period))}
            candidates = []
            for path in (directory / 'versions').glob('v*.md'):
                match = re.fullmatch(r'v(\d+)\.md', path.name)
                if match and int(match[1]) not in indexed:
                    candidates.append(path)
            candidates.extend((directory / 'versions').glob('*.tmp'))
            candidates.extend(directory.glob('current.md.*.tmp'))
            pointer = directory / 'current.md'
            mismatch = (pointer.read_bytes() != (body.encode('utf-8') if body is not None else None)
                        if pointer.is_file() else body is not None)
            if pointer.is_file() and mismatch:
                candidates.append(pointer)
            if not candidates and not mismatch:
                return {'changed': False, 'promoted': False, 'candidate_files': 0}
            work_root = (self.root.parent / 'work' / 'analysis').resolve()
            if work_root.is_relative_to(self.root):
                raise ValueError('Recovery directory must be outside formal Memory')
            recovery_id = 'recovery-' + uuid4().hex[:16]
            destination = work_root / recovery_id
            moves = []
            for source in sorted(set(candidates)):
                if not source.resolve().is_relative_to(self.root):
                    raise ValueError('Recovery source is outside formal Memory')
                target = destination / source.relative_to(directory)
                if not target.resolve().is_relative_to(destination):
                    raise ValueError('Recovery destination is outside its work directory')
                moves.append((source, target))
            destination.mkdir(parents=True, exist_ok=False)
            receipt = {'recovery_id': recovery_id, 'scope_type': scope_type, 'scope_id': scope_id,
                       'period': period, 'status': 'prepared', 'promoted': False,
                       'restored_version': int(current['version']) if current else None,
                       'files': [{'source': str(source), 'destination': str(target),
                                  'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
                                 for source, target in moves], 'run_states_unchanged': True}
            receipt_path = destination / 'recovery.json'
            self._atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2))
            moved = []
            restored_pointer = False
            pointer_existed = pointer.is_file()
            try:
                for (source, target), record in zip(moves, receipt['files']):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source, target)
                    moved.append((source, target))
                    if hashlib.sha256(target.read_bytes()).hexdigest() != record['sha256']:
                        raise RuntimeError('Recovery candidate changed while being preserved')
                if body is not None and mismatch:
                    self._atomic_write(pointer, body)
                    restored_pointer = True
                receipt['status'] = 'recovered'
                self._atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2))
            except BaseException:
                if restored_pointer and not pointer_existed:
                    pointer.unlink(missing_ok=True)
                for source, target in reversed(moved):
                    os.replace(target, source)
                raise
            return {'changed': True, 'promoted': False, 'recovery_id': recovery_id,
                    'work_dir': str(destination), 'candidate_files': len(moves),
                    'restored_version': receipt['restored_version'], 'run_states_unchanged': True}

    @staticmethod
    def _safe(value: str) -> str:
        text = str(value).strip()
        reserved = {'CON', 'PRN', 'AUX', 'NUL',
                    *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
        if (not text or text != str(value) or text in {".", ".."} or text.endswith('.')
                or any(ch in text for ch in '<>:"/\\|?*') or any(ord(ch) < 32 for ch in text)
                or text.split('.')[0].upper() in reserved):
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
        directory = self._directory(scope_type, scope_id, period)
        directory.mkdir(parents=True, exist_ok=True)
        with self.publication(scope_type, scope_id, period):
            current = self.store.current_version(scope_type, scope_id, period)
            parent = int(current["version"]) if current else 0
            if expected_parent is not None and parent != expected_parent:
                raise RuntimeError(f"stale Markdown parent: expected {expected_parent}, current {parent}")
            previous_body = self.read_current(scope_type, scope_id, period) if current else ""
            if current and current["content_hash"] == digest and current["input_fingerprint"] == input_fingerprint:
                return {"changed": False, "version": current["version"],
                        "path": current["markdown_path"], "content_hash": digest}
            version = parent + 1
            versions = directory / "versions"
            versions.mkdir(parents=True, exist_ok=True)
            version_path = versions / f"v{version:06d}.md"
            current_path = directory / "current.md"
            if version_path.exists():
                raise RuntimeError("Unindexed Markdown version exists; review required before writing")
            version_written = current_written = False
            try:
                self._atomic_write(version_path, body)
                version_written = True
                self._atomic_write(current_path, body)
                current_written = True
                recorded = self.store.record_version(
                    scope_type, scope_id, period, content_hash=digest,
                    markdown_path=str(version_path), input_fingerprint=input_fingerprint,
                    expected_parent=parent,
                )
            except BaseException:
                if current_written:
                    if current:
                        self._atomic_write(current_path, previous_body)
                    else:
                        current_path.unlink(missing_ok=True)
                if version_written:
                    version_path.unlink(missing_ok=True)
                raise
            return {"changed": True, "version": recorded, "path": str(current_path),
                    "version_path": str(version_path), "content_hash": digest}

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        temp = Path(name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    @contextmanager
    def _write_lock(directory: Path):
        import msvcrt

        # The OS releases this byte lock even after a process crash. The file
        # stays in place so another writer cannot lock a different inode.
        with (directory / '.write.lock').open('a+b') as stream:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('Memory target is already being written') from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def read_current(self, scope_type: str, scope_id: str, period: str = "") -> str:
        self._directory(scope_type, scope_id, period)
        current = self.store.current_version(scope_type, scope_id, period)
        if current is None:
            return ""
        # A crash may publish current.md before recording the index. Only an
        # indexed, hash-verified complete version is successful analysis.
        body = self.read_version(scope_type, scope_id, int(current['version']), period)
        if hashlib.sha256(body.encode('utf-8')).hexdigest() != current['content_hash']:
            raise RuntimeError('Indexed Markdown version failed integrity validation')
        return body

    def read_version(self, scope_type: str, scope_id: str, version: int,
                     period: str = "") -> str:
        indexed = self.store._connection.execute(
            'SELECT content_hash FROM analysis_versions WHERE scope_type=? AND scope_id=? AND period=? AND version=?',
            (scope_type, scope_id, period, version)).fetchone()
        if indexed is None:
            raise FileNotFoundError('No successfully indexed Markdown version')
        path = self._directory(scope_type, scope_id, period) / "versions" / f"v{version:06d}.md"
        if not path.is_file():
            raise FileNotFoundError(path)
        body = path.read_text(encoding="utf-8")
        if hashlib.sha256(body.encode('utf-8')).hexdigest() != indexed[0]:
            raise RuntimeError('Indexed Markdown version failed integrity validation')
        return body

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
