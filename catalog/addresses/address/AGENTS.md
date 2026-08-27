# AGENTS.md — Address

Guidance for agents and automated clients reading this collection.

Every claim here is measured from the data or quoted from Overture's published
schema. Nothing is inferred. If you cannot point at where a fact came from, it
does not belong in this file.

## Overview

Overture Maps `addresses` theme, `address` type, release `2026-08-19.0`.
32 GeoParquet parts holding 472,797,160 rows. Geometry is WKB in EPSG:4326.

This catalog holds metadata only. Every `data` asset href points at
`overturemaps-us-west-2`, which Overture hosts and which needs no credentials.

## Accessing the Data

Read every part at once through the glob. The `s3://` form needs a
partition-aware reader, and DuckDB is one:

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=addresses/type=address/*.parquet');
```

Over plain HTTPS, address one part at a time. A glob cannot expand over HTTPS,
because expansion needs a directory listing:

```sql
SELECT count(*) AS rows
FROM read_parquet('https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=addresses/type=address/part-00000-239b7d07-845d-5c63-9969-d08b18f7957d-c000.zstd.parquet');
```

## The Bbox Column Is the Fast Path

Every part carries a GeoParquet 1.1 `bbox` covering column, verified in the
footer. Filter on it before any spatial predicate. The reader then skips whole
row groups without decoding geometry.

```sql
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=addresses/type=address/*.parquet')
WHERE bbox.xmin BETWEEN -0.6 AND 0.4
  AND bbox.ymin BETWEEN 51.2 AND 51.8;
```

A query that calls `ST_Intersects` without a bbox filter first reads every
geometry in 472,797,160 rows.

## Row Groups

Parts hold 256 to
512 row groups. The largest holds
97,727 rows, which is inside
the 150,000 cap Portolan sets, so range reads stay small.

## Schema and Field Notes

The collection's `table:columns` carries a description for every documented
column. Those descriptions are harvested from Overture's JSON Schema at tag
`v1.18.0` rather than authored here, so they track upstream.

## Related Collections

Every collection in this catalog shares the `id` column convention and the
`bbox` covering column, so the access patterns above apply unchanged. See the
[catalog agent guide](../../AGENTS.md).

## Rendering

The `visual` asset is Overture's prebuilt PMTiles archive for the whole `addresses`
theme. This collection's features are in the `address` layer. Declare
`minzoom` and `maxzoom` on the vector source, or MapLibre requests a tile the
archive does not hold and draws nothing.
