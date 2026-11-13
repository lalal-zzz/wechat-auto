"""Display frozen analysis input without shortening readable message bodies.

This is a reading aid, not a semantic coverage certificate. XML parsing errors
are explicit gaps. It never fetches linked media or prints XML attributes.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from wechat_auto.memory.reading import display_time, readable_message

MEDIA_TYPES = {'图片', '动画表情', '语音', '视频', '3', '34', '43', '47'}
MEDIA_MARKERS = {'[图片未解读]', '[动画表情未解读]', '[语音未转写]',
                 '[语音未解读]', '[视频未解读]', '[XML/媒体正文未解读]'}


def fold_media_records(records):
    """Fold only typed, text-free, error-free media; retain every natural text."""
    pending = []

    def flush():
        if len(pending) < 2:
            return list(pending)
        return [{"unread_media_range": [pending[0]['ordinal'], pending[-1]['ordinal']],
                     "count": len(pending),
                     "time_Beijing": [pending[0]['time_Beijing'], pending[-1]['time_Beijing']],
                     "directions": dict(Counter(r['analysis_direction'] for r in pending)),
                     "kinds": dict(Counter(r['_media_type'] for r in pending))}]

    for record in records:
        if (record.get('_media_type') in MEDIA_TYPES and not record['parse_gaps'] and
                record['text'] and all(part in MEDIA_MARKERS for part in record['text'])):
            pending.append(record)
        else:
            yield from flush()
            pending.clear()
            yield record
    yield from flush()


def lean_record(record, period):
    """Reduce repeated display metadata, preserving every text and parse gap."""
    stamp = record['time_Beijing']
    if stamp.startswith(period + '-') and stamp.endswith('+08:00'):
        stamp = stamp[len(period) + 1:-6].replace('T', ' ')
    # Exact duplicate strings add no information; quoted/context text stays.
    parts = list(dict.fromkeys(record['text']))
    value = [record['ordinal'], {'incoming': 'C', 'outgoing': 'S'}.get(
        record['analysis_direction'], '?'), stamp, parts[0] if len(parts) == 1 else parts]
    if record['parse_gaps']:
        value.append(record['parse_gaps'])
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--count', type=int, default=300)
    parser.add_argument('--compact', action='store_true', help='compact row arrays with explicit Beijing dates')
    parser.add_argument('--lean', action='store_true', help='compact rows with month header, speaker codes and lossless text')
    parser.add_argument('--recover-xml', action='store_true',
                        help='optional local lxml recovery; retains explicit parse-gap provenance')
    parser.add_argument('--fold-media', action='store_true',
                        help='merge consecutive pure-media placeholders; preserves all text and parse gaps')
    args = parser.parse_args()
    if args.start < 1 or args.count < 1:
        parser.error('start and count must be positive')
    if args.fold_media and not args.compact:
        parser.error('fold-media requires compact output')
    if args.lean and not args.compact:
        parser.error('lean requires compact output')
    period = args.source.stem
    if args.lean and not re.fullmatch(r'\d{4}-\d{2}', period):
        parser.error('lean requires a YYYY-MM source filename')
    sys.stdout.reconfigure(encoding='utf-8')
    rows = json.loads(args.source.read_text(encoding='utf-8'))
    selected = rows[args.start - 1:args.start - 1 + args.count]
    if args.lean:
        print(json.dumps({"period": period, "timezone": '+08:00', "columns": ['ordinal', 'speaker', 'day HH:mm:ss (full date when outside period)', 'texts', 'parse_gaps only when nonempty'], "speakers": {'S': 'self/outgoing', 'C': 'contact/incoming', '?': 'unknown'}}))
    elif args.compact:
        print(json.dumps(['ordinal', 'analysis_direction', 'time_Beijing', 'texts', 'parse_gaps']))
    records = []
    for ordinal, row in enumerate(selected, args.start):
        # Legacy cached direction can be wrong; never use it as a fallback.
        direction = row.get('analysis_direction', 'unknown')
        if direction not in {'incoming', 'outgoing'}:
            direction = 'unknown'
        parts, errors = readable_message(row, recover_xml=args.recover_xml)
        raw = row.get('raw')
        records.append({"ordinal": ordinal, "time": row.get('time'), "time_Beijing": display_time(row.get('time')),
                            "analysis_direction": direction, "text": parts, "parse_gaps": errors,
                            "_media_type": str(raw.get('type', '')) if isinstance(raw, dict) else ''})
    entries = list(fold_media_records(records)) if args.fold_media else records
    for record in entries:
        if 'unread_media_range' in record:
            value = record
        elif args.lean:
            value = lean_record(record, period)
        elif args.compact:
            value = [record['ordinal'], record['analysis_direction'], record['time_Beijing'],
                     record['text'], record['parse_gaps']]
        else:
            value = {key: val for key, val in record.items() if not key.startswith('_')}
        print(json.dumps(value, ensure_ascii=False))
    print(json.dumps({"displayed": len(selected), "first_ordinal": args.start,
                          "last_ordinal": args.start + len(selected) - 1,
                          "total_rows": len(rows), "output_entries": len(entries),
                          "media_rows_folded": sum(r['count'] for r in entries if 'unread_media_range' in r),
                          "semantic_reading_certified": False}))


if __name__ == '__main__':
    main()
