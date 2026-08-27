#!/usr/bin/env python3
"""The collections in the catalog, as a matrix for the weekly data pass.

`.github/workflows/data-pass.yml` runs one job per collection. The list comes
from the catalog rather than from a hand-written array in the workflow, so a
collection that is added or removed changes the matrix on the same commit.

Each entry carries three fields:

- `collection`, the theme/collection path the data pass takes,
- `slug`, the same path with a dash, because an artifact name holds no slash,
- `parts`, the number of GeoParquet parts, which sets how long the job runs.

`parts` counts item links, and it counts 1 for a collection that carries the
`data` asset itself. `tools/build_catalog.py` writes no item for a collection
with one part, because an item that wraps the only part adds indirection. A
count of item links alone therefore reports 0 for a collection the data pass
does read.

The list is sorted with the largest collection first. The jobs then start in
the order that finishes soonest when the runner count is below the job count.

Run:
    python3 tools/list_collections.py
    python3 tools/list_collections.py --github-output matrix
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from catalog_config import load_config  # noqa: E402


def collections(root: Path) -> list[dict[str, object]]:
    """Every collection under the catalog root, largest first."""
    found: list[dict[str, object]] = []
    for path in sorted(root.glob("*/*/collection.json")):
        collection = path.parent
        theme = collection.parent
        node = json.loads(path.read_text())
        parts = sum(1 for link in node.get("links", []) if link.get("rel") == "item")
        if parts == 0 and "data" in node.get("assets", {}):
            parts = 1
        if parts == 0:
            raise SystemExit(
                f"error  {path} names no item link and carries no data asset, "
                "so the data pass would read nothing"
            )
        name = f"{theme.name}/{collection.name}"
        found.append(
            {
                "collection": name,
                "slug": name.replace("/", "-"),
                "parts": parts,
            }
        )
    if not found:
        raise SystemExit(f"error  {root} holds no collection, so the matrix is empty")
    found.sort(key=lambda entry: (-int(entry["parts"]), str(entry["collection"])))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--github-output",
        metavar="NAME",
        help="append NAME=<json> to the file named by GITHUB_OUTPUT",
    )
    args = parser.parse_args()

    root = ROOT / load_config()["publish_dir"]
    found = collections(root)
    payload = json.dumps(found, separators=(",", ":"))

    if args.github_output:
        destination = os.environ.get("GITHUB_OUTPUT")
        if not destination:
            raise SystemExit("error  GITHUB_OUTPUT is not set")
        with open(destination, "a") as handle:
            handle.write(f"{args.github_output}={payload}\n")

    print(payload)
    total = sum(int(entry["parts"]) for entry in found)
    print(f"{len(found)} collections, {total} parts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
