# address

Overture's address collection

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
| Release | `2026-08-19.0` |
| Parts | 32 |
| Rows | 472,797,160 |
| Geometry | Point |
| Columns | 12, 11 with a description |
| Format | GeoParquet 1.1.0, WKB |
| Licence | other |

## Reading it

The data is GeoParquet on a public bucket. No credentials are needed.

```sql
INSTALL spatial; LOAD spatial;
SELECT count(*)
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=addresses/type=address/*.parquet');
```

See [AGENTS.md](AGENTS.md) for join keys, the bbox pruning pattern, and more
queries.

## Where this came from

Overture Maps publishes this data under release `2026-08-19.0`. Column meanings
come from Overture's JSON Schema at tag `v1.18.0`. Both are linked from the
collection metadata as `via` and `canonical`.

Attribution follows [Overture's terms](https://docs.overturemaps.org/attribution/).
