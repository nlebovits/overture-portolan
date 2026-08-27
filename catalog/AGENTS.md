# AGENTS.md — Overture Maps

Guidance for AI agents and automated clients working with this catalog.

**One rule survives every edit to this file.** Every claim here is either quoted
from a source or measured from the data. If you cannot point at where a fact
came from, it does not belong in this file. An agent acting on an invented join
key or an invented column name produces a confident wrong answer, and nothing
downstream catches it.

Every query below was run against the published data on 2026-08-27, and the
output is pasted with it. Timings come from one machine on a home connection, so
treat them as ratios rather than as guarantees.

## What This Catalog Holds

Overture Maps release `2026-08-19.0`, as 15 collections across 6 themes. The
root is <https://nlebovits.github.io/overture-portolan/catalog.json>.

| Theme | Collections |
|---|---|
| `addresses` | `address` |
| `base` | `bathymetry`, `infrastructure`, `land`, `land_cover`, `land_use`, `water` |
| `buildings` | `building`, `building_part` |
| `divisions` | `division`, `division_area`, `division_boundary` |
| `places` | `place` |
| `transportation` | `connector`, `segment` |

Together they hold 4,332,026,224 rows in 987 GeoParquet files, 611.6 GB in
total, measured by listing the release prefix on 2026-08-27. The catalog itself
is 1005 STAC objects: one root, six theme catalogs, 15 collections, and 983
items.

**This catalog holds metadata only.** Every `data` href points at
`overturemaps-us-west-2`, and every `visual` href points at
`overturemaps-extras-us-west-2`. Both are Overture's own buckets on AWS in
`us-west-2`, both are anonymous-readable, and nothing here is a copy. Do not
look for the bytes on the catalog host.

Each part is GeoParquet 1.1.0 with WKB geometry in the column `geometry`. The
GeoParquet metadata declares no `crs`. GeoParquet 1.1.0 states that "if the
field is not provided, the default CRS is `OGC:CRS84`", which is longitude and
latitude on the WGS84 datum. That is EPSG:4326 with axis order east then north.

Five columns are present in all 15 collections: `id`, `geometry`, `bbox`,
`sources`, and `version`. Everything else varies, and `subtype` and `class`
carry different vocabularies in different collections.

Every collection has a per-collection `AGENTS.md` with its own measured row
count, its part count, its coded column values, and its S3 glob. Read that
before you guess a column name from this page.

## How to Read It

The `s3://` glob covers every part of a collection at once, and it needs a
partition-aware reader. DuckDB is one. Anonymous S3 works with no credentials
configured.

```sql
INSTALL spatial; LOAD spatial;

SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division_area/*.parquet');
```

```
[(1074177,)]   -- 2.7s
```

**A glob cannot expand over HTTPS**, because expansion needs a directory
listing, and an HTTPS object store gives none. Over HTTPS, address one part at
a time. Each item in this catalog carries exactly one part, and its `data` asset
gives both forms: the `href` is the HTTPS URL and `alternate.s3.href` is the
`s3://` URL for the same file.

```sql
SELECT count(*) AS rows
FROM read_parquet('https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=divisions/type=division_area/part-00000-f96e181e-fc0f-5b29-a7c1-054128d2640e-c000.zstd.parquet');
```

```
[(138481,)]   -- 1.1s
```

### Four Collections Carry Their Data At Collection Level

`base/bathymetry`, `buildings/building_part`, `divisions/division`, and
`divisions/division_boundary` each hold one part. PTL-COL-001 requires a
single-file collection to carry that file at collection level, so these four
have **no items at all**. Their `data` asset sits on `collection.json`.

An agent that walks `rel="item"` links to find data will find nothing in those
four and will report them as empty. Read the collection's own `assets.data`
first, and fall back to items only when it is absent.

## The Bbox Covering Column Is the Fast Path

Every part carries a GeoParquet 1.1 `bbox` covering column, a struct of `xmin`,
`ymin`, `xmax`, and `ymax`. Each of the four is a plain double with min and max
statistics per row group, verified in the footer of a `division_area` part on
2026-08-27. A filter on them lets the reader skip whole row groups without
decoding a single geometry. `ST_Intersects` alone cannot do that, because the
reader must decode every WKB blob to evaluate it.

**Write the filter as a rectangle overlap test, not as a corner test.** The two
are not the same query, and the difference is silent.

```sql
-- Correct: keeps every feature whose bbox overlaps the window.
SELECT count(*) AS rows
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division_area/*.parquet')
WHERE bbox.xmin <= 0.0 AND bbox.xmax >= -0.2
  AND bbox.ymin <= 51.6 AND bbox.ymax >= 51.4
  AND ST_Intersects(geometry, ST_MakeEnvelope(-0.2, 51.4, 0.0, 51.6));
```

Measured three ways over the same window on `divisions/division_area`,
1,074,177 rows in 8 parts:

```
bbox overlap test, then ST_Intersects: 567 rows in 5.7s
bbox.xmin/ymin BETWEEN, then ST_Intersects: 537 rows in 0.5s
ST_Intersects alone: 567 rows in 85.9s
```

The overlap test gives the same 567 rows as the unfiltered spatial predicate and
runs about 15 times faster. The corner test, which filters `bbox.xmin` and
`bbox.ymin` into the window with `BETWEEN`, drops 30 of those 567. It discards
every feature whose box starts west or south of the window and reaches into it.
It returns quickly and it returns the wrong answer.

The gap widens with collection size. On `buildings/building`, 2,529,582,613
rows in 512 parts, the same overlap filter counted 415,888 features over a
0.2-degree window in 49.6 seconds. The unfiltered `ST_Intersects` over the same
window did not finish in 14 minutes and was killed.

Two consequences follow. Scope every exploratory query to a window before you
run it against a large collection. And prefer a small collection when you only
want to see the shape of the data: `base/bathymetry` holds 59,963 rows and
`divisions/division_boundary` holds 87,533.

## Join Keys

Every feature carries an `id`, a `VARCHAR` unique within a release. Overture's
schema documents it as an identifier in the Global Entity Reference System when
the feature is part of GERS. Four documented references cross collections, and
one is a self-reference.

| From | Column | Type | To | Cardinality |
|---|---|---|---|---|
| `buildings/building_part` | `building_id` | `VARCHAR` | `buildings/building.id` | many parts to one building |
| `divisions/division_area` | `division_id` | `VARCHAR` | `divisions/division.id` | many areas to one division |
| `divisions/division_boundary` | `division_ids` | `VARCHAR[]` | `divisions/division.id` | exactly two, left then right |
| `divisions/division` | `parent_division_id` | `VARCHAR` | `divisions/division.id` | self-reference, null on countries |
| `transportation/segment` | `connectors` | `STRUCT(connector_id VARCHAR, "at" DOUBLE)[]` | `transportation/connector.id` | many connectors per segment |

The `id` side is unique in every row above. The referencing side is not.

`division_boundary.division_ids` is ordered, and the order carries meaning.
Overture's schema states that the first element is the division on the left of
the boundary line and the second is the division on the right, seen by a person
standing on the line and facing the direction the geometry runs. Treating the
array as an unordered set loses that.

`segment.connectors` is a list of structs rather than a list of ids. `at` is the
position along the segment, so `unnest` first and then read `connector_id`.

```sql
WITH seg AS (
  SELECT id, unnest(connectors) AS c
  FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=transportation/type=segment/*.parquet')
  WHERE bbox.xmin <= -0.10 AND bbox.xmax >= -0.12
    AND bbox.ymin <= 51.52 AND bbox.ymax >= 51.50
)
SELECT count(*) AS pairs,
       count(DISTINCT seg.id) AS segments,
       count(DISTINCT k.id) AS connectors
FROM seg
JOIN read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=transportation/type=connector/*.parquet') k
  ON seg.c.connector_id = k.id
WHERE k.bbox.xmin <= -0.10 AND k.bbox.xmax >= -0.12
  AND k.bbox.ymin <= 51.52 AND k.bbox.ymax >= 51.50;
```

```
[(13456, 4635, 6375)]   -- 38.6s
```

Bound both sides of a join by bbox. The join itself has no spatial awareness, so
an unbounded side reads the whole collection.

A cross-collection join on the smaller divisions collections runs in seconds:

```sql
SELECT d.names.primary AS division, a.subtype, a.class
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division_area/*.parquet') a
JOIN read_parquet('s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division/*.parquet') d
  ON a.division_id = d.id
WHERE a.bbox.xmin <= 0.0 AND a.bbox.xmax >= -0.2
  AND a.bbox.ymin <= 51.6 AND a.bbox.ymax >= 51.4
  AND d.bbox.xmin <= 0.0 AND d.bbox.xmax >= -0.2
  AND d.bbox.ymin <= 51.6 AND d.bbox.ymax >= 51.4
ORDER BY division
LIMIT 5;
```

```
('Abbey Estate', 'neighborhood', 'land')
('Abbots Manor Estate', 'neighborhood', 'land')
('Aberfeldy Village', 'neighborhood', 'land')
('Acorn Estate', 'neighborhood', 'land')
('Acorn Walk', 'neighborhood', 'land')
-- 9.7s
```

`places/place` carries an `addresses` column, which Overture's schema describes
as the addresses of the place. It holds address text rather than a foreign key,
so it does not join to `addresses/address.id`. No other documented reference
crosses a theme boundary.

## Column Meanings Are Cited, Not Authored

Every collection carries `table:columns` with a description per column. Those
descriptions are harvested from Overture's JSON Schema at tag
[`v1.18.0`](https://github.com/OvertureMaps/schema/tree/v1.18.0/schema), not
written here, so they track upstream and the tag is recorded.

Of the 234 column descriptions in this catalog, 213 come straight from that
schema. The other 21 cover columns the schema does not describe, because they
are not Overture properties: `bbox`, `geometry`, `id`, `names`, `cartography`,
and a few whose meaning differs per collection. Each of those names its source
in `tools/harvest_schema.py`.

Read `table:columns` on the collection rather than inferring a column's meaning
from its name. Coded columns list their permitted values in the per-collection
`AGENTS.md`.

## Quirks That Produce Silently Wrong Answers

**The corner bbox filter.** Covered above, and it is the trap most likely to
cost you. `bbox.xmin BETWEEN a AND b` is not a window test. Use the four-way
overlap test.

**`base/land_cover` bounding boxes are clamped in this catalog.** Overture
reports longitudes of ±180.00022888183594 for that collection, which falls
outside the WGS84 range STAC requires. This catalog clamps the extent to ±180,
and records every clamp when it builds. The parquet files are untouched, so a
query that reads `bbox.xmax` from the data still sees the out-of-range value.
Compare a longitude against the data rather than against the STAC extent.

**`subtype` and `class` are per-collection vocabularies.** A value that appears
in `base/land` does not mean the same thing in `base/land_use`. Read the coded
values in the collection's own `AGENTS.md` rather than reusing a list from a
sibling.

**Null is common in coded columns.** A `DISTINCT subtype` on
`buildings/building` over a London window returned 14 values on 2026-08-27, and
one of them was `NULL`. Filter it out deliberately rather than by accident.

**Part filenames change on every release.** Overture puts a UUID in each part
name, so every href in this catalog changes when the release does, even when the
schema and the row counts do not. Never cache a part URL across releases. Read
the release from the catalog, which records it as `updated` and in every href.

**Overture keeps few releases.** Listing the release prefix on 2026-08-27
returned exactly two, `2026-07-22.0` and `2026-08-19.0`. An href cached from an
older release points at bytes that are gone.

## Rendering

Each collection's `visual` asset is Overture's prebuilt PMTiles archive for the
whole theme, not for that collection. Six archives cover 15 collections, 573.9
GB in total. The `pmtiles` link on each collection carries `pmtiles:layers` with
the layer name to use, which is the collection id.

The archives are PMTiles v3, confirmed by reading the first bytes of the
`divisions` archive on 2026-08-27: the header magic is `PMTiles` and the spec
version byte is `3`.

**Declare `minzoom` and `maxzoom` on the vector source.** MapLibre otherwise
assumes the archive reaches zoom 22, requests a tile the archive does not hold,
and draws nothing. The failure looks like an empty map rather than an error.
Each collection declares a `default-style` asset at `./styles/default.json`,
which `tools/make_styles.py` generates with both values set on the source.

## Known Limitations

**No `file:size` and no `file:checksum` on upstream assets.** A consumer cannot
verify the integrity of a data file from this catalog alone. The omission is
deliberate: a validator reads every byte of an asset that declares either, which
would turn a conformance check into a 611.6 GB download. Both are a SHOULD under
PORTO-CORE-028. See
[docs/publication.md](https://github.com/nlebovits/overture-portolan/blob/main/docs/publication.md).

**No temporal extent.** Every collection reports a null temporal interval,
because Overture publishes a snapshot rather than a time series. Do not filter
these collections by time.

**Two accepted conformance deviations, PTL-LIV-004 and PTL-LIV-005.** The
publishing host sends no `Access-Control-Expose-Headers` and answers an OPTIONS
preflight with 405. Both concern browser range reads, and nothing on this host
is range-read. The data on Overture's buckets is unaffected. See
[docs/conformance.md](https://github.com/nlebovits/overture-portolan/blob/main/docs/conformance.md).

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here carry no `self` link, so a client tracks its own location.

Each collection carries `describedby` pointing at its README and `agents`
pointing at its agent guide. Follow `agents` first.

## Publication

This catalog is deployed from git to GitHub Pages by
`.github/workflows/pages.yml`. It uses neither `portolan push` nor the catalog
template's `tools/publish.py`, and it uploads nothing to an object store. A
merge to `main` is a deploy, and the deployed state equals the repository state.

Everything under `catalog/` is published and nothing outside it ever is. The
metadata is generated by the scripts in `tools/`, so a fix belongs in the
generator rather than in the JSON.

A workflow checks Overture's STAC root each Monday and opens a pull request when
the release changes. It never pushes to `main`. See
[docs/publication.md](https://github.com/nlebovits/overture-portolan/blob/main/docs/publication.md)
for why this catalog publishes the way it does.

Every `data` and `visual` asset href points at Overture's own buckets rather
than at this host. Those buckets answer range requests and permit cross-origin
reads, so a client reads them directly. This catalog holds metadata only.
