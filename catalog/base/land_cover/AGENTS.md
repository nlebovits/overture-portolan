# AGENTS.md — Land Cover

Guidance for agents and automated clients reading this collection.

Every claim here is measured from the data or quoted from Overture's published
schema. Nothing is inferred. If you cannot point at where a fact came from, it
does not belong in this file.

## Overview

Overture Maps `base` theme, `land_cover` type, release `2026-08-19.0`.
128 GeoParquet parts holding 123,302,114 rows. Geometry is WKB in EPSG:4326.

This catalog holds metadata only. Every `data` asset href points at
`overturemaps-us-west-2`, which Overture hosts and which needs no credentials.

## Accessing the Data

Read every part at once through the glob. The `s3://` form needs a
partition-aware reader, and DuckDB is one:

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=base/type=land_cover/*.parquet');
```

Over plain HTTPS, address one part at a time. A glob cannot expand over HTTPS,
because expansion needs a directory listing:

```sql
SELECT count(*) AS rows
FROM read_parquet('https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=base/type=land_cover/part-00000-4720939f-e9d9-5bb1-9182-85d871b23a33-c000.zstd.parquet');
```

## The Bbox Column Is the Fast Path

Every part carries a GeoParquet 1.1 `bbox` covering column, verified in the
footer. Filter on it before any spatial predicate. The reader then skips whole
row groups without decoding geometry.

```sql
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=base/type=land_cover/*.parquet')
WHERE bbox.xmin BETWEEN -0.6 AND 0.4
  AND bbox.ymin BETWEEN 51.2 AND 51.8;
```

A query that calls `ST_Intersects` without a bbox filter first reads every
geometry in 123,302,114 rows.

## Row Groups

Parts hold 64 to
128 row groups. The largest holds
19,590 rows, which is inside
the 150,000 cap Portolan sets, so range reads stay small.

## Coded Columns

Every value below is documented in Overture's schema, and the
meanings are carried in `table:columns` on the collection.

- **`subtype`**: `barren`, `crop`, `forest`, `grass`, `mangrove`, `moss`, `shrub`, `snow`, `urban`, `wetland`

## Known Issues

Read these before you trust a query against this collection.

- **Overture reports bboxes outside the WGS84 range.** Its STAC gives longitudes of 180.00022888183594 and -180.00022888183594, which PTL-BBX-001 rejects. This catalog clamps them to ±180 and logs every clamp. The excess is about 25 metres at the equator, so the clamp loses nothing a consumer can use. Overture's own STAC still carries the original values.

- **The legend comes from a sample.** Style categories were measured over bbox windows rather than a full scan, because a full `GROUP BY` on this collection costs minutes. A sample proves a category is present and never proves one is absent, so a category that occurs only outside those windows is missing from the legend. The windows are in `sources/style_sampling.json`.

## Schema and Field Notes

The collection's `table:columns` carries a description for every documented
column. Those descriptions are harvested from Overture's JSON Schema at tag
`v1.18.0` rather than authored here, so they track upstream.

## Related Collections

Every collection in this catalog shares the `id` column convention and the
`bbox` covering column, so the access patterns above apply unchanged. See the
[catalog agent guide](../../AGENTS.md).

## Rendering

The `visual` asset is Overture's prebuilt PMTiles archive for the whole `base`
theme. This collection's features are in the `land_cover` layer. Declare
`minzoom` and `maxzoom` on the vector source, or MapLibre requests a tile the
archive does not hold and draws nothing.
