#!/usr/bin/env python3
"""Diff a new Overture fingerprint against the committed baseline.

`sources/fingerprint.json` is the one file in `sources/` that git tracks. The
sync workflow regenerates it, and this script decides whether a human must read
the release before the catalog follows it.

Two classes of change, and the split is deliberate.

**Fail** on a collection that appears or disappears, a column that appears or
disappears, a licence change, a GeoParquet version change, or a row group above
the PORTO-DAT-008 cap. Each one invalidates something the catalog states. The
authored column descriptions in `sources/columns.json` go stale when a column
moves, and a licence change makes the collection say the wrong thing about
reuse. Across the two Overture releases available in August 2026, no column set
moved in any of the 15 collections. The gate fires rarely, so a failure is
worth reading.

**Report** item-count deltas, and never fail on them. Between those same two
releases `base/land` went from 32 parts to 47, and `buildings/building_part`
went from 3 to 1. A threshold would have fired twice in one ordinary month, and
a monthly false alarm stops being read. The deltas go in the pull request body,
where a reviewer sees them next to the diff.

Usage:
    python3 tools/check_fingerprint.py \
        --baseline sources/fingerprint.baseline.json \
        --current sources/fingerprint.json \
        --report /tmp/fingerprint.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# PORTO-DAT-008 caps a row group at this many rows. tools/harvest_overture.py
# records the cap it measured against, so a fingerprint written under a
# different cap reports its own.
DEFAULT_ROW_GROUP_CAP = 150_000


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def collections(doc: dict[str, Any]) -> dict[str, Any]:
    return doc.get("collections") or {}


def compare(
    baseline: dict[str, Any], current: dict[str, Any]
) -> tuple[
    list[str],
    list[tuple[str, int, int]],
]:
    """Blocking problems, and the item-count deltas that only get reported."""
    errors: list[str] = []
    deltas: list[tuple[str, int, int]] = []

    old = collections(baseline)
    new = collections(current)

    for key in sorted(set(old) - set(new)):
        errors.append(f"collection {key} disappeared from the release")
    for key in sorted(set(new) - set(old)):
        errors.append(f"collection {key} appeared in the release")

    for key in sorted(set(old) & set(new)):
        was, now = old[key], new[key]

        old_columns = set(was.get("columns") or [])
        new_columns = set(now.get("columns") or [])
        for column in sorted(old_columns - new_columns):
            errors.append(f"{key}: column {column!r} disappeared")
        for column in sorted(new_columns - old_columns):
            errors.append(f"{key}: column {column!r} appeared")

        if was.get("license") != now.get("license"):
            errors.append(
                f"{key}: licence changed from {was.get('license')!r} "
                f"to {now.get('license')!r}"
            )

        old_geo = sorted(was.get("geoparquet") or [])
        new_geo = sorted(now.get("geoparquet") or [])
        if old_geo != new_geo:
            errors.append(
                f"{key}: GeoParquet version changed from {old_geo} to {new_geo}"
            )

        old_items = int(was.get("items") or 0)
        new_items = int(now.get("items") or 0)
        if old_items != new_items:
            deltas.append((key, old_items, new_items))

    # The cap applies to the release the catalog is about to describe, so it
    # reads every collection in the new fingerprint, new ones included.
    for key in sorted(new):
        record = new[key]
        cap = int(record.get("row_group_cap") or DEFAULT_ROW_GROUP_CAP)
        rows = int(record.get("max_row_group_rows") or 0)
        if rows > cap:
            errors.append(
                f"{key}: largest row group holds {rows:,} rows, above the "
                f"PORTO-DAT-008 cap of {cap:,}"
            )

    return errors, deltas


def report(
    baseline: dict[str, Any],
    current: dict[str, Any],
    deltas: list[tuple[str, int, int]],
) -> str:
    """The markdown a reviewer reads in the pull request body."""
    lines = [
        f"Release `{baseline.get('release')}` becomes `{current.get('release')}`.",
        "",
        "Every collection keeps its columns, its licence, and its GeoParquet "
        "version. The sync fails on a change to any of the three.",
        "",
    ]
    if deltas:
        lines += [
            "Part counts that moved:",
            "",
            "| Collection | Before | After | Delta |",
            "|---|---:|---:|---:|",
        ]
        for key, was, now in deltas:
            lines.append(f"| `{key}` | {was} | {now} | {now - was:+d} |")
        lines += [
            "",
            "A part count moves when Overture repartitions a collection. The "
            "sync reports the count. It does not fail on the count.",
        ]
    else:
        lines.append("No part count moved.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument(
        "--report",
        type=Path,
        help="write the markdown item-count report here",
    )
    args = parser.parse_args()

    baseline = load(args.baseline)
    current = load(args.current)

    errors, deltas = compare(baseline, current)

    for key, was, now in deltas:
        print(f"note   {key}: {was} part(s) -> {now} part(s)")

    if args.report:
        args.report.write_text(report(baseline, current, deltas))

    if errors:
        print("\n".join(f"error  {e}" for e in errors))
        print(
            "       a human reviews what moved before the catalog follows it. "
            "Re-run the sync after you update the authored inputs."
        )
        raise SystemExit(1)

    count = len(collections(current))
    print(
        f"OK: {count} collection(s) keep their columns, licence, and GeoParquet version"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
