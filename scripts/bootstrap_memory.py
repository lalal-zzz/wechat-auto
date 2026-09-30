"""Index local archives and queue the initial top-five analysis set."""
from __future__ import annotations

import argparse

from wechat_auto.memory import AnalysisService, MarkdownMemory, MemoryStore
from wechat_auto.memory.indexer import ArchiveIndexer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-db", default="data/wechat_memory.sqlite3")
    parser.add_argument("--memory-root", default="data/memory")
    parser.add_argument("--history-db", required=True)
    parser.add_argument("--profiles-db")
    parser.add_argument("--moments-db")
    args = parser.parse_args()
    with MemoryStore(args.memory_db) as store:
        indexer = ArchiveIndexer(store)
        result = {}
        result["history"] = indexer.index_history(args.history_db)
        if args.profiles_db:
            result["profiles"] = indexer.index_profiles(args.profiles_db)
            result["profile_snapshots"] = indexer.index_profile_snapshots(args.profiles_db)
        if args.moments_db:
            result["moments"] = indexer.index_moments(args.moments_db)
        analysis = AnalysisService(store, MarkdownMemory(args.memory_root, store))
        result["initial_queue"] = indexer.queue_initial_top(args.history_db, analysis)
        # Count-only output avoids exposing private names, IDs, or message text.
        print({"profiles": result.get("profiles", {}).get("profiles_seen", 0),
               "profile_snapshots": result.get("profile_snapshots", {}).get("snapshots_seen", 0),
               "moments": result.get("moments", {}).get("moments_seen", 0),
               "messages": result["history"]["messages_seen"],
               "conversations": result["history"]["conversations_seen"],
               "jobs": result["initial_queue"]["jobs_queued"]})


if __name__ == "__main__":
    main()
