"""One-time full archive of all local WeChat chats into offline SQLite."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wechatauto import WeChatDB

from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive all local WeChat messages and media")
    parser.add_argument("--store", default="data/wechat_history.sqlite3")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--skip-images", action="store_true",
                        help="skip image blobs when WeChat image AES key is unavailable")
    args = parser.parse_args()

    db = WeChatDB()
    result = DatabaseConversationBackend(db).archive_all_history(
        str(Path(args.store).resolve()),
        batch_size=args.batch_size,
        include_images=not args.skip_images,
        progress=lambda i, total, chat: print(
            json.dumps({"chat_index": i + 1, "chat_total": total, "chat": chat}, ensure_ascii=False),
            flush=True,
        ),
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
