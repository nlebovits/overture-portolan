# Overture Maps

> **Reading this with an agent?** Start at [AGENTS.md](AGENTS.md). It carries
> the access patterns, the join keys, the bbox filter that makes queries cheap,
> and the traps that produce wrong answers quietly. Every query in it has been
> run against this data. This README is the human summary.

The [Overture Maps Foundation](https://overturemaps.org/) publishes an open map
of the world: buildings, roads, places, addresses, administrative divisions, and
base layers such as water and land cover. This catalog describes release
`2026-08-19.0` of that data as a [Portolan](https://www.portolan-sdi.org/)
catalog.

Overture produces and hosts the data. This catalog holds metadata only. Every
data link points at Overture's own buckets on AWS, so nothing here is a copy.
What this catalog adds is the part Overture leaves out of the files themselves:
what each column means, a style and a thumbnail per collection, and queries that
have been run.

## What Is Here

15 collections across 6 themes, from release `2026-08-19.0`. Every row count
below was measured from the parquet footers on 2026-08-27.

| Theme | Collections | Rows |
|---|---|---|
| [Addresses](addresses/README.md) | address | 472,797,160 |
| [Base](base/README.md) | bathymetry, infrastructure, land, land_cover, land_use, water | 475,845,928 |
| [Buildings](buildings/README.md) | building, building_part | 2,533,921,763 |
| [Divisions](divisions/README.md) | division, division_area, division_boundary | 5,820,410 |
| [Places](places/README.md) | place | 73,631,092 |
| [Transportation](transportation/README.md) | connector, segment | 770,009,871 |

That is 4,332,026,224 rows in 987 GeoParquet files, 611.6 GB in total. Coverage
is global. The data carries no time dimension, so each collection describes the
world as of its release rather than a period.

Each collection has its own README with the row count, the geometry types, the
column count, and a query to start from.

## License

There is no single license. Terms follow the upstream sources Overture draws
on, and they are set out on
[Overture's attribution page](https://docs.overturemaps.org/attribution/). Each
collection carries the identifier that applies to it, and the base theme alone
spans three:

| License | Collections |
|---|---|
| `ODbL-1.0` | all of buildings, divisions, and transportation; base infrastructure, land, land_use, and water |
| `CC-BY-4.0` | base land_cover |
| `CC0-1.0` | base bathymetry |
| `other` | addresses, places |

Addresses and places draw on many sources with different terms, so no single
SPDX identifier fits. Those two collections carry `other` plus a link to
Overture's terms, and a reuser reads that page before redistribution.

Attribution goes to the Overture Maps Foundation and to the upstream sources
Overture names. The `sources` column in every collection records which source
each row came from.

## Provenance

This catalog is a mirror, not an official Overture publication. Overture's own
STAC catalog is at <https://stac.overturemaps.org/catalog.json>, and it is
linked from this catalog as `canonical`. The documentation is at
<https://docs.overturemaps.org/>.

Overture ships a release each month. A workflow in the
[source repository](https://github.com/nlebovits/overture-portolan) checks the
Overture STAC root each Monday and opens a pull request when the release
changes. A person reads the diff before the catalog follows, because a release
can change a column, a license, or a row count.

Column meanings are quoted from Overture's JSON Schema at tag
[`v1.18.0`](https://github.com/OvertureMaps/schema/tree/v1.18.0/schema) rather
than written here. 213 of the 234 column descriptions in this catalog come
straight from that schema. The other 21 cover columns the schema does not
describe, such as `bbox` and `geometry`, and each names its source in
`tools/harvest_schema.py`.

## Access

The data is GeoParquet on a public AWS bucket in `us-west-2`. No account and no
credentials are needed. This query reads one file over HTTPS, and it returned in
1.5 seconds on 2026-08-27. DuckDB reads the file footer, then the `depth` column
alone, and never the geometry.

```sql
INSTALL spatial; LOAD spatial;

SELECT depth, count(*) AS features
FROM read_parquet(
  'https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=base/type=bathymetry/part-00000-cf17cfee-00e5-5871-9cab-7f48d910d28f-c000.zstd.parquet'
)
GROUP BY depth
ORDER BY depth
LIMIT 5;
```

```
┌───────┬──────────┐
│ depth │ features │
│ int32 │  int64   │
├───────┼──────────┤
│     0 │     4284 │
│    10 │     4228 │
│    50 │     4620 │
│   100 │     3877 │
│   500 │     2746 │
└───────┴──────────┘
```

Larger collections span many files, and the `s3://` glob reads them all at once.
[AGENTS.md](AGENTS.md) covers that, along with the bbox filter that keeps a
query on a four-billion-row catalog affordable.

Every collection also has a prebuilt PMTiles archive for map rendering, and a
MapLibre style to draw it with.

## Structure

The catalog root is `catalog.json`, published at
<https://nlebovits.github.io/overture-portolan/catalog.json>. Below it sit six
theme catalogs, 15 collections, and 983 items, one per GeoParquet file. Four
collections hold a single file each and carry it directly, so they have no
items.

The catalog is generated from Overture's STAC and from the parquet footers. The
generator and the tests live in the
[source repository](https://github.com/nlebovits/overture-portolan), which also
takes issues about the metadata. Problems with the data itself belong with
[Overture](https://docs.overturemaps.org/).
