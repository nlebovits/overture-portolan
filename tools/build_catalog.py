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

    links.append(
        {
            "rel": "pmtiles",
            "href": record["pmtiles"],
            "type": PMTILES_TYPE,
            "title": f"Overture {theme} vector tiles",
            "pmtiles:layers": [type_name],
        }
    )

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
        "title": record["title"] or type_name.replace("_", " ").title(),
        "description": record["description"] or "",
        "license": licence,
        "providers": PROVIDERS,
        "extent": record["extent"],
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
    write(directory / "collection.json", collection)
    (directory / "README.md").write_text(
        docs.collection_readme(key, record, meanings, release)
    )
    (directory / "AGENTS.md").write_text(
        docs.collection_agents(key, record, meanings, release)
    )

    for item in record["items"]:
        write(directory / "items" / f"{item['id']}.json", build_item(item, type_name))

    return directory


def build_item(item: dict[str, Any], collection_id: str) -> dict[str, Any]:
    return {
        "type": "Feature",
        "stac_version": "1.1.0",
        "stac_extensions": [ALTERNATE_EXT],
        "id": item["id"],
        "collection": collection_id,
        "bbox": item["bbox"],
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


def build_theme(theme: str, type_names: list[str], release: str) -> None:
    title = THEME_TITLES.get(theme, theme.title())
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


def update_root(themes: list[str], release: str) -> None:
    """Add a child link per theme, and record the release in `updated`."""
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
        for theme in sorted(themes)
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
    for key, record in sorted(selected.items()):
        theme = record["theme"]
        if args.clean and (CATALOG / theme).exists():
            shutil.rmtree(CATALOG / theme)
        meanings = columns["collections"].get(key, {})
        directory = build_collection(key, record, meanings, release)
        by_theme.setdefault(theme, []).append(key.split("/", 1)[1])
        print(
            f"  {key}: {len(record['items'])} items -> {directory.relative_to(ROOT)}",
            file=sys.stderr,
        )

    for theme, type_names in sorted(by_theme.items()):
        build_theme(theme, type_names, release)

    update_root(sorted(by_theme), release)
    print(
        f"built {len(selected)} collection(s) from release {release}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
