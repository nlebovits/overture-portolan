#!/usr/bin/env python3
"""Every remote data and visual href still answers.

This catalog copies no bytes. Each `data` asset points at a parquet part in
Overture's public bucket, and each `visual` asset points at Overture's
prebuilt PMTiles. Part filenames carry a UUID, so every href changes on every
monthly release. A catalog that cites a pruned release looks correct on disk
and serves nothing.

tests/test_links.py cannot catch that. It resolves relative hrefs against the
working tree and skips anything with a scheme, so the remote hrefs go
unchecked. This gate takes the other half: it sends a HEAD to every distinct
remote `data` and `visual` href and fails on any status outside 2xx.

The href set is de-duplicated first. One `visual` href serves every collection
in a theme, so a 15-collection catalog cites about 5 distinct PMTiles files.
The HEADs then run in parallel, because 987 sequential round trips to
us-west-2 take longer than the rest of the gates together.

Usage:
    python3 tests/test_upstream_alive.py
    python3 tests/test_upstream_alive.py --workers 32
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from catalog_config import load_config  # noqa: E402

config = load_config()
BASE = ROOT / config["publish_dir"]

# The two asset keys that point off this host. A role filter also matches
# `thumbnail` and `default-style`, which are local files that
# tests/test_links.py already resolves.
REMOTE_KEYS = ("data", "visual")

TIMEOUT = 30
USER_AGENT = "overture-portolan-upstream-gate"


def remote_hrefs() -> dict[str, list[str]]:
    """Distinct http(s) data and visual hrefs, each with the paths that cite it."""
    found: dict[str, list[str]] = {}
    for path in sorted(BASE.rglob("*.json")):
        rel = path.relative_to(BASE)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.name.endswith(".style.json") or "styles" in path.parts:
            continue
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            # tests/test_links.py owns the malformed-JSON message. Two gates
            # that report one fault make it read as two.
            continue
        if not isinstance(doc, dict):
            continue
        for key in REMOTE_KEYS:
            href = ((doc.get("assets") or {}).get(key) or {}).get("href", "")
            if href.startswith(("http://", "https://")):
                found.setdefault(href, []).append(str(rel))
    return found


def probe(href: str) -> str | None:
    """None when the href answers 2xx, else the reason it did not."""
    request = urllib.request.Request(
        href, method="HEAD", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except OSError as exc:
        return f"request failed ({exc})"
    if not 200 <= status < 300:
        return f"HTTP {status}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="parallel HEAD requests (default: 16)",
    )
    args = parser.parse_args()

    hrefs = remote_hrefs()
    if not hrefs:
        print("OK: no remote data or visual href to check")
        return 0

    targets = sorted(hrefs)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        reasons = list(pool.map(probe, targets))

    errors: list[str] = []
    for href, reason in zip(targets, reasons, strict=True):
        if reason is None:
            continue
        # Name one object that cites the href. The others carry the same href
        # and the same fix, so a list of 987 paths hides the fault.
        where = sorted(hrefs[href])[0]
        errors.append(f"{where}: {href} -> {reason}")

    if errors:
        print("\n".join(f"error  {e}" for e in errors))
        raise SystemExit(1)

    print(f"OK: {len(targets)} distinct upstream href(s) answered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
