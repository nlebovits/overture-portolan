# division_area

Overture's division_area collection

This is a Portolan mirror. Overture Maps produces and hosts the data, and this
catalog adds column documentation, styles, and a thumbnail. No bytes are copied.
Every asset link points at Overture's own buckets.

## What is here

| | |
|---|---|
| Release | `2026-08-19.0` |
| Parts | 8 |
| Rows | 1,074,177 |
| Geometry | MultiPolygon, Polygon |
| Columns | 14, 13 with a description |
| Format | GeoParquet 1.1.0, WKB |
| Licence | ODbL-1.0 |

## Reading it

The data is GeoParquet on a public bucket. No credentials are needed.

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*)
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division_area/*.parquet');
```

Read the [agent guide](AGENTS.md) for join keys, the bbox pruning pattern, and
queries that run.

## Where this came from

Overture Maps publishes this data under release `2026-08-19.0`. Column meanings
come from Overture's JSON Schema at tag `v1.18.0`. Both are linked from the
collection metadata as `via` and `canonical`.

Attribution follows [Overture's terms](https://docs.overturemaps.org/attribution/).
