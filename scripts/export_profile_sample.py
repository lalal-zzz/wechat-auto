"""Export a small local-only contact profile sample for visual verification."""
from __future__ import annotations

import argparse
import hashlib
import html
import sqlite3
from pathlib import Path


def _text(value) -> str:
    return html.escape(str(value or "（空）"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a private local profile sample")
    parser.add_argument("--database", default="data/wechat_contact_profiles.sqlite3")
    parser.add_argument("--output", default="data/profile_sample.md")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        raise ValueError("limit must be between 1 and 20")

    database = Path(args.database).resolve(strict=True)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("""
            SELECT p.wechat_id,p.nickname,p.remark,p.alias,p.signature,p.avatar_ref,
                   EXISTS(SELECT 1 FROM profile_media m
                          WHERE m.profile_type='contact' AND m.wechat_id=p.wechat_id
                            AND m.media_kind='avatar') AS avatar_blob
            FROM profiles p
            WHERE p.profile_type='contact'
            ORDER BY CASE WHEN COALESCE(p.remark,'') != '' THEN 0 ELSE 1 END,
                     p.display_name,p.wechat_id
            LIMIT ?
        """, (args.limit,)).fetchall()
    finally:
        connection.close()

    lines = [
        "# 联系人资料抽样核对",
        "",
        "> 本文件仅保存在本机 `data/`；完整微信号未展示。",
        "",
        "| 脱敏人员标识 | 昵称 | 备注 | 别名 | 个性签名 | 头像 |",
        "|---|---|---|---|---|---|",
    ]
    for wechat_id, nickname, remark, alias, signature, avatar_ref, avatar_blob in rows:
        person_ref = "person_" + hashlib.sha256(str(wechat_id).encode()).hexdigest()[:10]
        signature_display = signature or "（当前源未提供）"
        avatar = "本地 BLOB" if avatar_blob else ("有引用" if avatar_ref else "无")
        lines.append(
            f"| `{person_ref}` | {_text(nickname)} | {_text(remark)} | {_text(alias)} | "
            f"{_text(signature_display)} | {avatar} |"
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
