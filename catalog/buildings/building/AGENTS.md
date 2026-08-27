# AGENTS.md — building

Guidance for agents and automated clients reading this collection.

Every claim here is measured from the data or quoted from Overture's published
schema. Nothing is inferred. If you cannot point at where a fact came from, it
does not belong in this file.

## Overview

Overture Maps `buildings` theme, `building` type, release `2026-08-19.0`.
512 GeoParquet parts holding 2,529,582,613 rows. Geometry is WKB in EPSG:4326.

This catalog holds metadata only. Every `data` asset href points at
`overturemaps-us-west-2`, which Overture hosts and which needs no credentials.

## Accessing the data

Read every part at once through the glob. The `s3://` form needs a
partition-aware reader, and DuckDB is one:

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=buildings/type=building/*.parquet');
```

Over plain HTTPS, address one part at a time. A glob cannot expand over HTTPS,
because expansion needs a directory listing:

```sql
SELECT count(*) AS rows
FROM read_parquet('https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=buildings/type=building/part-00000-66390f89-3dae-58d7-a8f9-dd8538b7141a-c000.zstd.parquet');
```

## The bbox column is the fast path

Every part carries a GeoParquet 1.1 `bbox` covering column, verified in the
footer. Filter on it before any spatial predicate. The reader then skips whole
row groups without decoding geometry.

```sql
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=buildings/type=building/*.parquet')
WHERE bbox.xmin BETWEEN -0.6 AND 0.4
  AND bbox.ymin BETWEEN 51.2 AND 51.8;
```

A query that calls `ST_Intersects` without a bbox filter first reads every
geometry in 2,529,582,613 rows.

## Row groups

Parts hold 128 to
256 row groups. The largest holds
57,772 rows, which is inside
the 150,000 cap Portolan sets, so range reads stay small.

## Coded columns

Every value below is documented in Overture's schema, and the
meanings are carried in `table:columns` on the collection.

- **`subtype`**: `agricultural`, `civic`, `commercial`, `education`, `entertainment`, `industrial`, `medical`, `military`, `outbuilding`, `religious`, `residential`, `service`, and 1 more
- **`class`**: `agricultural`, `allotment_house`, `apartments`, `barn`, `beach_hut`, `boathouse`, `bridge_structure`, `bungalow`, `bunker`, `cabin`, `carport`, `cathedral`, and 75 more
- **`facade_material`**: `brick`, `cement_block`, `clay`, `concrete`, `glass`, `metal`, `plaster`, `plastic`, `stone`, `timber_framing`, `wood`
- **`roof_material`**: `concrete`, `copper`, `eternit`, `glass`, `grass`, `gravel`, `metal`, `plastic`, `roof_tiles`, `slate`, `solar_panels`, `thatch`, and 2 more
- **`roof_shape`**: `dome`, `flat`, `gabled`, `gambrel`, `half_hipped`, `hipped`, `mansard`, `onion`, `pyramidal`, `round`, `saltbox`, `sawtooth`, and 2 more
- **`roof_orientation`**: `across`, `along`

## Known issues

Read these before you trust a query against this collection.

- **Most attributes are null, so this collection carries no legend.** Measured over central Paris on release 2026-08-19.0, 354,621 rows: `facade_material` is present on 0.4%, `subtype` on 25.7%, `class` on 25.4%, and `roof_material` on none. No column describes enough of the data to colour a map by, so the default style is a single colour. Filter on an attribute only after you have counted its nulls.

- **The legend comes from a sample.** Style categories were measured over bbox windows rather than a full scan, because a full `GROUP BY` on this collection costs minutes. A sample proves a category is present and never proves one is absent, so a category that occurs only outside those windows is missing from the legend. The windows are in `sources/style_sampling.json`.

## Schema and field notes

The collection's `table:columns` carries a description for every documented
column. Those descriptions are harvested from Overture's JSON Schema at tag
`v1.18.0` rather than authored here, so they track upstream.

## Related collections

Every collection in this catalog shares the `id` column convention and the
`bbox` covering column, so the access patterns above apply unchanged. See the
[catalog agent guide](../../AGENTS.md).

## Rendering

The `visual` asset is Overture's prebuilt PMTiles archive for the whole `buildings`
theme. This collection's features are in the `building` layer. Declare
`minzoom` and `maxzoom` on the vector source, or MapLibre requests a tile the
archive does not hold and draws nothing.
