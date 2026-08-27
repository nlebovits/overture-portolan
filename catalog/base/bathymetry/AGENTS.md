# AGENTS.md — Bathymetry

Guidance for agents and automated clients reading this collection.

Every claim here is measured from the data or quoted from Overture's published
schema. Nothing is inferred. If you cannot point at where a fact came from, it
does not belong in this file.

## Overview

Overture Maps `base` theme, `bathymetry` type, release `2026-08-19.0`.
1 GeoParquet parts holding 59,963 rows. Geometry is WKB in EPSG:4326.

This catalog holds metadata only. Every `data` asset href points at
`overturemaps-us-west-2`, which Overture hosts and which needs no credentials.

## Accessing the Data

Read every part at once through the glob. The `s3://` form needs a
partition-aware reader, and DuckDB is one:

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=base/type=bathymetry/*.parquet');
```

Over plain HTTPS, address one part at a time. A glob cannot expand over HTTPS,
because expansion needs a directory listing:

```sql
SELECT count(*) AS rows
FROM read_parquet('https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=base/type=bathymetry/part-00000-cf17cfee-00e5-5871-9cab-7f48d910d28f-c000.zstd.parquet');
```

## The Bbox Column Is the Fast Path

Every part carries a GeoParquet 1.1 `bbox` covering column, verified in the
footer. Filter on it before any spatial predicate. The reader then skips whole
row groups without decoding geometry.

```sql
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=base/type=bathymetry/*.parquet')
WHERE bbox.xmin BETWEEN -0.6 AND 0.4
  AND bbox.ymin BETWEEN 51.2 AND 51.8;
```

A query that calls `ST_Intersects` without a bbox filter first reads every
geometry in 59,963 rows.

## Row Groups

Parts hold 4 to
4 row groups. The largest holds
15,200 rows, which is inside
the 150,000 cap Portolan sets, so range reads stay small.

## Known Issues

Read these before you trust a query against this collection.

- **The rows are not spatially ordered.** rashid reports PTL-DAT-006 against release 2026-08-19.0: 59,963 rows in 4 row groups do not cluster spatially. A reader cannot skip any part of the file, so a bbox filter prunes nothing here and a spatial query reads the whole collection. Reproduce it with `python3 tests/test_data_pass.py base/bathymetry`, which takes about 13 seconds.

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
theme. This collection's features are in the `bathymetry` layer. Declare
`minzoom` and `maxzoom` on the vector source, or MapLibre requests a tile the
archive does not hold and draws nothing.
