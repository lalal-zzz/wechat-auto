"""Action receipts for current-frame visual controls."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4


class StaleFrameError(RuntimeError):
    """Window geometry changed after observation, before any input was sent."""


@dataclass(frozen=True)
class ActionReceipt:
    action: str
    transport: str = "hwnd"
    verified_by: str = "not_verified"
    success: bool = True
    coordinate_source: str = "observed_frame"
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
