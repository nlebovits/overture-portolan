# AGENTS.md — Base

The Overture Maps `base` theme, release `2026-08-19.0`.

Collections here:

- `bathymetry`
- `infrastructure`
- `land`
- `land_cover`
- `land_use`
- `water`

Each collection carries its own agent guide with measured row counts, the S3
glob, and the bbox pruning pattern. Read that rather than guessing from this
page.

Access patterns are identical across the theme. Data is GeoParquet in EPSG:4326
on `overturemaps-us-west-2`, readable without credentials, and every part
carries a GeoParquet 1.1 `bbox` covering column.
