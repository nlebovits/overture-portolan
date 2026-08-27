#!/usr/bin/env python3
"""The published host answers exactly the two deviations we accept.

tests/test_conformance.py runs rashid without --live, so it never exercises
PTL-LIV-004 and PTL-LIV-005, the two ids in its ACCEPTED set. Those two rules
probe a server, and a pull request has no server to probe. They stayed
unchecked until someone ran the live pass by hand.

This gate runs the live pass against the deployed site, so it belongs after a
deploy rather than on a pull request. It asserts the exact shape of the
accepted deviation:

- exactly two error-severity findings,
- their rule ids are PTL-LIV-004 and PTL-LIV-005,
- both name the publish host.

Anything else fails. A third finding means the host changed. A finding against
an `overturemaps` host means the PORTO-CORE-073 carve-out did not apply, which
happens when --url is missing: rashid then has no publish host to compare
against, probes every absolute href, and reports the Overture buckets. The
--url is not optional and this gate proves it took effect.

Usage:
    python3 tests/test_live_hosting.py https://nlebovits.github.io/overture-portolan/
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from catalog_config import load_config  # noqa: E402

# Both rows are in docs/conformance.md, tracked by portolan-spec#183. This set
# and ACCEPTED in tests/test_conformance.py hold the same two ids on purpose.
EXPECTED: set[str] = {"PTL-LIV-004", "PTL-LIV-005"}

# rashid rather than portolan-cli. The `--no-data` and `--live` flags this
# gate needs reached portolan-cli in 1.0.0a0, which is a pre-release, and a
# plain `pip install portolan-cli` in CI takes 0.7.0 and fails with
# "No such option '--no-data'". rashid carries the same passes, it is already
# pinned in requirements-ci.txt, and one validator then runs every gate.
INSTALL = "python -m pip install -r requirements-ci.txt"


def fail(message: str) -> None:
    """Report the problem, name the fix, and exit non-zero."""
    print(f"error  {message}")
    print(f"       install the CLI with: {INSTALL}")
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url",
        help="base URL the catalog is published under",
    )
    args = parser.parse_args()

    host = urlparse(args.url).netloc
    if not host:
        raise SystemExit(f"error  {args.url!r} names no host")

    if shutil.which("rashid") is None:
        fail("rashid is not installed, so this gate checks nothing")

    config = load_config()
    target = ROOT / config["publish_dir"]

    result = subprocess.run(
        [
            "rashid",
            "check",
            str(target),
            "--no-data",
            "--live",
            "--live-base-url",
            args.url,
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit("rashid produced no JSON report") from None

    # rashid puts findings at the top level. portolan-cli nests them under
    # "data". Read either, so this gate survives a swap between the two.
    findings = report.get("findings")
    if findings is None:
        findings = (report.get("data") or {}).get("findings", [])
    errors = [f for f in findings if f.get("severity") == "error"]

    for finding in errors:
        print(
            f"found  {finding.get('rule_id')}  "
            f"{finding.get('path', '?')}: {finding.get('message')}"
        )

    problems: list[str] = []

    ids = {f.get("rule_id") for f in errors}
    if ids != EXPECTED:
        missing = sorted(EXPECTED - ids)
        extra = sorted(ids - EXPECTED)
        if missing:
            print(
                f"note   {', '.join(missing)} no longer fires. If the host now "
                "sends the CORS headers, drop the id from ACCEPTED in "
                "tests/test_conformance.py, from EXPECTED here, and from the "
                "table in docs/conformance.md."
            )
        if extra:
            problems.append(f"unexpected error-severity rule(s): {', '.join(extra)}")
        else:
            problems.append(f"expected exactly {sorted(EXPECTED)}, found {sorted(ids)}")

    # Every finding must name the publish host. One against an Overture bucket
    # means the carve-out did not apply and the --url did not reach rashid.
    for finding in errors:
        message = finding.get("message", "")
        if f"host '{host}'" not in message:
            problems.append(
                f"{finding.get('rule_id')} does not name host {host!r}: {message}"
            )

    if problems:
        print("\n".join(f"error  {p}" for p in problems))
        raise SystemExit(1)

    print(
        f"OK: {host} reports exactly the {len(EXPECTED)} accepted deviation(s); "
        "see docs/conformance.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
