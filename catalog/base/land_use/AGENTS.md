# AGENTS.md — land_use

Guidance for agents and automated clients reading this collection.

Every claim here is measured from the data or quoted from Overture's published
schema. Nothing is inferred. If you cannot point at where a fact came from, it
does not belong in this file.

## Overview

Overture Maps `base` theme, `land_use` type, release `2026-08-19.0`.
32 GeoParquet parts holding 55,617,746 rows. Geometry is WKB in EPSG:4326.

This catalog holds metadata only. Every `data` asset href points at
`overturemaps-us-west-2`, which Overture hosts and which needs no credentials.

## Accessing the data

Read every part at once through the glob. The `s3://` form needs a
partition-aware reader, and DuckDB is one:

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=base/type=land_use/*.parquet');
```

Over plain HTTPS, address one part at a time. A glob cannot expand over HTTPS,
because expansion needs a directory listing:

```sql
SELECT count(*) AS rows
FROM read_parquet('https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=base/type=land_use/part-00000-e960da61-9e0a-5b84-915c-e06285a09182-c000.zstd.parquet');
```

## The bbox column is the fast path

Every part carries a GeoParquet 1.1 `bbox` covering column, verified in the
footer. Filter on it before any spatial predicate. The reader then skips whole
row groups without decoding geometry.

```sql
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=base/type=land_use/*.parquet')
WHERE bbox.xmin BETWEEN -0.6 AND 0.4
  AND bbox.ymin BETWEEN 51.2 AND 51.8;
```

A query that calls `ST_Intersects` without a bbox filter first reads every
geometry in 55,617,746 rows.

## Row groups

Parts hold 64 to
128 row groups. The largest holds
34,812 rows, which is inside
the 150,000 cap Portolan sets, so range reads stay small.

## Coded columns

Every value below is documented in Overture's schema, and the
meanings are carried in `table:columns` on the collection.

- **`subtype`**: `agriculture`, `aquaculture`, `campground`, `cemetery`, `construction`, `developed`, `education`, `entertainment`, `golf`, `grass`, `horticulture`, `landfill`, and 12 more
- **`class`**: `aboriginal_land`, `airfield`, `allotments`, `animal_keeping`, `aquaculture`, `barracks`, `base`, `beach_resort`, `brownfield`, `bunker`, `camp_site`, `cemetery`, and 97 more
- **`surface`**: `asphalt`, `cobblestone`, `compacted`, `concrete`, `concrete_plates`, `dirt`, `earth`, `fine_gravel`, `grass`, `gravel`, `ground`, `paved`, and 12 more

## Schema and field notes

The collection's `table:columns` carries a description for every documented
column. Those descriptions are harvested from Overture's JSON Schema at tag
`v1.18.0` rather than authored here, so they track upstream.

## Related collections

Every collection in this catalog shares the `id` column convention and the
`bbox` covering column, so the access patterns above apply unchanged. See the
[catalog agent guide](../../AGENTS.md).

## Rendering

The `visual` asset is Overture's prebuilt PMTiles archive for the whole `base`
theme. This collection's features are in the `land_use` layer. Declare
`minzoom` and `maxzoom` on the vector source, or MapLibre requests a tile the
archive does not hold and draws nothing.
