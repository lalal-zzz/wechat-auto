"""Create a resumable local plan; does not launch agents or certify reading."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from wechat_auto.memory.partition import AnalysisBudget, plan_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="directory of YYYY-MM.json arrays")
    parser.add_argument("output", type=Path, help="plan in the analysis run work directory")
    parser.add_argument("--max-records", type=int, default=3000)
    parser.add_argument("--max-text-chars", type=int, default=60000)
    parser.add_argument("--max-months", type=int, default=12)
    parser.add_argument("--context-records", type=int, default=12)
    args = parser.parse_args()
    args.input = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    args.output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    if args.output.exists():
        parser.error("output already exists; preserve the existing plan and reading receipts")
    paths = sorted(args.input.glob("????-??.json"))
    if not paths:
        parser.error("no monthly input arrays found")
    months = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in paths}
    plan = plan_analysis(months, AnalysisBudget(args.max_records, args.max_text_chars,
                                              args.max_months, args.context_records))
    plan["sources"] = {p.stem: {"path": str(p.resolve()),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": plan["status"], "months": plan["months"],
                      "records": plan["records"], "shards": len(plan["jobs"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
