#!/usr/bin/env python3
"""The data pass over one collection, via rashid.

`tests/test_conformance.py` runs rashid with `--no-data`, so the byte checks
never run on a pull request. Those checks read every asset over HTTP range,
which is too slow for a gate that must answer in a minute. This gate runs them.

The byte rules it reaches are PTL-DAT-006 spatial ordering, PTL-DAT-007
per-row-group statistics, PTL-DAT-008 the 150,000 row cap on a row group, and
PTL-DAT-012 the GeoParquet version.

rashid reads a catalog root and it has no flag that scopes the pass to one
collection. This gate makes a pruned copy of the catalog in a temporary
directory instead. The copy keeps the root catalog, the theme catalog, and the
one collection. It drops every other child link and every directory those links
name. The copy holds metadata only, so it costs about 5 MB and no network.

The pruned copy is why this gate takes a collection and not a filter: one
collection is one job, and 15 jobs run in about the time the largest one takes.

There is no accepted-finding list here, unlike `tests/test_conformance.py`. The
two ids that gate accepts, PTL-LIV-004 and PTL-LIV-005, only fire under
`--live`, which this gate does not pass. Any error-severity finding fails.

Usage:
    python3 tests/test_data_pass.py divisions/division_area
    python3 tests/test_data_pass.py buildings/building --report /tmp/found.md
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from catalog_config import load_config  # noqa: E402

# The same range as tests/test_conformance.py, for the same reason: a rashid
# below the floor reports a pass for rules it does not carry, and an
# unreviewed 0.2 rule set changes what this gate means.
MIN_VERSION = (0, 1, 5)
MAX_VERSION = (0, 2, 0)
SPEC = "rashid>=0.1.5,<0.2.0"
INSTALL = f"python -m pip install '{SPEC}'"


def fail(message: str) -> None:
    """Report the problem, name the fix, and exit non-zero."""
    print(f"error  {message}")
    print(f"       install a usable rashid with: {INSTALL}")
    raise SystemExit(1)


def rashid_version() -> tuple[int, ...]:
    """The version that rashid reports, as a tuple of integers."""
    try:
        proc = subprocess.run(["rashid", "--version"], capture_output=True, text=True)
    except OSError as exc:
        fail(f"rashid --version did not run ({exc})")
    if proc.returncode != 0:
        fail(f"rashid --version exited {proc.returncode}")
    text = (proc.stdout + proc.stderr).strip()
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        fail(f"rashid --version printed no readable version: {text!r}")
    return tuple(int(part) for part in match.groups())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def child_hrefs(node: dict) -> list[str]:
    return [
        link["href"] for link in node.get("links", []) if link.get("rel") == "child"
    ]


def keep_one_child(path: Path, keep: str) -> None:
    """Drop every child link from the STAC node at `path` except `keep`.

    Fails when `keep` is not one of the child links, because a rename upstream
    must not quietly produce a catalog with no children and a passing run.
    """
    node = read_json(path)
    hrefs = child_hrefs(node)
    if keep not in hrefs:
        raise SystemExit(
            f"error  {path} has no child link {keep!r}; it has {sorted(hrefs)}"
        )
    node["links"] = [
        link
        for link in node.get("links", [])
        if link.get("rel") != "child" or link.get("href") == keep
    ]
    path.write_text(json.dumps(node, indent=2) + "\n")


def prune(source: Path, target: Path, theme: str, collection: str) -> None:
    """Copy the catalog to `target`, holding only one theme and one collection.

    Every directory removed here is named by a child link that is removed with
    it, so the copy stays a complete catalog rather than one with dead links.
    """
    shutil.copytree(source, target)

    root = target / "catalog.json"
    for href in child_hrefs(read_json(root)):
        name = href.split("/")[1]
        if name != theme:
            shutil.rmtree(target / name)
    keep_one_child(root, f"./{theme}/catalog.json")

    theme_catalog = target / theme / "catalog.json"
    for href in child_hrefs(read_json(theme_catalog)):
        name = href.split("/")[1]
        if name != collection:
            shutil.rmtree(target / theme / name)
    keep_one_child(theme_catalog, f"./{collection}/collection.json")


def write_report(path: Path, name: str, errors: list[dict], seconds: float) -> None:
    """Write the findings as Markdown, for a workflow that files an issue."""
    lines = [f"### `{name}`", "", f"The data pass took {seconds:.0f} seconds.", ""]
    if errors:
        lines += ["| Rule | Path | Message |", "|---|---|---|"]
        for finding in errors:
            message = str(finding.get("message", "")).replace("|", "\\|")
            lines.append(
                f"| `{finding.get('rule_id')}` | `{finding.get('path', '?')}` "
                f"| {message} |"
            )
    else:
        lines.append("No error-severity finding.")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "collection",
        help="collection path under the catalog root, such as divisions/division_area",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="write the findings to this file as Markdown",
    )
    args = parser.parse_args()

    parts = args.collection.strip("/").split("/")
    if len(parts) != 2:
        raise SystemExit(
            f"error  {args.collection!r} is not a theme/collection path, "
            "such as divisions/division_area"
        )
    theme, collection = parts

    if shutil.which("rashid") is None:
        fail("rashid is not installed, so this gate checks nothing")
    version = rashid_version()
    shown = ".".join(str(part) for part in version)
    if not MIN_VERSION <= version < MAX_VERSION:
        fail(f"rashid {shown} is outside the required range {SPEC}")

    source = ROOT / load_config()["publish_dir"]
    if not (source / theme / collection / "collection.json").is_file():
        raise SystemExit(f"error  {source / theme / collection} holds no collection")

    with tempfile.TemporaryDirectory() as work:
        target = Path(work) / "catalog"
        prune(source, target, theme, collection)

        started = time.monotonic()
        result = subprocess.run(
            ["rashid", "check", str(target), "--data", "--all", "--json"],
            capture_output=True,
            text=True,
        )
        seconds = time.monotonic() - started

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        # The report file is what a workflow puts in an issue. Write it here
        # too, so a crash reaches the reader rather than an empty artifact.
        if args.report:
            args.report.write_text(
                f"### `{args.collection}`\n\nrashid produced no JSON report. "
                f"It exited {result.returncode} after {seconds:.0f} seconds.\n"
            )
        raise SystemExit("rashid produced no JSON report") from None

    findings = report.get("findings", [])
    errors = [f for f in findings if f.get("severity") == "error"]

    for finding in errors:
        print(
            f"error  {finding.get('rule_id')}  "
            f"{finding.get('path', '?')}: {finding.get('message')}"
        )
        if finding.get("fix_hint"):
            print(f"       hint: {finding['fix_hint']}")

    if args.report:
        write_report(args.report, args.collection, errors, seconds)

    print(
        f"{args.collection}: rashid {shown} read "
        f"{report.get('files_checked', '?')} files in {seconds:.0f}s"
    )
    if errors:
        print(f"FAILED: {len(errors)} error-severity finding(s)")
        return 1
    print(f"OK: the data pass found no error in {args.collection}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
