"""Audit tracked files, optionally all reachable Git history, without printing values."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATHS = {
    "docs/PROJECT_STATE.md", "docs/HISTORY_SOURCE_AUDIT.md",
    "docs/PROJECT_PROBLEM_TREE.md", "docs/PROJECT_SOLUTION_TREE.md",
    "docs/LIVE_TEST_TODO.md",
}
RULES = {
    "personal_home_path": re.compile(
        rb"(?i)(?:[a-z]:[\\/]+Users[\\/]+(?!<|Public\b|Default\b)[\w.-]+"
        rb"|/(?:home|Users)/(?!<)[\w.-]+)"
    ),
    "machine_python_path": re.compile(rb"(?i)[a-z]:[\\/]+Anconda[\\/]+"),
    "non_fixture_wechat_id": re.compile(rb"wxid_(?!test_)[A-Za-z0-9_]{6,}"),
    "phone_number": re.compile(rb"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "private_key_or_token": re.compile(
        rb"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        rb"|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})"
    ),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-history", action="store_true")
    args = parser.parse_args()
    findings: set[tuple[str, str]] = set()
    checked: set[tuple[bytes, str]] = set()
    revisions = git("rev-list", "--all").decode().splitlines() if args.all_history else ["HEAD"]
    for revision in revisions:
        records = git("ls-tree", "-rz", revision).split(b"\0") if args.all_history else git("ls-files", "-sz").split(b"\0")
        for record in records:
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            path = raw_path.decode("utf-8", errors="replace")
            oid = metadata.split()[2 if args.all_history else 1]
            if (oid, path) in checked:
                continue
            checked.add((oid, path))
            if path in PRIVATE_PATHS or path.startswith(("data/", "exports/", "captures/", "screenshots/", "scratch/")):
                findings.add((path, "private_artifact"))
                continue
            content = git("cat-file", "blob", oid.decode()) if args.all_history else (ROOT / path).read_bytes()
            for rule, pattern in RULES.items():
                if pattern.search(content):
                    findings.add((path, rule))
    # Paths and rule names only: never expose matched values or private content.
    for path, rule in sorted(findings):
        print(f"{path}: {rule}")
    print(f"Checked {len(checked)} file versions; {len(findings)} findings.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
