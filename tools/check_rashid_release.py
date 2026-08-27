#!/usr/bin/env python3
"""Watch PyPI for the rashid release that replaces the git pin.

`requirements-ci.txt` pins rashid to the merge commit of
portolan-sdi/rashid#167. That fix is merged and it is not released. A comment
that says "switch to the release when it is cut" reminds nobody, so this tool
does the watching and `.github/workflows/rashid-release.yml` runs it weekly.

Dependabot cannot do this work. It does not read a `pip install` inside a
workflow `run:` step, and it cannot move a requirement from a git URL to a
PyPI version. It takes over once the pin is a version, which is why the pin
now lives in a requirements file.

The pin must hold one of two exact shapes:

    rashid @ git+https://github.com/portolan-sdi/rashid@<40 hex characters>
    rashid==<major>.<minor>.<patch>

A line that matches neither exits 2 and names the file. A silent match of
nothing would report "no release is due" every week for a pin that no longer
exists, which is the one failure this tool must not have.

Exit codes:

    0  the check ran. Read `available` for the answer.
    1  the network call or PyPI failed.
    2  the pin does not hold either shape, or the file is missing.

Run:
    python3 tools/check_rashid_release.py
    python3 tools/check_rashid_release.py --apply
    python3 tools/check_rashid_release.py --pypi-json /tmp/pypi.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements-ci.txt"
PYPI = "https://pypi.org/pypi/rashid/json"

# The release the pinned commit sits above. rashid#167 merged after 0.1.7, so
# the first release that carries it is the first release above 0.1.7.
FLOOR = (0, 1, 7)

GIT_PIN = re.compile(
    r"^rashid @ git\+https://github\.com/portolan-sdi/rashid@([0-9a-f]{40})$"
)
VERSION_PIN = re.compile(r"^rashid==(\d+)\.(\d+)\.(\d+)$")

# A release with a suffix, such as 0.2.0rc1, is not a release this pin takes.
RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def fail(message: str, code: int) -> None:
    """Report the problem and exit with the code the caller reads."""
    print(f"error  {message}")
    raise SystemExit(code)


def read_pin(path: Path) -> tuple[str, str, int]:
    """The rashid requirement in `path`, as (shape, text, line number).

    `shape` is "git" or "version". Anything else is a failure, and so is a file
    that names rashid twice or not at all.
    """
    if not path.is_file():
        fail(f"{path} is missing, so there is no pin to check", 2)

    matches = [
        (number, line.strip())
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if line.strip().lower().startswith("rashid")
    ]
    if len(matches) != 1:
        fail(
            f"{path} names rashid {len(matches)} times, and this tool reads "
            "exactly one pin",
            2,
        )

    number, text = matches[0]
    if GIT_PIN.match(text):
        return "git", text, number
    if VERSION_PIN.match(text):
        return "version", text, number
    fail(
        f"{path}:{number} holds a rashid pin this tool does not know: {text!r}. "
        "It reads 'rashid @ git+https://github.com/portolan-sdi/rashid@<sha>' "
        "or 'rashid==X.Y.Z'. Fix the line or fix this tool. Do not leave it "
        "matching nothing, because it then reports that no release is due "
        "every week.",
        2,
    )
    raise AssertionError("unreachable")


def pypi_releases(source: str | None) -> list[tuple[int, int, int]]:
    """Every final rashid release on PyPI that carries at least one file."""
    if source:
        payload = json.loads(Path(source).read_text())
    else:
        try:
            with urllib.request.urlopen(PYPI, timeout=60) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            fail(f"PyPI did not answer for rashid ({exc})", 1)

    found = []
    for name, files in payload.get("releases", {}).items():
        match = RELEASE.match(name)
        if match is None:
            continue
        # A release whose files are all yanked is not installable.
        if not files or all(f.get("yanked") for f in files):
            continue
        found.append(tuple(int(part) for part in match.groups()))
    if not found:
        fail("PyPI reports no final rashid release, which cannot be right", 1)
    return sorted(found)


def emit(name: str, value: str) -> None:
    """Append an output for the workflow step, when one is listening."""
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements",
        type=Path,
        default=REQUIREMENTS,
        help="the file that holds the pin",
    )
    parser.add_argument(
        "--pypi-json",
        help="read the PyPI answer from this file instead of the network",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="rewrite the git pin as a version pin when a release is available",
    )
    args = parser.parse_args()

    shape, text, number = read_pin(args.requirements)
    floor = ".".join(str(part) for part in FLOOR)

    if shape == "version":
        current = ".".join(text.split("==")[1].split("."))
        print(f"{args.requirements}:{number} pins rashid=={current}")
        print(
            "The move off the git pin is done. Dependabot keeps a version pin "
            "current, so delete this tool and "
            ".github/workflows/rashid-release.yml."
        )
        emit("available", "false")
        return 0

    releases = pypi_releases(args.pypi_json)
    newest = releases[-1]
    shown = ".".join(str(part) for part in newest)

    if newest <= FLOOR:
        print(f"The newest rashid release on PyPI is {shown}.")
        print(f"It is not above {floor}, so the git pin stays.")
        emit("available", "false")
        return 0

    print(f"rashid {shown} is on PyPI, above the pinned {floor}.")
    print(f"Replace {args.requirements}:{number} with 'rashid=={shown}'.")
    emit("available", "true")
    emit("version", shown)

    if args.apply:
        lines = args.requirements.read_text().splitlines()
        lines[number - 1] = f"rashid=={shown}"
        args.requirements.write_text("\n".join(lines) + "\n")
        print(f"Wrote 'rashid=={shown}' to {args.requirements}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
