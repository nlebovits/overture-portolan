#!/usr/bin/env python3
"""Run every SQL block in the published collection agent guides.

The queries read Overture's published data. A failure can expose a stale URL,
a changed column, or a query that no longer works in DuckDB.

Run every guide:

    python3 tests/test_agent_queries.py

Run one guide:

    python3 tests/test_agent_queries.py catalog/base/water/AGENTS.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
SETUP = "INSTALL spatial; LOAD spatial;\nINSTALL httpfs; LOAD httpfs;\n"
TIMEOUT = 900


def sql_blocks(path: Path) -> list[tuple[int, str]]:
    """Return each SQL fence with its opening line number."""
    text = path.read_text()
    pattern = r"^```sql\s*$\n(.*?)^```\s*$"
    blocks = []
    for match in re.finditer(pattern, text, re.MULTILINE | re.DOTALL):
        line = text.count("\n", 0, match.start()) + 1
        blocks.append((line, match.group(1).strip()))
    return blocks


def guides() -> list[Path]:
    """Return the root guide and one guide for every collection."""
    found = [CATALOG / "AGENTS.md"]
    for collection in sorted(CATALOG.glob("*/*/collection.json")):
        found.append(collection.with_name("AGENTS.md"))

    missing = [path for path in found if not path.is_file()]
    if missing:
        rendered = ", ".join(str(path.relative_to(ROOT)) for path in missing)
        raise SystemExit(f"FAIL: missing agent guide: {rendered}")

    empty = [path for path in found if not sql_blocks(path)]
    if empty:
        rendered = ", ".join(str(path.relative_to(ROOT)) for path in empty)
        raise SystemExit(f"FAIL: agent guide has no SQL blocks: {rendered}")
    return found


def write_matrix(name: str) -> int:
    """Write the guide matrix for GitHub Actions."""
    destination = os.environ.get("GITHUB_OUTPUT")
    if not destination:
        raise SystemExit("FAIL: GITHUB_OUTPUT is not set")
    matrix = [str(path.relative_to(ROOT)) for path in guides()]
    with open(destination, "a") as handle:
        handle.write(f"{name}={json.dumps(matrix, separators=(',', ':'))}\n")
    print(f"PASS: found {len(matrix)} query guides")
    return 0


def run(paths: list[Path]) -> int:
    """Run every SQL block in the selected guides."""
    if shutil.which("duckdb") is None:
        print("FAIL: duckdb is not installed")
        return 1

    failures = []
    ran = 0
    for path in paths:
        relative = path.relative_to(ROOT)
        blocks = sql_blocks(path)
        if not blocks:
            failures.append((str(relative), "no SQL blocks found"))
            continue
        for line, sql in blocks:
            label = f"{relative}:{line}"
            try:
                process = subprocess.run(
                    ["duckdb", "-noheader", "-list", "-c", SETUP + sql],
                    capture_output=True,
                    cwd=ROOT,
                    text=True,
                    timeout=TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                failures.append((label, f"timed out after {TIMEOUT} seconds"))
                continue
            ran += 1
            if process.returncode:
                error = process.stderr.strip().splitlines()
                failures.append((label, (error or ["DuckDB failed"])[0][:300]))
            else:
                print(f"PASS: {label}")

    for label, reason in failures:
        print(f"FAIL: {label}: {reason}")
    if failures:
        print(f"FAIL: {len(failures)} of {ran} documented queries failed")
        return 1
    print(f"PASS: {ran} documented queries ran")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="*", type=Path)
    parser.add_argument("--github-output", metavar="NAME")
    args = parser.parse_args()

    if args.github_output:
        if args.path:
            parser.error("--github-output does not take guide paths")
        return write_matrix(args.github_output)

    paths = [path.resolve() for path in args.path] if args.path else guides()
    outside = [path for path in paths if not path.is_relative_to(ROOT)]
    if outside:
        parser.error("guide paths must be inside the repository")
    missing = [path for path in paths if not path.is_file()]
    if missing:
        parser.error(f"guide does not exist: {missing[0]}")
    return run(paths)


if __name__ == "__main__":
    sys.exit(main())
