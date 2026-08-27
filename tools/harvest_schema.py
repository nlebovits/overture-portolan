#!/usr/bin/env python3
"""Harvest column descriptions from Overture's published JSON Schema.

Overture ships a `description` per property and an `enum` per coded column, at a
tagged release. That makes every column meaning in this catalog a cited fact
rather than an authored guess, which is what `portolan-bootstrap` calls the
researched-and-cited tier.

Two mechanisms are needed, because the schema hides meaning in two places.

The first is `$ref` resolution. Feature properties arrive through
`propertyContainers` in a shared `defs.yaml`, so a property is often a bare
`$ref` with its description one or two hops away. Measured against tag v1.18.0,
resolution alone covers 180 of the 217 columns.

The second is comment recovery. 57 enum values across 5 files document their
meaning only in a YAML comment:

    - megacity      #A extensive, large human settlement.
                    #Example: Tokyo, Japan.

`yaml.safe_load` discards those. A line parser recovers them, and they decode the
coded columns at the value level. `divisions/division.yaml` holds 5 and
`transportation/segment.yaml` holds 36.

Columns that neither mechanism covers are reported, never guessed. The caller
writes them into `known_issues`.

Usage:
    python3 tools/harvest_schema.py > sources/columns.json
"""

from __future__ import annotations

import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_TAG = "v1.18.0"
SCHEMA_DIR = ROOT / "sources" / f"overture-schema-{SCHEMA_TAG}"
SCHEMA_URL = f"https://github.com/OvertureMaps/schema/tree/{SCHEMA_TAG}/schema"
SCHEMA_TARBALL = (
    "https://github.com/OvertureMaps/schema/archive/refs/tags/"
    f"{SCHEMA_TAG}.tar.gz"
)

# Every theme/type Overture publishes, and the order collections appear in.
PAIRS: list[tuple[str, str]] = [
    ("addresses", "address"),
    ("base", "bathymetry"),
    ("base", "infrastructure"),
    ("base", "land"),
    ("base", "land_cover"),
    ("base", "land_use"),
    ("base", "water"),
    ("buildings", "building"),
    ("buildings", "building_part"),
    ("divisions", "division"),
    ("divisions", "division_area"),
    ("divisions", "division_boundary"),
    ("places", "place"),
    ("transportation", "connector"),
    ("transportation", "segment"),
]

# Columns the Overture schema does not describe, because they are not Overture
# properties. Each description cites where the meaning comes from. Keep this
# list short: an entry here is authored text, and everything else is harvested.
AUTHORED: dict[str, str] = {
    "bbox": (
        "The bounding box of the geometry, as a struct of xmin, ymin, xmax, and "
        "ymax. This is the GeoParquet 1.1 covering column. Readers use it to "
        "skip row groups that fall outside a query window, without decoding any "
        "geometry. See the GeoParquet 1.1 specification."
    ),
    "geometry": (
        "The feature geometry, stored as well-known binary in EPSG:4326."
    ),
    "names": (
        "Properties defining the names of a feature. The struct carries a "
        "primary name, optional common names by language, and optional rules. "
        "Quoted from the namesContainer definition in the Overture schema."
    ),
    "cartography": (
        "Cartographic hints Overture supplies for rendering, such as the zoom "
        "range over which a feature should be drawn."
    ),
    "id": (
        "The stable Overture feature identifier, unique within the release."
    ),
}

# Columns the schema leaves undescribed where the meaning differs per
# collection, so a single entry in AUTHORED cannot serve. Each of these carries
# documented enum values, which the comment parser recovers, so only the
# column-level sentence is authored here. Keyed by "theme/type:column".
AUTHORED_PER_COLLECTION: dict[str, str] = {
    "divisions/division:class": (
        "The settlement class of the division, where one applies. The value "
        "ranks a populated place by size, from megacity down to hamlet. It is "
        "empty for divisions that are not settlements."
    ),
    "divisions/division_area:class": (
        "Whether the area stops at the coastline or extends beyond it. Use it "
        "to exclude maritime extents when a land polygon is wanted."
    ),
    "divisions/division_boundary:class": (
        "Whether the boundary runs on land or beyond the coastline. A maritime "
        "boundary is not a land border between two divisions."
    ),
}

def fetch_schema() -> None:
    """Download the pinned schema tag into sources/.

    `sources/` is regenerable scratch and stays out of git, so the tag is
    fetched rather than vendored. `SCHEMA_TAG` is the only place the version is
    named, and every column description cites it.
    """
    print(f"fetching schema {SCHEMA_TAG}", file=sys.stderr)
    with urllib.request.urlopen(SCHEMA_TARBALL, timeout=120) as response:
        payload = response.read()
    prefix = f"schema-{SCHEMA_TAG.lstrip('v')}/schema/"
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            target = SCHEMA_DIR / member.name[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is not None:
                target.write_bytes(source.read())


_CACHE: dict[Path, Any] = {}


def load(path: Path) -> Any:
    """Parse a schema file once and reuse it."""
    path = path.resolve()
    if path not in _CACHE:
        _CACHE[path] = yaml.safe_load(path.read_text())
    return _CACHE[path]


def deref(ref: str, base: Path) -> tuple[Any, Path | None]:
    """Resolve one `$ref` to its node and the file that holds it.

    An external URL, such as the GeoJSON geometry schemas, returns `(None,
    None)`. Those describe shapes this catalog does not document per column.
    """
    if ref.startswith("http"):
        return None, None
    file_part, _, fragment = ref.partition("#")
    target = (base.parent / file_part).resolve() if file_part else base
    node = load(target)
    for segment in [s for s in fragment.split("/") if s]:
        key = segment.replace("~1", "/").replace("~0", "~")
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node, target


def expand(node: Any, base: Path, depth: int = 0) -> dict[str, Any]:
    """Follow a `$ref` until the node carries real keys.

    Keys on the referring node win over the referenced node, which is how a
    schema narrows a shared definition.
    """
    if depth > 12 or not isinstance(node, dict):
        return node if isinstance(node, dict) else {}
    if "$ref" not in node:
        return node
    target, target_file = deref(node["$ref"], base)
    local = {k: v for k, v in node.items() if k != "$ref"}
    if target is None:
        return local
    return {**expand(target, target_file or base, depth + 1), **local}


def properties_of(node: Any, base: Path, depth: int = 0) -> dict[str, Any]:
    """Flatten a node's properties, and follow its `allOf` containers."""
    out: dict[str, Any] = {}
    node = expand(node, base, depth)
    for sub in node.get("allOf", []) + node.get("oneOf", []):
        if isinstance(sub, dict) and "$ref" in sub:
            target, target_file = deref(sub["$ref"], base)
        else:
            target, target_file = sub, base
        if target is not None:
            out.update(properties_of(target, target_file or base, depth + 1))
    for name, spec in (node.get("properties") or {}).items():
        out[name] = expand(spec, base, depth + 1)
    return out


def enum_docs(path: Path) -> dict[str, str]:
    """Enum value meanings that Overture publishes only as YAML comments."""
    out: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current and buffer:
            out[current] = " ".join(buffer).strip()

    for line in path.read_text().splitlines():
        value = re.match(r"^\s*- ([A-Za-z0-9_]+)\s*(?:#\s?(.*))?$", line)
        if value:
            flush()
            current = value.group(1)
            buffer = [value.group(2)] if value.group(2) else []
            continue
        comment = re.match(r"^\s*#\s?(.*)$", line)
        if comment and current:
            buffer.append(comment.group(1))
            continue
        if line.strip() and current:
            flush()
            current, buffer = None, []
    flush()
    return {k: v for k, v in out.items() if v}


def columns_for(theme: str, type_name: str) -> dict[str, dict[str, Any]]:
    """Every documented column of one Overture type, keyed by column name."""
    path = SCHEMA_DIR / theme / f"{type_name}.yaml"
    top = load(path)
    resolved: dict[str, Any] = {}
    for name, spec in (top.get("properties") or {}).items():
        if name == "properties":
            resolved.update(properties_of(spec, path))
        else:
            resolved[name] = expand(spec, path)

    comments = enum_docs(path)
    theme_defs = SCHEMA_DIR / theme / "defs.yaml"
    if theme_defs.exists():
        comments.update(enum_docs(theme_defs))

    out: dict[str, dict[str, Any]] = {}
    for name, spec in resolved.items():
        spec = spec if isinstance(spec, dict) else {}
        per_collection = AUTHORED_PER_COLLECTION.get(
            f"{theme}/{type_name}:{name}"
        )
        description = (
            spec.get("description") or per_collection or AUTHORED.get(name)
        )
        if spec.get("description"):
            source = "overture-schema"
        elif description:
            source = "authored"
        else:
            source = None
        entry: dict[str, Any] = {
            "description": _tidy(description) if description else None,
            "source": source,
        }
        values = spec.get("enum")
        if values:
            entry["enum"] = [
                {"value": v, "description": _tidy(comments[v])}
                if v in comments else {"value": v}
                for v in values
            ]
        out[name] = entry
    return out


def _tidy(text: str) -> str:
    """Collapse the whitespace a folded YAML scalar leaves behind."""
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    if not SCHEMA_DIR.is_dir():
        fetch_schema()

    out = {
        "schema_tag": SCHEMA_TAG,
        "schema_url": SCHEMA_URL,
        "collections": {
            f"{theme}/{type_name}": columns_for(theme, type_name)
            for theme, type_name in PAIRS
        },
    }
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")

    described = total = enums = 0
    gaps: list[str] = []
    for key, cols in out["collections"].items():
        for name, entry in cols.items():
            total += 1
            if entry["description"]:
                described += 1
            else:
                gaps.append(f"{key}:{name}")
            if entry.get("enum"):
                enums += 1
    print(
        f"{described}/{total} columns described, {enums} carry enum values",
        file=sys.stderr,
    )
    if gaps:
        print(f"undocumented: {', '.join(gaps)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
