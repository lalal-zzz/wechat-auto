"""Export familiar direct contacts using message volume and local avatars."""
from __future__ import annotations

import argparse
import hashlib
import html
import sqlite3
from pathlib import Path

from wechat_auto.storage import ProfileStore


def _image_suffix(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def _safe(value: object) -> str:
    return html.escape(str(value or "（空）"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export familiar direct-contact profiles")
    parser.add_argument("--history", default="data/wechat_history_complete.sqlite3")
    parser.add_argument("--profiles", default="data/wechat_contact_profiles.sqlite3")
    parser.add_argument("--output-dir", default="data/familiar_contacts")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--add-watchlist", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        raise ValueError("limit must be between 1 and 20")

    history_path = Path(args.history).resolve(strict=True)
    profile_path = Path(args.profiles).resolve(strict=True)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(profile_path)
    try:
        connection.execute("ATTACH DATABASE ? AS history", (str(history_path),))
        rows = connection.execute("""
            SELECT p.wechat_id,p.nickname,p.remark,p.alias,p.signature,
                   m.content,COUNT(h.id) AS message_count
            FROM profiles p
            JOIN profile_media m
              ON m.profile_type='contact' AND m.wechat_id=p.wechat_id
             AND m.media_kind='avatar'
            JOIN history.messages h ON h.chat=p.wechat_id
            WHERE p.profile_type='contact'
              AND p.wechat_id NOT LIKE '%@chatroom'
              AND p.wechat_id NOT IN ('filehelper','notifymessage')
            GROUP BY p.wechat_id,p.nickname,p.remark,p.alias,p.signature,m.content
            ORDER BY message_count DESC,p.wechat_id
            LIMIT ?
        """, (args.limit,)).fetchall()
    finally:
        connection.close()

    lines = [
        "# 最熟悉的直接联系人",
        "",
        "> 排序依据：本地历史私聊消息量；仅选择已有本地头像 BLOB 的直接联系人。",
        "",
    ]
    with ProfileStore(profile_path) as store:
        for index, (wechat_id, nickname, remark, alias, signature, avatar, message_count) in enumerate(rows, 1):
            person_ref = "person_" + hashlib.sha256(str(wechat_id).encode()).hexdigest()[:10]
            avatar_bytes = bytes(avatar)
            avatar_path = output_dir / f"{person_ref}{_image_suffix(avatar_bytes)}"
            avatar_path.write_bytes(avatar_bytes)
            if args.add_watchlist:
                store.watch_contact(str(wechat_id), str(remark or nickname or alias or wechat_id))
            lines.extend([
                f"## {index}. {_safe(remark or nickname or alias)}",
                "",
                f"![头像]({avatar_path.as_posix()})",
                "",
                f"- 脱敏人员标识：`{person_ref}`",
                f"- 昵称：{_safe(nickname)}",
                f"- 备注：{_safe(remark)}",
                f"- 别名：{_safe(alias)}",
                f"- 历史私聊消息数：{int(message_count)}",
                f"- 个性签名：{_safe(signature or '待资料卡 OCR 采集')}",
                "",
            ])
    report = output_dir / "index.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
