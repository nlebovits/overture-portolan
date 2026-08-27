#!/usr/bin/env python3
"""Build catalog/ from sources/upstream.json and sources/columns.json.

The layout mirrors Overture's own: a theme sub-catalog per theme, and a
collection per type under it. That keeps every `canonical` link a one-to-one
match with the upstream object it mirrors.

Every `data` href points at Overture's bucket. This catalog stores no data. The
`visual` asset points at Overture's prebuilt PMTiles for the theme, which is what
gives each collection a zero-infrastructure render path.

`file:size` and `file:checksum` are deliberately absent from upstream assets.
rashid's data pass reads every byte of an asset that declares either, so
declaring them would turn `portolan check` into a 611.6 GB download. Both are a
SHOULD under PORTO-CORE-028. See docs/publication.md.

Output is deterministic. Every list is sorted and the only timestamp is the
Overture release date, so an unchanged release produces an unchanged tree.

Usage:
    python3 tools/build_catalog.py
    python3 tools/build_catalog.py -c divisions/division_area
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import docs

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
SOURCES = ROOT / "sources"

PORTOLAN_SCHEMA = "https://schemas.portolan-sdi.org/portolan/v0.1.1/schema.json"
TABLE_EXT = "https://stac-extensions.github.io/table/v1.2.0/schema.json"
ALTERNATE_EXT = "https://stac-extensions.github.io/alternate-assets/v1.2.0/schema.json"
WEB_MAP_LINKS_EXT = "https://stac-extensions.github.io/web-map-links/v1.3.0/schema.json"

PARQUET_TYPE = "application/vnd.apache.parquet"
PMTILES_TYPE = "application/vnd.pmtiles"
STYLE_TYPE = "application/vnd.mapbox.style+json"

DOCS = "https://docs.overturemaps.org"
ATTRIBUTION_URL = f"{DOCS}/attribution/"

# Overture licences differ by theme. base, buildings, divisions, and
# transportation are ODbL. addresses and places draw on mixed sources, so no
# single SPDX identifier fits and PORTO-CORE-047 requires `other` plus a licence
# link. Quoted from https://docs.overturemaps.org/attribution/.
MIXED_LICENCE_THEMES = {"addresses", "places"}

PROVIDERS = [
    {
        "name": "Overture Maps Foundation",
        "roles": ["producer", "licensor"],
        "url": "https://overturemaps.org/",
    },
    {
        "name": "Amazon Web Services",
        "roles": ["host"],
        "url": "https://registry.opendata.aws/",
    },
]

THEME_TITLES = {
    "addresses": "Addresses",
    "base": "Base",
    "buildings": "Buildings",
    "divisions": "Divisions",
    "places": "Places",
    "transportation": "Transportation",
}


def load(name: str) -> Any:
    path = SOURCES / name
    if not path.exists():
        sys.exit(f"missing {path}. Run the harvest scripts first.")
    return json.loads(path.read_text())


def write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n")


def table_columns(
    column_names: list[str], meanings: dict[str, Any]
) -> list[dict[str, Any]]:
    """`table:columns` for the columns the data actually holds.

    The column list comes from the upstream STAC, which reflects the parquet.
    The meanings come from Overture's pinned JSON Schema. A column the schema
    does not cover ships with no description rather than an invented one.
    """
    out = []
    for name in column_names:
        entry: dict[str, Any] = {"name": name}
        meaning = meanings.get(name) or {}
        if meaning.get("description"):
            entry["description"] = meaning["description"]
        out.append(entry)
    return out


def build_collection(
    key: str, record: dict[str, Any], meanings: dict[str, Any], release: str
) -> Path:
    theme = record["theme"]
    type_name = key.split("/", 1)[1]
    directory = CATALOG / theme / type_name

    mixed = theme in MIXED_LICENCE_THEMES
    licence = "other" if mixed else record["license"]

    links: list[dict[str, Any]] = [
        {
            "rel": "root",
            "href": "../../catalog.json",
            "type": "application/json",
            "title": "Overture Maps",
        },
        {
            "rel": "parent",
            "href": "../catalog.json",
            "type": "application/json",
            "title": THEME_TITLES.get(theme, theme.title()),
        },
        {
            "rel": "describedby",
            "href": "./README.md",
            "type": "text/markdown",
            "title": "Collection README",
        },
        {
            "rel": "agents",
            "href": "./AGENTS.md",
            "type": "text/markdown",
            "title": "Collection agent guide",
        },
        {
            "rel": "via",
            "href": f"{DOCS}/{theme}/{type_name}",
            "type": "text/html",
            "title": f"Overture documentation for {type_name}",
        },
        {
            "rel": "canonical",
            "href": record["upstream_collection"],
            "type": "application/json",
            "title": "Overture STAC collection",
        },
    ]
    if mixed:
        links.append(
            {
                "rel": "license",
                "href": ATTRIBUTION_URL,
                "type": "text/html",
                "title": "Overture attribution and licence terms",
            }
        )

    # PTL-COL-001: a collection with one data file carries that file at
    # collection level. A single item wrapping it adds indirection the spec
    # forbids.
    single = len(record["items"]) == 1

    links.append(
        {
            "rel": "pmtiles",
            "href": record["pmtiles"],
            "type": PMTILES_TYPE,
            "title": f"Overture {theme} vector tiles",
            "pmtiles:layers": [type_name],
        }
    )

    if not single:
        for item in record["items"]:
            links.append(
                {
                    "rel": "item",
                    "href": f"./items/{item['id']}.json",
                    "type": "application/geo+json",
                    "title": f"Part {item['id']}, {item['rows']:,} rows",
                }
            )

    collection = {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": sorted([PORTOLAN_SCHEMA, TABLE_EXT, WEB_MAP_LINKS_EXT]),
        "id": type_name,
        "title": human_title(record["title"], type_name),
        "description": record["description"] or "",
        "license": licence,
        "providers": PROVIDERS,
        "extent": clamp_extent(record["extent"], key),
        "updated": f"{release[:10]}T00:00:00Z",
        "table:columns": table_columns(record["columns"], meanings),
        "assets": {
            "visual": {
                "href": record["pmtiles"],
                "type": PMTILES_TYPE,
                "roles": ["visual"],
                "title": f"Overture {theme} vector tiles",
                "description": (
                    "Overture's prebuilt PMTiles archive for the whole "
                    f"{theme} theme. This collection's features are in the "
                    f"`{type_name}` layer."
                ),
            },
            "thumbnail": {
                "href": "./thumbnail.png",
                "type": "image/png",
                "roles": ["thumbnail"],
                "title": "Thumbnail",
            },
            "default-style": {
                "href": "./styles/default.json",
                "type": STYLE_TYPE,
                "roles": ["style", "default"],
                "title": "Default style",
            },
        },
        "links": links,
    }
    collection["assets"].update(style_assets(directory))

    if single:
        collection["assets"]["data"] = data_asset(record["items"][0])
        collection["stac_extensions"] = sorted(
            [*collection["stac_extensions"], ALTERNATE_EXT]
        )

    write(directory / "collection.json", collection)
    (directory / "README.md").write_text(
        docs.collection_readme(key, record, meanings, release)
    )
    (directory / "AGENTS.md").write_text(
        docs.collection_agents(key, record, meanings, release)
    )

    # A single-file collection carries its data at collection level, so it
    # writes no items at all. `written` stays empty, and the prune below then
    # removes every item file a previous release left behind. That is the
    # multi-part-to-single-part transition, which Overture does make:
    # buildings/building_part went 3 parts to 1 between the only two releases
    # available.
    written = set()
    if not single:
        for item in record["items"]:
            path = directory / "items" / f"{item['id']}.json"
            write(path, build_item(item, type_name))
            written.add(path)

    # Overture repartitions between releases, so a collection can hold fewer
    # parts than it did. An item file left from the last release keeps a href
    # into a pruned release directory, and the collection no longer links it.
    # Nothing else deletes it: only --clean removes a theme, and that also
    # removes the thumbnails and styles, which the sync does not regenerate.
    items_dir = directory / "items"
    for stale in sorted(items_dir.glob("*.json")):
        if stale not in written:
            stale.unlink()
            print(f"    removed stale {stale.relative_to(ROOT)}", file=sys.stderr)
    if items_dir.is_dir() and not any(items_dir.iterdir()):
        items_dir.rmdir()

    return directory


def human_title(upstream: str | None, type_name: str) -> str:
    """A human-readable title, per PTL-TTL-002.

    Overture's own collection title is often the raw slug, such as
    `land_cover`. Passing that through publishes a slug where a title belongs,
    so a slug is expanded rather than copied.
    """
    slug = type_name.replace("_", " ").title()
    if not upstream or upstream.replace("_", " ").strip().lower() == (
        type_name.replace("_", " ").lower()
    ):
        return slug
    return upstream


CLAMPED: list[str] = []


def clamp_bbox(bbox: list[float] | None, where: str) -> list[float] | None:
    """Hold a bbox inside the WGS84 range, and record every clamp.

    Overture's `base/land_cover` reports longitudes of +/-180.00022888183594,
    which PTL-BBX-001 rejects. The excess is about 25 metres at the equator, so
    a clamp loses nothing a consumer can use. It is recorded rather than
    applied silently, because the defect belongs upstream and the record is
    what lets someone report it.
    """
    if not bbox:
        return bbox
    out = list(bbox)
    for index, limit in ((0, 180.0), (2, 180.0)):
        if abs(out[index]) > limit:
            CLAMPED.append(
                f"{where}: lon {out[index]} -> {limit * (1 if out[index] > 0 else -1)}"
            )
            out[index] = limit if out[index] > 0 else -limit
    for index, limit in ((1, 90.0), (3, 90.0)):
        if abs(out[index]) > limit:
            CLAMPED.append(f"{where}: lat {out[index]}")
            out[index] = limit if out[index] > 0 else -limit
    return out


STYLE_TITLES = {
    "flat": "Single colour",
    "zoom": "By zoom level",
}


def style_assets(directory: Path) -> dict[str, Any]:
    """Every style on disk beside `default.json`, as collection assets.

    PORTO-CORE-069 requires each style to be a collection-level asset carrying
    the `style` role, and `portolan-bootstrap` asks for three to five per
    dataset. `make_styles.py` writes the alternates; without this they sit on
    disk undeclared, which is a style a client cannot find.

    `default.json` is declared separately, because PORTO-CORE-070 requires
    exactly one asset to carry both `style` and `default`.
    """
    out: dict[str, Any] = {}
    for path in sorted((directory / "styles").glob("*.json")):
        stem = path.stem
        if stem == "default":
            continue
        title = STYLE_TITLES.get(stem)
        if title is None and stem.startswith("by_"):
            title = "By " + stem[3:].replace("_", " ")
        out[f"style-{stem.replace('_', '-')}"] = {
            "href": f"./styles/{path.name}",
            "type": STYLE_TYPE,
            "roles": ["style"],
            "title": title or stem.replace("_", " ").capitalize(),
        }
    return out


def data_asset(item: dict[str, Any]) -> dict[str, Any]:
    """The `data` asset for one parquet part.

    `file:size` and `file:checksum` are deliberately absent. rashid reads every
    byte of an asset that declares either, so declaring them would turn a check
    into a 611.6 GB download. Both are a SHOULD under PORTO-CORE-028.
    """
    return {
        "href": item["href"],
        "type": PARQUET_TYPE,
        "roles": ["data"],
        "title": f"GeoParquet part {item['id']}",
        "alternate": {
            "s3": {
                "href": item["s3"],
                "title": "S3, us-west-2, no credentials needed",
            }
        },
    }


def clamp_extent(extent: dict[str, Any], where: str) -> dict[str, Any]:
    """The collection extent, with every bbox held inside the WGS84 range."""
    out = json.loads(json.dumps(extent))
    boxes = ((out.get("spatial") or {}).get("bbox")) or []
    (out["spatial"])["bbox"] = [clamp_bbox(b, where) for b in boxes]
    return out


def build_item(item: dict[str, Any], collection_id: str) -> dict[str, Any]:
    return {
        "type": "Feature",
        "stac_version": "1.1.0",
        "stac_extensions": [ALTERNATE_EXT],
        "id": item["id"],
        "collection": collection_id,
        "bbox": clamp_bbox(item["bbox"], f"{collection_id}/{item['id']}"),
        "geometry": item["geometry"],
        "properties": {
            "datetime": item["datetime"],
            "table:row_count": item["rows"],
        },
        "assets": {
            "data": {
                "href": item["href"],
                "type": PARQUET_TYPE,
                "roles": ["data"],
                "title": f"GeoParquet part {item['id']}",
                "alternate": {
                    "s3": {
                        "href": item["s3"],
                        "title": "S3, us-west-2, no credentials needed",
                    }
                },
            }
        },
        "links": [
            {
                "rel": "root",
                "href": "../../../catalog.json",
                "type": "application/json",
                "title": "Overture Maps",
            },
            {"rel": "parent", "href": "../collection.json", "type": "application/json"},
            {
                "rel": "collection",
                "href": "../collection.json",
                "type": "application/json",
            },
        ],
    }


def theme_children(theme: str) -> list[str]:
    """Every collection on disk under a theme, sorted.

    Read from the filesystem rather than from what this run built. A `-c` build
    touches one collection, and its theme catalog must still link the rest.
    """
    root = CATALOG / theme
    return sorted(path.parent.name for path in root.glob("*/collection.json"))


def catalog_themes() -> list[str]:
    """Every theme on disk, sorted. Same reason as `theme_children`."""
    return sorted(path.parent.name for path in CATALOG.glob("*/catalog.json"))


def build_theme(theme: str, type_names: list[str], release: str) -> None:
    title = THEME_TITLES.get(theme, theme.title())
    type_names = theme_children(theme) or type_names
    keys = [f"{theme}/{name}" for name in type_names]
    (CATALOG / theme / "README.md").write_text(
        docs.theme_readme(theme, title, keys, release)
    )
    (CATALOG / theme / "AGENTS.md").write_text(
        docs.theme_agents(theme, title, keys, release)
    )
    write(
        CATALOG / theme / "catalog.json",
        {
            "type": "Catalog",
            "stac_version": "1.1.0",
            "stac_extensions": [PORTOLAN_SCHEMA],
            "id": theme,
            "title": THEME_TITLES.get(theme, theme.title()),
            "description": (
                f"Overture Maps {THEME_TITLES.get(theme, theme)} theme. "
                f"Holds {len(type_names)} collection"
                f"{'s' if len(type_names) != 1 else ''}."
            ),
            "links": [
                {
                    "rel": "root",
                    "href": "../catalog.json",
                    "type": "application/json",
                    "title": "Overture Maps",
                },
                {
                    "rel": "parent",
                    "href": "../catalog.json",
                    "type": "application/json",
                    "title": "Overture Maps",
                },
                {
                    "rel": "describedby",
                    "href": "./README.md",
                    "type": "text/markdown",
                    "title": "Theme README",
                },
                {
                    "rel": "agents",
                    "href": "./AGENTS.md",
                    "type": "text/markdown",
                    "title": "Theme agent guide",
                },
                *[
                    {
                        "rel": "child",
                        "href": f"./{name}/collection.json",
                        "type": "application/json",
                        "title": name.replace("_", " ").title(),
                    }
                    for name in sorted(type_names)
                ],
            ],
        },
    )


def update_root(release: str) -> None:
    """Link every theme on disk, and record the release in `updated`."""
    path = CATALOG / "catalog.json"
    root = json.loads(path.read_text())
    keep = [link for link in root["links"] if link.get("rel") != "child"]
    root["links"] = keep + [
        {
            "rel": "child",
            "href": f"./{theme}/catalog.json",
            "type": "application/json",
            "title": THEME_TITLES.get(theme, theme.title()),
        }
        for theme in catalog_themes()
    ]
    root["updated"] = f"{release[:10]}T00:00:00Z"
    write(path, root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--collection", action="append", metavar="THEME/TYPE")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove generated theme directories before the build",
    )
    args = parser.parse_args()

    upstream = load("upstream.json")
    columns = load("columns.json")
    release = upstream["release"]

    wanted = set(args.collection or [])
    selected = {
        key: record
        for key, record in upstream["collections"].items()
        if not wanted or key in wanted
    }
    if not selected:
        sys.exit("no collections matched")

    by_theme: dict[str, list[str]] = {}
    if args.clean:
        for theme in sorted({r["theme"] for r in selected.values()}):
            if (CATALOG / theme).exists():
                shutil.rmtree(CATALOG / theme)

    for key, record in sorted(selected.items()):
        theme = record["theme"]
        meanings = columns["collections"].get(key, {})
        directory = build_collection(key, record, meanings, release)
        by_theme.setdefault(theme, []).append(key.split("/", 1)[1])
        print(
            f"  {key}: {len(record['items'])} items -> {directory.relative_to(ROOT)}",
            file=sys.stderr,
        )

    for theme, type_names in sorted(by_theme.items()):
        build_theme(theme, type_names, release)

    update_root(release)
    if CLAMPED:
        print(
            f"\n{len(CLAMPED)} bbox value(s) clamped to the WGS84 range. "
            "This is an upstream defect; report it to Overture.",
            file=sys.stderr,
        )
        for entry in CLAMPED[:6]:
            print(f"    {entry}", file=sys.stderr)
        if len(CLAMPED) > 6:
            print(f"    ... and {len(CLAMPED) - 6} more", file=sys.stderr)

    print(
        f"built {len(selected)} collection(s) from release {release}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
