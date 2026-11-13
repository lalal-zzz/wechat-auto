"""Event-driven Windows directory watcher; it does not poll WeChat."""
from __future__ import annotations

from pathlib import Path


class WindowsDirectoryWatcher:
    """Wait for a directory write event using the Windows notification API."""
    def __init__(self, directory: str | Path, recursive: bool = True):
        self.directory = str(Path(directory).resolve())
        self.recursive = recursive
        self._handle = None

    def start(self) -> None:
        if self._handle is not None:
            return
        import win32con
        import win32file
        self._handle = win32file.FindFirstChangeNotification(
            self.directory, self.recursive,
            win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE,
        )

    def wait(self, timeout_ms: int = 60_000) -> bool:
        """Block until a write event, returning false only on timeout."""
        if self._handle is None:
            self.start()
        import win32con
        import win32event
        import win32file
        result = win32event.WaitForSingleObject(self._handle, timeout_ms)
        if result == win32con.WAIT_TIMEOUT:
            return False
        if result != win32con.WAIT_OBJECT_0:
            raise OSError(f"Directory notification wait failed: {result}")
        win32file.FindNextChangeNotification(self._handle)
        return True

    def close(self) -> None:
        if self._handle is not None:
            import win32file
            win32file.FindCloseChangeNotification(self._handle)
            self._handle = None
