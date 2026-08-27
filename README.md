# Overture Maps Portolan Catalog

This repository maintains a Portolan mirror of Overture Maps release
`2026-08-19.0`. It publishes metadata, documentation, styles, and thumbnails.
The data stays in Overture's public buckets.

The live catalog starts at
<https://nlebovits.github.io/overture-portolan/catalog.json>.

## Use the Catalog

Start with the [catalog README](catalog/README.md) for coverage, licenses, and
provenance. Read the [catalog agent guide](catalog/AGENTS.md) for tested DuckDB
queries, join keys, and data limits.

Each collection also has a README and an agent guide. Those files record its
row count, columns, access paths, and known issues.

## Repository Structure

| Path | Purpose |
|---|---|
| `catalog/` | The complete published catalog |
| `sources/` | Authored and harvested generator inputs |
| `tools/` | Catalog, style, thumbnail, and harvest tools |
| `tests/` | Catalog and remote-data checks |
| `docs/` | Publication and conformance decisions |

The scripts in `tools/` generate `catalog/`. Edit a generator or its input
instead of generated JSON. Never add Overture data files to this repository.

## Verification

Run the pull request gates:

```bash
python3 tests/run_all.py
```

The weekly data pass reads every GeoParquet asset. A separate weekly workflow
runs every SQL block in the 16 published query guides:

```bash
python3 tests/test_agent_queries.py
```

That command needs the DuckDB CLI and network access to Overture's buckets.

## Publication

A push to `main` deploys `catalog/` to GitHub Pages. The site hosts metadata
only. Read [the publication decision](docs/publication.md) before any hosting,
item-shape, or asset-format change.

## License

Apache-2.0 covers this repository's code and metadata. Overture data uses the
licenses listed in the [catalog README](catalog/README.md#license).
