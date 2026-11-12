"""Tests for RELEASE_NOTES.md, which the account menu's Release notes page renders.

Deliberately dependency-free: no pytest, no network. Run it directly.

    server/venv/bin/python tests/test_release_notes.py

The heading pattern matches HEADING in src/releaseNotes.ts; keep the two in step.
"""
import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
HEADING = re.compile(r"^##\s+v?(\d+\.\d+\.\d+)\s*(?:[—–-]+\s*(\d{4}-\d{2}-\d{2}))?\s*$", re.M)

passed = 0
failed = 0


def check(description: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {description}")
    else:
        failed += 1
        print(f"  FAIL {description}")


notes = re.sub(r"<!--.*?-->", "", (APP / "RELEASE_NOTES.md").read_text(), flags=re.S)
releases = HEADING.findall(notes)
version = json.loads((APP / "package.json").read_text())["version"]

check("there is at least one release", len(releases) > 0)
check(f"the top release matches package.json ({version})", bool(releases) and releases[0][0] == version)
check("every release has a date", all(date for _, date in releases))
dates = [date for _, date in releases]
check("releases are newest first", dates == sorted(dates, reverse=True))
versions = [tuple(int(n) for n in v.split(".")) for v, _ in releases]
check("versions increase toward the top", versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
