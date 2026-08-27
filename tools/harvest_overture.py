#!/usr/bin/env python3
"""Harvest Overture's STAC and parquet footers into sources/upstream.json.

Overture publishes correct STAC 1.1.0, so this reads rather than infers. It
follows `latest` from the STAC root, walks the theme catalogs to the 15
collections, and takes one item per parquet part.

Each item's `aws` asset becomes the `data` href. The `azure` asset is dropped:
it answers `Range` but sends no CORS headers, so a browser cannot read it.

The parquet footer is read over HTTP range, which costs about 0.7 seconds per
file and downloads none of the data. It supplies the facts this catalog states
about the upstream: row counts, row-group sizes, the GeoParquet version, and
the covering bbox column that makes spatial pruning work.

The same walk writes sources/fingerprint.json. The sync workflow diffs against
it and fails when a column, a collection, or a licence changes, so a human
reviews what moved before the catalog follows.

Usage:
    python3 tools/harvest_overture.py                 # all 15 collections
    python3 tools/harvest_overture.py -c divisions/division_area
    python3 tools/harvest_overture.py --workers 8
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pyarrow.fs as pafs
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
STAC_ROOT = "https://stac.overturemaps.org/catalog.json"
DOCS_URL = "https://docs.overturemaps.org/"
PARQUET_BUCKET = "overturemaps-us-west-2"
TILES_BUCKET = "overturemaps-extras-us-west-2"
TILES_BASE = f"https://{TILES_BUCKET}.s3.us-west-2.amazonaws.com/tiles"

# PORTO-DAT-008 caps a row group at this many rows. Recorded per collection so
# the sync gate fails when an Overture release crosses it.
MAX_ROW_GROUP_ROWS = 150_000

TIMEOUT = 60


def fetch(url: str) -> Any:
    """One STAC document."""
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return json.load(response)


def links(doc: Any, rel: str) -> list[dict[str, Any]]:
    return [link for link in doc.get("links", []) if link.get("rel") == rel]


def footer(s3: pafs.S3FileSystem, href: str) -> dict[str, Any]:
    """Facts from one parquet footer, read over range requests."""
    path = PARQUET_BUCKET + "/" + href.split(".amazonaws.com/", 1)[1]
    handle = pq.ParquetFile(s3.open_input_file(path))
    meta = handle.metadata
    rows = [meta.row_group(i).num_rows for i in range(meta.num_row_groups)]

    geo = handle.schema_arrow.metadata.get(b"geo")
    geo = json.loads(geo) if geo else {}
    primary = geo.get("primary_column")
    column = (geo.get("columns") or {}).get(primary, {})

    return {
        "rows": meta.num_rows,
        "row_groups": meta.num_row_groups,
        "max_row_group_rows": max(rows) if rows else 0,
        "geoparquet_version": geo.get("version"),
        "geometry_column": primary,
        "geometry_encoding": column.get("encoding"),
        "has_covering_bbox": bool(column.get("covering")),
        "geometry_types": sorted(column.get("geometry_types") or []),
    }


def harvest_item(s3: pafs.S3FileSystem, url: str) -> dict[str, Any]:
    """One parquet part, as the facts a STAC item needs."""
    item = fetch(url)
    asset = item["assets"]["aws"]
    href = asset["href"]
    record = {
        "id": item["id"],
        "bbox": item.get("bbox"),
        "geometry": item.get("geometry"),
        "datetime": (item.get("properties") or {}).get("datetime"),
        "href": href,
        "s3": f"s3://{PARQUET_BUCKET}/" + href.split(".amazonaws.com/", 1)[1],
        "upstream_item": url,
    }
    record.update(footer(s3, href))
    return record


def harvest_collection(
    s3: pafs.S3FileSystem, url: str, theme: str, workers: int
) -> dict[str, Any]:
    """One Overture collection, with every part it holds."""
    collection = fetch(url)
    item_urls = sorted(link["href"] for link in links(collection, "item"))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        items = list(pool.map(lambda u: harvest_item(s3, u), item_urls))
    items.sort(key=lambda record: record["id"])

    return {
        "id": collection["id"],
        "theme": theme,
        "title": collection.get("title"),
        "description": collection.get("description"),
        "license": collection.get("license"),
        "extent": collection.get("extent"),
        "columns": [c["name"] for c in collection.get("table:columns", [])],
        "upstream_collection": url,
        "pmtiles": f"{TILES_BASE}/{{release}}/{theme}.pmtiles",
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c",
        "--collection",
        action="append",
        metavar="THEME/TYPE",
        help="restrict to one collection; repeatable",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=str(ROOT / "sources" / "upstream.json"))
    args = parser.parse_args()

    root = fetch(STAC_ROOT)
    release = root["latest"]
    release_url = next(
        link["href"] for link in links(root, "child") if link.get("latest")
    )
    print(f"release {release}", file=sys.stderr)

    s3 = pafs.S3FileSystem(anonymous=True, region="us-west-2")
    wanted = set(args.collection or [])
    collections: dict[str, Any] = {}

    for theme_link in sorted(
        links(fetch(release_url), "child"), key=lambda link: link["href"]
    ):
        theme_doc = fetch(theme_link["href"])
        theme = theme_doc["id"]
        for child in sorted(links(theme_doc, "child"), key=lambda link: link["href"]):
            url = child["href"]
            type_name = url.rstrip("/").split("/")[-2]
            key = f"{theme}/{type_name}"
            if wanted and key not in wanted:
                continue
            record = harvest_collection(s3, url, theme, args.workers)
            record["pmtiles"] = record["pmtiles"].format(release=release)
            collections[key] = record
            print(
                f"  {key}: {len(record['items'])} parts, "
                f"{sum(i['rows'] for i in record['items']):,} rows",
                file=sys.stderr,
            )

    upstream = {
        "release": release,
        "stac_root": STAC_ROOT,
        "docs_url": DOCS_URL,
        "collections": collections,
    }
    Path(args.out).write_text(json.dumps(upstream, indent=2, sort_keys=True) + "\n")

    fingerprint = {
        "release": release,
        "collections": {
            key: {
                "columns": record["columns"],
                "items": len(record["items"]),
                "license": record["license"],
                "geoparquet": sorted(
                    {i["geoparquet_version"] for i in record["items"]}
                ),
                "max_row_group_rows": max(
                    i["max_row_group_rows"] for i in record["items"]
                ),
                "row_group_cap": MAX_ROW_GROUP_ROWS,
            }
            for key, record in collections.items()
        },
    }
    (ROOT / "sources" / "fingerprint.json").write_text(
        json.dumps(fingerprint, indent=2, sort_keys=True) + "\n"
    )
    print(f"wrote {args.out} and sources/fingerprint.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
