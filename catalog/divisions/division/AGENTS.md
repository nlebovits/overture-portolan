# AGENTS.md — division

Guidance for agents and automated clients reading this collection.

Every claim here is measured from the data or quoted from Overture's published
schema. Nothing is inferred. If you cannot point at where a fact came from, it
does not belong in this file.

## Overview

Overture Maps `divisions` theme, `division` type, release `2026-08-19.0`.
1 GeoParquet parts holding 4,658,700 rows. Geometry is WKB in EPSG:4326.

This catalog holds metadata only. Every `data` asset href points at
`overturemaps-us-west-2`, which Overture hosts and which needs no credentials.

## Accessing the data

Read every part at once through the glob. The `s3://` form needs a
partition-aware reader, and DuckDB is one:

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division/*.parquet');
```

Over plain HTTPS, address one part at a time. A glob cannot expand over HTTPS,
because expansion needs a directory listing:

```sql
SELECT count(*) AS rows
FROM read_parquet('https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=divisions/type=division/part-00000-4427279e-644a-58f2-bf86-ec1c351e39f4-c000.zstd.parquet');
```

## The bbox column is the fast path

Every part carries a GeoParquet 1.1 `bbox` covering column, verified in the
footer. Filter on it before any spatial predicate. The reader then skips whole
row groups without decoding geometry.

```sql
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division/*.parquet')
WHERE bbox.xmin BETWEEN -0.6 AND 0.4
  AND bbox.ymin BETWEEN 51.2 AND 51.8;
```

A query that calls `ST_Intersects` without a bbox filter first reads every
geometry in 4,658,700 rows.

## Row groups

Parts hold 256 to
256 row groups. The largest holds
27,258 rows, which is inside
the 150,000 cap Portolan sets, so range reads stay small.

## Coded columns

Every value below is documented in Overture's schema, and the
meanings are carried in `table:columns` on the collection.

- **`subtype`**: `country`, `dependency`, `macroregion`, `region`, `macrocounty`, `county`, `localadmin`, `locality`, `borough`, `macrohood`, `neighborhood`, `microhood`
- **`class`**: `megacity`, `city`, `town`, `village`, `hamlet`

## Schema and field notes

The collection's `table:columns` carries a description for every documented
column. Those descriptions are harvested from Overture's JSON Schema at tag
`v1.18.0` rather than authored here, so they track upstream.

## Related collections

Every collection in this catalog shares the `id` column convention and the
`bbox` covering column, so the access patterns above apply unchanged. See the
[catalog agent guide](../../AGENTS.md).

## Rendering

The `visual` asset is Overture's prebuilt PMTiles archive for the whole `divisions`
theme. This collection's features are in the `division` layer. Declare
`minzoom` and `maxzoom` on the vector source, or MapLibre requests a tile the
archive does not hold and draws nothing.
