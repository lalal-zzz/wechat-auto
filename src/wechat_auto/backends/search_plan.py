"""Database-first Weixin search planning with no OCR dependency."""
from __future__ import annotations

from dataclasses import asdict, dataclass

SEARCH_SECTION_ORDER: dict[str, tuple[str, ...]] = {
    # Weixin 4.x main search: people-like entities precede content results.
    "main": ("contact", "group", "official_account", "chat_history",
             "mini_program", "channels", "web"),
    # Dedicated views intentionally exclude cross-category results.
    "contacts": ("contact",),
    "groups": ("group",),
}


def classify_search_candidate(item: dict) -> str:
    known = str(item.get("_known_target_kind") or "")
    if known in {"contact", "group", "official_account"}:
        return known
    username = str(item.get("username") or item.get("wechat_id") or "")
    if username.endswith("@chatroom"):
        return "group"
    local_type = int(item.get("local_type") or 0)
    if local_type == 3:
        return "contact"
    return "official_account"


def _exact(item: dict, query: str) -> bool:
    value = query.strip()
    fields = ("username", "wechat_id", "alias", "nick_name", "nickname",
              "remark", "display_name")
    return bool(value and value in {str(item.get(field) or "").strip() for field in fields})


@dataclass(frozen=True)
class SearchPlan:
    scene: str
    target_kind: str
    exact_target_count: int
    higher_priority_exact_count: int
    safe_without_ocr: bool
    selection_steps: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_search_plan(candidates: list[dict], query: str, *, target_kind: str,
                      scene: str = "main", allow_partial: bool = False) -> SearchPlan:
    """Plan only collision-free keyboard selection for one search scene."""
    if scene not in SEARCH_SECTION_ORDER:
        raise ValueError(f"Unsupported search scene: {scene}")
    order = SEARCH_SECTION_ORDER[scene]
    if target_kind not in order:
        raise ValueError(f"{target_kind!r} is not available in {scene!r} search")
    considered = candidates if allow_partial else [item for item in candidates if _exact(item, query)]
    exact = [(classify_search_candidate(item), item) for item in considered]
    targets = [item for kind, item in exact if kind == target_kind]
    target_index = order.index(target_kind)
    higher = [item for kind, item in exact
              if kind in order and order.index(kind) < target_index]
    safe = len(targets) == 1 and not higher
    return SearchPlan(
        scene=scene,
        target_kind=target_kind,
        exact_target_count=len(targets),
        higher_priority_exact_count=len(higher),
        safe_without_ocr=safe,
        selection_steps=0 if safe else -1,
    )
