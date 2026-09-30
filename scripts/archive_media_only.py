"""Archive media blobs for messages already imported into HistoryStore."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wechatauto import MediaDownloader, WeChatDB

from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend
from wechat_auto.storage import HistoryStore, LocalSecretStore, make_message_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/wechat_history_full.sqlite3")
    parser.add_argument("--store", default="data/wechat_history.sqlite3")
    parser.add_argument("--include-images", action="store_true")
    parser.add_argument("--images-only", action="store_true")
    args = parser.parse_args()
    source = sqlite3.connect(args.source)
    source.row_factory = sqlite3.Row
    db = WeChatDB()
    backend = DatabaseConversationBackend(db)
    media_types = ("图片", "语音", "视频", "文件/链接/卡片")
    if args.images_only:
        query = "SELECT username,local_id,type,sender_id,sender_name,create_time,content,sort_seq,server_id FROM messages WHERE type=?"
        query_params = ("图片",)
    else:
        query = "SELECT username,local_id,type,sender_id,sender_name,create_time,content,sort_seq,server_id FROM messages WHERE type IN (?,?,?,?)"
        query_params = media_types
    total = media_count = errors = 0
    with tempfile.TemporaryDirectory(prefix="wechat-auto-media-") as media_dir:
        downloader = MediaDownloader(db, save_dir=media_dir)
        # WeChat stores several auxiliary ``*_W.dat`` files beside originals.
        # The dependency's default glob can pick one of those and reject a
        # valid image key, so seed it with a real 32-hex-name image blob.
        attach = os.path.join(db.account_dir, "msg", "attach")
        for root, _, files in os.walk(attach):
            probe = next((os.path.join(root, name) for name in files
                          if name.lower().endswith(".dat") and len(name) == 36
                          and name[:-4].isalnum()), None)
            if probe:
                downloader._probe_ct(probe)
                break
        if args.images_only:
            image_index = {}
            for root, _, files in os.walk(attach):
                for name in files:
                    if name.lower().endswith(".dat"):
                        image_index.setdefault(name, os.path.join(root, name))
            downloader._find_dat = lambda user, md5, create_time, thumbnail=False: image_index.get(
                md5 + ("_t.dat" if thumbnail else ".dat"))
        if args.include_images:
            image_key = downloader.detect_image_key(refresh=True)
            if image_key:
                downloader._img_key = image_key
                LocalSecretStore(Path(args.store).resolve().parent / ".secrets").save(
                    "wechat_image_key", {"aes_key": image_key[0], "xor_key": image_key[1]})
        with HistoryStore(args.store) as store:
            pending = []
            for row in source.execute(query, query_params):
                total += 1
                if row["type"] == "图片" and not args.include_images:
                    continue
                try:
                    media = backend._download_local_media(
                        downloader, row["username"], row["local_id"],
                        dict(row), media_dir, include_images=args.include_images)
                    if not media:
                        continue
                    media_count += len(media)
                    pending.append({
                        "id": make_message_id(row["username"], row["local_id"], row["sort_seq"], row["server_id"], row["type"]),
                        "chat": row["username"], "content": row["content"] or "",
                        "sender": row["sender_name"] or str(row["sender_id"] or ""),
                        "time": str(row["create_time"] or ""), "source": "wechat_db_media",
                        "raw": {"sort_seq": row["sort_seq"], "type": row["type"]},
                        "media": media,
                    })
                    if len(pending) >= 100:
                        store.save_messages(pending)
                        pending.clear()
                except Exception:
                    errors += 1
                if total % 100 == 0:
                    print(json.dumps({"media_messages_seen": total,
                                      "media_saved": media_count,
                                      "errors": errors}), flush=True)
            if pending:
                store.save_messages(pending)
    source.close()
    print(json.dumps({"media_messages_seen": total, "media_saved": media_count,
                      "errors": errors, "include_images": args.include_images}), flush=True)


if __name__ == "__main__":
    main()
