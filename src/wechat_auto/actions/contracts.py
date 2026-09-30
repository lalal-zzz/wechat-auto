"""Stable action receipts and calibrated Weixin layout profiles."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class LayoutProfile:
    wechat_version: str
    client_width: int
    client_height: int
    dpi: int = 96
    theme: str = "unknown"
    profile_id: str = "default"
    size_tolerance: int = 2
    elements: dict[str, list[float]] | None = None
    page_operations: dict[str, list[float]] | None = None

    def matches(self, width: int, height: int, *, dpi: int | None = None,
                wechat_version: str | None = None, theme: str | None = None) -> bool:
        return (abs(width - self.client_width) <= self.size_tolerance
                and abs(height - self.client_height) <= self.size_tolerance
                and (dpi is None or dpi == self.dpi)
                and (not wechat_version or wechat_version == self.wechat_version)
                and (not theme or self.theme == "unknown" or theme == self.theme))

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def point_for(self, page: int, element: int) -> tuple[float, float]:
        """Resolve a calibrated semantic element; never guess a missing point."""
        from wechat_auto.actions.semantics import semantic_key

        key = semantic_key(page, element)
        values = (self.elements or {}).get(key)
        if values is None or len(values) != 2:
            raise RuntimeError(f"Semantic coordinate {key} is not calibrated in this layout profile")
        x, y = float(values[0]), float(values[1])
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise RuntimeError(f"Semantic coordinate {key} is outside the client window")
        return x, y

    @classmethod
    def load(cls, path: str | Path) -> LayoutProfile:
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class ActionReceipt:
    action: str
    transport: str = "hwnd"
    verified_by: str = "not_verified"
    success: bool = True
    layout_profile: str = "default"
    point: tuple[float, float] | None = None
    receipt_id: str = ""
    executed_at: str = ""

    def to_dict(self) -> dict:
        values = asdict(self)
        values["receipt_id"] = self.receipt_id or f"ar{uuid4().hex[:12]}"
        values["executed_at"] = self.executed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        if values["point"] is not None:
            values["point"] = list(values["point"])
        return values
