"""Render full, verified formal Markdown versions as a local reading report."""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from wechat_auto.memory import MemoryStore
from wechat_auto.memory.report import FullReportBuilder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-db", type=Path, default=Path("data/wechat_memory.sqlite3"))
    parser.add_argument("--memory-root", type=Path, default=Path("data/memory"))
    parser.add_argument("--conversation-id")
    parser.add_argument("--person-id")
    parser.add_argument("--accepted-receipts", type=Path,
                        help="coordinator JSON: accepted_versions and optional source_months")
    parser.add_argument("--visuals", type=Path, help="reviewed display spec bound to formal Markdown versions")
    args = parser.parse_args()
    for field in ("memory_db", "memory_root", "accepted_receipts", "visuals"):
        value = getattr(args, field)
        if value is not None and not value.is_absolute():
            setattr(args, field, PROJECT_ROOT / value)
    if not args.memory_db.is_file():
        parser.error("formal Memory database does not exist")
    accepted, months = None, None
    if args.accepted_receipts:
        receipt = json.loads(args.accepted_receipts.read_text(encoding="utf-8"))
        accepted = {(r["scope_type"], r["scope_id"], r.get("period", "")): int(r["version"])
                    for r in receipt["accepted_versions"]}
        months = receipt.get("source_months")
    with MemoryStore(args.memory_db) as store:
        builder = FullReportBuilder(store, args.memory_root / "dashboard", memory_root=args.memory_root)
        path = builder.build(person_id=args.person_id, conversation_id=args.conversation_id,
                             accepted_versions=accepted, source_months=months,
                             visuals=json.loads(args.visuals.read_text(encoding="utf-8")) if args.visuals else None)
    print(json.dumps({"path": path, "status": "rendered_not_semantically_certified"}))


if __name__ == "__main__":
    main()
