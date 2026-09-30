"""High-density context views for external agents."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

from wechat_auto.memory.store import MemoryStore


class ContextBuilder:
    def __init__(self, store: MemoryStore):
        self.store = store

    @staticmethod
    def _confidence_label(value: float) -> str:
        if value >= .8:
            return "高"
        if value >= .55:
            return "中"
        return "低"

    def compact_claims(self, *, person_id: str | None = None,
                       conversation_id: str | None = None, query: str = "",
                       limit: int = 30) -> dict:
        claims = self.store.search_claims(query=query, person_id=person_id,
                                          conversation_id=conversation_id, limit=limit)
        groups = {"confirmed": [], "observed": [], "inferred": []}
        for claim in claims:
            status = claim["status"]
            if status not in groups:
                continue
            dates = ""
            if claim.get("valid_from") or claim.get("valid_to"):
                dates = f"{claim.get('valid_from') or '?'}～{claim.get('valid_to') or '至今'}："
            groups[status].append(
                f"- {dates}{claim['canonical_text']} [{claim['claim_id']}]"
                f"（置信度：{self._confidence_label(float(claim['confidence']))}）"
            )
        labels = {"confirmed": "已确认", "observed": "直接观察", "inferred": "推断"}
        sections = []
        for key in ("confirmed", "observed", "inferred"):
            if groups[key]:
                sections.append(f"{labels[key]}：\n\n" + "\n".join(groups[key]))
        text = "\n\n".join(sections) if sections else "暂无相关记忆。"
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return {"text": text, "claim_count": sum(map(len, groups.values())),
                "fingerprint": fingerprint}

    def reply_context(self, conversation_id: str, current_messages: Iterable[dict], *,
                      person_id: str | None = None, claim_limit: int = 20) -> dict:
        messages = list(current_messages)
        memory = self.compact_claims(person_id=person_id,
                                     conversation_id=conversation_id, limit=claim_limit)
        rendered_messages = []
        for item in messages[-20:]:
            rendered_messages.append(
                f"- {item.get('time', '')} {item.get('sender', '')}: {item.get('content', '')}"
            )
        text = "当前消息：\n\n" + ("\n".join(rendered_messages) or "（无）")
        text += "\n\n相关记忆：\n\n" + memory["text"]
        fingerprint = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
        return {"text": text, "fingerprint": fingerprint,
                "message_count": len(messages), "claim_count": memory["claim_count"]}
