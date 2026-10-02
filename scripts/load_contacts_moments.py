"""Queue/resume bounded contact album loading, then refresh the local archive.

No messages, relationship mutations or remote media downloads are performed.
All raw contact rows may be queued as candidates; they are not certified friends.
"""
from __future__ import annotations

import argparse
import json
import logging

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.backends.collection_sync import LocalCollectionSource
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.memory.collection import MomentsCollection
from wechat_auto.memory.store import MemoryStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory-db', default='data/wechat_memory.sqlite3')
    parser.add_argument('--person-id', action='append', default=[])
    parser.add_argument('--enqueue-all', action='store_true', help='Queue raw contact candidates, not certified friends')
    parser.add_argument('--queue-only', action='store_true')
    parser.add_argument('--max-contacts', type=int, default=1)
    parser.add_argument('--max-pages', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.max_contacts <= 30 or not 1 <= args.max_pages <= 30:
        parser.error('Contacts/pages must be between 1 and 30')
    logging.disable(logging.CRITICAL)
    with MemoryStore(args.memory_db) as store:
        collector = MomentsCollection(store)
        people = args.person_id
        if args.enqueue_all:
            people += [row[0] for row in store._connection.execute(
                "SELECT person_id FROM people WHERE person_type='contact'")]
        if people:
            collector.enqueue(people)
        if args.queue_only:
            print(json.dumps({'queued': len(collector.queue()), 'ui_actions': 0}))
            return
        config = WeChatConfig(ocr_engine='paddle', ocr_verify_enabled=True, ocr_allow_rapid_fallback=False)
        app = Application(config).connect()
        skill = BasicSkill(app, config, SessionConfig())
        source = LocalCollectionSource(memory_path=args.memory_db)
        pending = [row for row in collector.queue() if row['status'] in {'pending', 'failed', 'partial'}]
        if args.person_id:
            pending = [row for row in pending if row['person_id'] in args.person_id]
        complete, failed = 0, 0
        for row in pending[:args.max_contacts]:
            try:
                result = collector.run_one(row['person_id'], skill, sync_after_load=source, max_pages=args.max_pages)
                complete += 1
                if result['requires_navigation_restore']:
                    break
            except Exception as exc:
                failed += 1
                print(json.dumps({'error_type': type(exc).__name__, 'automatic_retry': False}))
                # A navigation failure can leave a popup or unknown page; stop
                # the batch instead of trying the next person's stale UI.
                break
        print(json.dumps({'loaded': complete, 'failed': failed, 'network_media_downloads': 0,
                          'server_history_complete': False, 'queue_entries': len(collector.queue())}))


if __name__ == '__main__':
    main()
