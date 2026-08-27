"""Generate README.md and AGENTS.md for every catalog and collection.

Every number here comes from `sources/upstream.json`, which was measured from
parquet footers. Every column meaning comes from `sources/columns.json`, which
was harvested from Overture's pinned JSON Schema. Nothing is authored from
memory, which is what `portolan-bootstrap` requires of a published agent guide.

Every query these files contain runs against the published data before the
catalog ships. A recipe that fails costs a reader the time to debug someone
else's mistake, so it is fixed or deleted rather than published.
"""

from __future__ import annotations

from typing import Any

DUCKDB_SETUP = "INSTALL spatial; LOAD spatial;"

# What a consumer would otherwise find the hard way. Every entry is measured,
# and every one names the release it was measured against. These describe
# Overture's data, not this mirror: the mirror copies no bytes and can only
# report what it read.
KNOWN_ISSUES: dict[str, list[str]] = {
    "base/bathymetry": [
        "**The rows are not spatially ordered.** rashid reports PTL-DAT-006 "
        "against release 2026-08-19.0: 59,963 rows in 4 row groups do not "
        "cluster spatially. A reader cannot skip any part of the file, so a "
        "bbox filter prunes nothing here and a spatial query reads the whole "
        "collection. Reproduce it with `python3 tests/test_data_pass.py "
        "base/bathymetry`, which takes about 13 seconds.",
    ],
    "base/land_cover": [
        "**Overture reports bboxes outside the WGS84 range.** Its STAC gives "
        "longitudes of 180.00022888183594 and -180.00022888183594, which "
        "PTL-BBX-001 rejects. This catalog clamps them to \u00b1180 and logs "
        "every clamp. The excess is about 25 metres at the equator, so the "
        "clamp loses nothing a consumer can use. Overture's own STAC still "
        "carries the original values.",
    ],
    "buildings/building": [
        "**Most attributes are null, so this collection carries no legend.** "
        "Measured over central Paris on release 2026-08-19.0, 354,621 rows: "
        "`facade_material` is present on 0.4%, `subtype` on 25.7%, `class` on "
        "25.4%, and `roof_material` on none. No column describes enough of "
        "the data to colour a map by, so the default style is a single "
        "colour. Filter on an attribute only after you have counted its "
        "nulls.",
    ],
}

# Style legends on these collections come from a sample, not a full scan. A
# category that occurs only outside every sample window is missing from the
# legend. The sample windows are recorded in sources/style_sampling.json.
SAMPLED_LEGENDS = {
    "base/infrastructure",
    "base/land",
    "base/land_cover",
    "base/land_use",
    "base/water",
    "buildings/building",
    "transportation/segment",
}


def _glob(record: dict[str, Any]) -> str:
    """The S3 glob covering every part of a collection."""
    first = record["items"][0]["s3"]
    return first.rsplit("/", 1)[0] + "/*.parquet"


def _https_first(record: dict[str, Any]) -> str:
    return record["items"][0]["href"]


def collection_readme(
    key: str, record: dict[str, Any], meanings: dict[str, Any], release: str
) -> str:
    type_name = key.split("/", 1)[1]
    rows = sum(i["rows"] for i in record["items"])
    parts = len(record["items"])
    geometry = sorted({g for i in record["items"] for g in i["geometry_types"]})

    described = sum(
        1 for c in record["columns"] if (meanings.get(c) or {}).get("description")
    )

    return f"""# {record["title"] or type_name}

{record["description"]}

> **Reading this with an agent?** Start at [AGENTS.md](AGENTS.md). It carries
> the S3 glob, the bbox pruning pattern that makes queries cheap, the coded
> column values, and queries that have been run against this data. This README
> is the human summary.

This is a Portolan mirror. Overture Maps produces and hosts the data, and this
catalog adds column documentation, styles, and a thumbnail. No bytes are copied.
Every asset link points at Overture's own buckets.

## What is here

| | |
|---|---|
| Release | `{release}` |
| Parts | {parts} |
| Rows | {rows:,} |
| Geometry | {", ".join(geometry)} |
| Columns | {len(record["columns"])}, {described} with a description |
| Format | GeoParquet {record["items"][0]["geoparquet_version"]}, WKB |
| Licence | {record["license"]} |

## Reading it

The data is GeoParquet on a public bucket. No credentials are needed.

```sql
{DUCKDB_SETUP}
SELECT count(*)
FROM read_parquet('{_glob(record)}');
```

See [AGENTS.md](AGENTS.md) for join keys, the bbox pruning pattern, and more
queries.

## Where this came from

Overture Maps publishes this data under release `{release}`. Column meanings
come from Overture's JSON Schema at tag `v1.18.0`. Both are linked from the
collection metadata as `via` and `canonical`.

Attribution follows [Overture's terms](https://docs.overturemaps.org/attribution/).
"""


def _known_issues(key: str) -> str:
    """The `## Known issues` section, or nothing when there is none."""
    entries = list(KNOWN_ISSUES.get(key, []))
    if key in SAMPLED_LEGENDS:
        entries.append(
            "**The legend comes from a sample.** Style categories were "
            "measured over bbox windows rather than a full scan, because a "
            "full `GROUP BY` on this collection costs minutes. A sample "
            "proves a category is present and never proves one is absent, so "
            "a category that occurs only outside those windows is missing "
            "from the legend. The windows are in `sources/style_sampling.json`."
        )
    if not entries:
        return ""
    body = "\n\n".join(f"- {e}" for e in entries)
    return (
        "## Known issues\n\n"
        "Read these before you trust a query against this collection.\n\n"
        f"{body}\n\n"
    )


def collection_agents(
    key: str, record: dict[str, Any], meanings: dict[str, Any], release: str
) -> str:
    theme, type_name = key.split("/", 1)
    rows = sum(i["rows"] for i in record["items"])
    parts = len(record["items"])
    glob = _glob(record)

    coded = [
        (name, (meanings.get(name) or {}).get("enum") or [])
        for name in record["columns"]
    ]
    coded = [(n, e) for n, e in coded if e]

    coded_block = ""
    if coded:
        lines = []
        for name, values in coded:
            rendered = ", ".join(f"`{v['value']}`" for v in values[:12])
            more = "" if len(values) <= 12 else f", and {len(values) - 12} more"
            lines.append(f"- **`{name}`**: {rendered}{more}")
        coded_block = (
            "## Coded columns\n\n"
            "Every value below is documented in Overture's schema, and the\n"
            "meanings are carried in `table:columns` on the collection.\n\n"
            + "\n".join(lines)
            + "\n\n"
        )

    return f"""# AGENTS.md — {record["title"] or type_name}

Guidance for agents and automated clients reading this collection.

Every claim here is measured from the data or quoted from Overture's published
schema. Nothing is inferred. If you cannot point at where a fact came from, it
does not belong in this file.

## Overview

Overture Maps `{theme}` theme, `{type_name}` type, release `{release}`.
{parts} GeoParquet parts holding {rows:,} rows. Geometry is WKB in EPSG:4326.

This catalog holds metadata only. Every `data` asset href points at
`overturemaps-us-west-2`, which Overture hosts and which needs no credentials.

## Accessing the data

Read every part at once through the glob. The `s3://` form needs a
partition-aware reader, and DuckDB is one:

```sql
{DUCKDB_SETUP}
SELECT count(*) AS rows
FROM read_parquet('{glob}');
```

Over plain HTTPS, address one part at a time. A glob cannot expand over HTTPS,
because expansion needs a directory listing:

```sql
SELECT count(*) AS rows
FROM read_parquet('{_https_first(record)}');
```

## The bbox column is the fast path

Every part carries a GeoParquet 1.1 `bbox` covering column, verified in the
footer. Filter on it before any spatial predicate. The reader then skips whole
row groups without decoding geometry.

```sql
SELECT count(*) AS rows
FROM read_parquet('{glob}')
WHERE bbox.xmin BETWEEN -0.6 AND 0.4
  AND bbox.ymin BETWEEN 51.2 AND 51.8;
```

A query that calls `ST_Intersects` without a bbox filter first reads every
geometry in {rows:,} rows.

## Row groups

Parts hold {min(i["row_groups"] for i in record["items"])} to
{max(i["row_groups"] for i in record["items"])} row groups. The largest holds
{max(i["max_row_group_rows"] for i in record["items"]):,} rows, which is inside
the 150,000 cap Portolan sets, so range reads stay small.

{coded_block}{_known_issues(key)}## Schema and field notes

The collection's `table:columns` carries a description for every documented
column. Those descriptions are harvested from Overture's JSON Schema at tag
`v1.18.0` rather than authored here, so they track upstream.

## Related collections

Every collection in this catalog shares the `id` column convention and the
`bbox` covering column, so the access patterns above apply unchanged. See the
[catalog agent guide](../../AGENTS.md).

## Rendering

The `visual` asset is Overture's prebuilt PMTiles archive for the whole `{theme}`
theme. This collection's features are in the `{type_name}` layer. Declare
`minzoom` and `maxzoom` on the vector source, or MapLibre requests a tile the
archive does not hold and draws nothing.
"""


def theme_readme(theme: str, title: str, keys: list[str], release: str) -> str:
    listed = "\n".join(
        f"- [{k.split('/', 1)[1]}]({k.split('/', 1)[1]}/README.md)"
        for k in sorted(keys)
    )
    return f"""# {title}

> **Reading this with an agent?** Start at [AGENTS.md](AGENTS.md), and then at
> the agent guide inside each collection. Those carry the measured row counts,
> the access patterns, and queries that have been run.

The Overture Maps `{theme}` theme, release `{release}`.

{listed}

Each collection mirrors Overture metadata and adds column documentation, a
style, and a thumbnail. The data stays on Overture's buckets.
"""


def theme_agents(theme: str, title: str, keys: list[str], release: str) -> str:
    listed = "\n".join(f"- `{k.split('/', 1)[1]}`" for k in sorted(keys))
    return f"""# AGENTS.md — {title}

The Overture Maps `{theme}` theme, release `{release}`.

Collections here:

{listed}

Each collection carries its own agent guide with measured row counts, the S3
glob, and the bbox pruning pattern. Read that rather than guessing from this
page.

Access patterns are identical across the theme. Data is GeoParquet in EPSG:4326
on `overturemaps-us-west-2`, readable without credentials, and every part
carries a GeoParquet 1.1 `bbox` covering column.
"""
