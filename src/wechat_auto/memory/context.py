"""High-density context views for external agents."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections.abc import Iterable

from wechat_auto.memory.store import MemoryStore


class ContextBuilder:
    def __init__(self, store: MemoryStore, markdown=None, history_path=None):
        self.store = store
        self.markdown = markdown
        self.history_path = Path(history_path).resolve() if history_path else None

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

    def _formal_memories(self, conversation_id, person_id):
        if self.markdown is None:
            return []
        members = [row[0] for row in self.store._connection.execute(
            "SELECT DISTINCT person_id FROM conversation_members WHERE conversation_id=? AND valid_to IS NULL",
            (conversation_id,))]
        conversation = self.store.get_conversation(conversation_id)
        # Direct-chat imports may only link the peer. Resolve self by the
        # explicit Person type, never by a nickname or an arbitrary account.
        if conversation and conversation["conversation_type"] == "direct":
            selves = [row[0] for row in self.store._connection.execute(
                "SELECT person_id FROM people WHERE person_type='self' AND status='active'")]
            if len(selves) == 1 and selves[0] not in members:
                members.append(selves[0])
        if person_id and person_id not in members:
            raise ValueError("person_id is not an active member of this conversation")
        scopes = [("conversation", conversation_id, "")]
        if not self.store.current_version("conversation", conversation_id):
            scopes.extend(("conversation", conversation_id, period)
                          for period in self.markdown.list_periods(conversation_id))
        people_to_read = members if conversation and conversation["conversation_type"] == "direct" else ([person_id] if person_id else [])
        scopes.extend(("person", member, "") for member in people_to_read)
        if conversation and conversation["conversation_type"] == "direct" and len(members) == 2:
            left, right = sorted(members)
            scopes.extend(("relationship", row[0], "") for row in self.store._connection.execute(
                "SELECT relationship_id FROM relationships WHERE left_person_id=? AND right_person_id=?",
                (left, right)))
        result = []
        for scope, target, period in scopes:
            version = self.store.current_version(scope, target, period)
            if not version:
                continue
            path = Path(version["markdown_path"]).resolve()
            expected = (self.markdown._directory(scope, target, period) / "versions" /
                        f"v{version['version']:06d}.md").resolve()
            if path != expected or not path.is_relative_to(self.markdown.root) or not path.is_file():
                raise ValueError("formal Memory path is missing or invalid")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != version["content_hash"]:
                raise ValueError("formal Memory hash mismatch")
            body = data.decode("utf-8")
            metadata = body.split("---", 2)[1] if body.startswith("---\n") else ""
            match = re.search(r"^source_range:\s*(.+)$", metadata, re.M)
            result.append({"scope_type": scope, "scope_id": target, "period": period,
                           "version": version["version"], "path": str(path),
                           "content_hash": version["content_hash"],
                           "source_range": match[1].strip() if match else "unknown", "text": body})
        return result

    def _pending_messages(self, conversation_id, memories, limit, after_id):
        conversation = self.store.get_conversation(conversation_id)
        ranges = [m["source_range"] for m in memories
                  if m["scope_type"] == "conversation" and not m["period"]]
        ends = []
        for value in ranges:
            # A day precision boundary is deliberately reread from the start of
            # that day: later messages on the last analysed day must not be lost.
            match = re.fullmatch(r"\d{4}-\d{2}-\d{2}\s*/\s*(\d{4}-\d{2}-\d{2})", value)
            if match:
                ends.append(match[1])
        info = {"status": "unknown", "boundary": max(ends) if ends else None,
                "boundary_overlap": "last_analysed_day", "source": str(self.history_path) if self.history_path else None,
                "count": 0, "remaining_count": None, "next_after_id": ""}
        if not ends or not conversation or not self.history_path or not self.history_path.is_file():
            return [], info
        since = int(datetime.strptime(max(ends), "%Y-%m-%d").replace(
            tzinfo=timezone(timedelta(hours=8))).timestamp())
        with sqlite3.connect(self.history_path.as_uri() + "?mode=ro", uri=True) as db:
            cursor = 0
            if after_id:
                row = db.execute("SELECT rowid FROM messages WHERE id=? AND chat=?",
                                 (after_id, conversation["source_chat_id"])).fetchone()
                if not row:
                    raise ValueError("pending cursor is not in this conversation")
                cursor = row[0]
            epoch = "CASE WHEN length(message_time)=10 AND message_time NOT GLOB '*[^0-9]*' THEN CAST(message_time AS INTEGER) ELSE CAST(strftime('%s', message_time || CASE WHEN length(message_time)=19 THEN '+08:00' ELSE '' END) AS INTEGER) END"
            where = f"chat=? AND rowid>? AND ({epoch}>=? OR {epoch} IS NULL)"
            args = (conversation["source_chat_id"], cursor, since)
            total = db.execute("SELECT count(*) FROM messages WHERE " + where, args).fetchone()[0]
            rows = db.execute("SELECT id,sender,content,message_time,direction FROM messages WHERE " +
                              where + " ORDER BY rowid LIMIT ?", (*args, limit)).fetchall()
        messages = [dict(zip(("id", "sender", "content", "time", "direction"), row)) for row in rows]
        info.update(status="partial" if total > len(rows) else "archive_range_loaded",
                    count=len(rows), remaining_count=total-len(rows),
                    next_after_id=messages[-1]["id"] if total > len(rows) else "")
        return messages, info

    def reply_context(self, conversation_id: str, current_messages: Iterable[dict], *,
                      person_id: str | None = None, claim_limit: int = 20,
                      pending_limit: int = 200, pending_after_id: str = "") -> dict:
        if not 1 <= pending_limit <= 5000:
            raise ValueError("pending_limit must be from 1 through 5000")
        messages = list(current_messages)
        formal = self._formal_memories(conversation_id, person_id)
        pending, coverage = self._pending_messages(conversation_id, formal, pending_limit, pending_after_id)
        memory = self.compact_claims(person_id=person_id, conversation_id=conversation_id, limit=claim_limit)
        def render(items):
            return "\n".join(f"- {i.get('time', '')} {i.get('sender', '')} [{i.get('id', '')}]: {i.get('content', '')}" for i in items) or "（无）"
        text = "当前消息（优先依据）：\n\n" + render(messages)
        text += "\n\n分析覆盖边界起的原始消息（含末日重读，尚未归纳为分析结论）：\n\n" + render(pending)
        text += "\n\n已完成的正式分析（历史背景）：\n\n" + ("\n\n".join(
            f"来源：{m['path']} · v{m['version']} · {m['source_range']}\n{m['text']}" for m in formal) or "暂无正式分析。")
        text += "\n\n补充短记忆：\n\n" + memory["text"]
        text += f"\n\n增量读取状态：{coverage['status']}；未读条数：{coverage['remaining_count']}。最新明确表达优先于历史推断；未读完时继续分页，不能声称已覆盖全部增量。"
        fingerprint = hashlib.sha256((text + repr(coverage)).encode("utf-8", "surrogatepass")).hexdigest()
        return {"text": text, "fingerprint": fingerprint, "message_count": len(messages),
                "claim_count": memory["claim_count"], "memory_sources": [
                    {k: v for k, v in m.items() if k != "text"} for m in formal],
                "pending_messages": pending, "pending_coverage": coverage,
                "requires_more_data": coverage["status"] in {"partial", "unknown"}}
