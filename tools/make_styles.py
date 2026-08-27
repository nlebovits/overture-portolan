#!/usr/bin/env python3
"""Generate MapLibre styles from measured column distributions.

Two rules drive everything here.

**The browser derives a legend only from a `fill` layer whose `fill-color` is a
`match` or `step` array.** An `interpolate` or `case` expression yields no
legend, and line, circle, and symbol layers yield none at all. So a polygon
collection gets its default style from a `match` on a categorical column.

**Every `match` branch is checked against real values first.** A legend listing
ten categories over a map painted one colour is the most common visible defect
in a new catalog. This script queries the distribution and builds the branches
from what came back, so a branch for an absent value cannot be written.

Candidate columns are ranked by how well they split the data. A column where one
value holds almost everything makes a poor default, however many categories it
has: `divisions/division_area.class` is 99.8% `land`, so `subtype` wins with 9
populated categories.

The source is Overture's prebuilt PMTiles, addressed remotely. `minzoom` and
`maxzoom` are declared on the source because MapLibre otherwise assumes zoom 22,
requests a tile the archive does not hold, and draws nothing.

Usage:
    python3 tools/make_styles.py -c divisions/division_area
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
SOURCES = ROOT / "sources"

# Assigned centrally so sibling collections do not all read as the same
# dataset in a card grid. Each is a distinct hue family.
THEME_PALETTES: dict[str, list[str]] = {
    "divisions": [
        "#4c72b0",
        "#dd8452",
        "#55a868",
        "#c44e52",
        "#8172b3",
        "#937860",
        "#da8bc3",
        "#e8c547",
        "#ccb974",
        "#64b5cd",
    ],
    "buildings": [
        "#e8a33d",
        "#c1553b",
        "#7f5539",
        "#b08968",
        "#ddb892",
        "#9c6644",
        "#e6ccb2",
        "#a68a64",
        "#c2a878",
        "#8a6f4a",
    ],
    "transportation": [
        "#2a9d8f",
        "#264653",
        "#e9c46a",
        "#f4a261",
        "#e76f51",
        "#457b9d",
        "#1d3557",
        "#a8dadc",
        "#588157",
        "#3a5a40",
    ],
    "places": [
        "#b5179e",
        "#7209b7",
        "#560bad",
        "#480ca8",
        "#3a0ca3",
        "#3f37c9",
        "#4361ee",
        "#4895ef",
        "#4cc9f0",
        "#f72585",
    ],
    "addresses": [
        "#ff8fa3",
        "#ff4d6d",
        "#c9184a",
        "#a4133c",
        "#800f2f",
        "#590d22",
        "#ffb3c1",
        "#ffccd5",
        "#fff0f3",
        "#e01e5a",
    ],
    "base": [
        "#386641",
        "#6a994e",
        "#a7c957",
        "#bc4749",
        "#f2e8cf",
        "#457b9d",
        "#1d3557",
        "#a8dadc",
        "#e63946",
        "#2b9348",
    ],
}
# Reserved for values outside the match. No palette may contain it, or a
# matched category reads as unmatched.
FALLBACK_COLOR = "#9e9e9e"

BACKGROUND = "#101418"
MIN_CATEGORIES = 3
MAX_CATEGORIES = 10
# A column whose top value holds more than this share splits the data poorly,
# whatever its category count.
MAX_DOMINANCE = 0.90
# The legend shows at most MAX_CATEGORIES branches, and everything else falls
# into one grey bucket. A column whose top branches cover less than this share
# paints most of the map grey, so it is rejected however evenly it spreads.
# `divisions/division_area.country` spreads across ~200 values and fails here;
# `subtype` covers everything with 9.
MIN_COVERAGE = 0.80

# Columns that are identifiers, geometry, or free text rather than categories.
SKIP = {
    "id",
    "geometry",
    "bbox",
    "names",
    "sources",
    "cartography",
    "version",
    "theme",
    "type",
    "wikidata",
    "division_id",
    "parent_division_id",
}


def glob_for(record: dict[str, Any]) -> str:
    return record["items"][0]["s3"].rsplit("/", 1)[0] + "/*.parquet"


def distribution(
    connection: duckdb.DuckDBPyConnection, glob: str, column: str
) -> list[tuple[Any, int]]:
    try:
        return connection.execute(
            f'SELECT "{column}" AS v, count(*) AS n '
            f"FROM read_parquet('{glob}') "
            'WHERE "' + column + '" IS NOT NULL '
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 40"
        ).fetchall()
    except duckdb.Error:
        return []


def pick_column(
    connection: duckdb.DuckDBPyConnection,
    glob: str,
    columns: list[str],
) -> tuple[str, list[tuple[Any, int]]] | None:
    """The categorical column that splits the data best.

    Ranked by the share held outside the top value, so a column that is
    overwhelmingly one value loses to a column that spreads.
    """
    best: tuple[float, str, list[tuple[Any, int]]] | None = None
    for column in columns:
        if column in SKIP:
            continue
        rows = distribution(connection, glob, column)
        rows = [(v, n) for v, n in rows if isinstance(v, str)]
        if not (MIN_CATEGORIES <= len(rows) <= 40):
            continue
        total = connection.execute(
            f"SELECT count(*) FROM read_parquet('{glob}') "
            f'WHERE "{column}" IS NOT NULL'
        ).fetchone()[0]
        if not total:
            continue
        top = rows[:MAX_CATEGORIES]
        dominance = rows[0][1] / total
        coverage = sum(n for _, n in top) / total
        if dominance > MAX_DOMINANCE:
            print(
                f"    skip {column}: top value holds {dominance:.1%}", file=sys.stderr
            )
            continue
        if coverage < MIN_COVERAGE:
            print(
                f"    skip {column}: top {len(top)} cover only {coverage:.1%}",
                file=sys.stderr,
            )
            continue
        score = coverage * (1.0 - dominance)
        if best is None or score > best[0]:
            best = (score, column, top)
    if best is None:
        return None
    return best[1], best[2]


def source_block(record: dict[str, Any], layer: str) -> dict[str, Any]:
    """The remote PMTiles source, with the zoom range declared.

    Without minzoom and maxzoom MapLibre assumes the archive reaches zoom 22,
    asks for a tile that is not there, and renders an empty frame.
    """
    return {
        "type": "vector",
        "tiles": [f"pmtiles://{record['pmtiles']}/{{z}}/{{x}}/{{y}}"],
        "minzoom": record.get("pmtiles_minzoom", 0),
        "maxzoom": record.get("pmtiles_maxzoom", 12),
        "attribution": (
            '<a href="https://overturemaps.org/">Overture Maps</a>, '
            "&copy; OpenStreetMap contributors"
        ),
    }


def categorical_style(
    record: dict[str, Any],
    layer: str,
    column: str,
    values: list[tuple[Any, int]],
    palette: list[str],
    title: str,
) -> dict[str, Any]:
    match: list[Any] = ["match", ["get", column]]
    for index, (value, _) in enumerate(values):
        match.extend([value, palette[index % len(palette)]])
    match.append(FALLBACK_COLOR)

    return {
        "version": 8,
        "name": title,
        "sources": {"overture": source_block(record, layer)},
        "layers": [
            {
                "id": "background",
                "type": "background",
                "paint": {"background-color": BACKGROUND},
            },
            {
                "id": f"{layer}-fill",
                "type": "fill",
                "source": "overture",
                "source-layer": layer,
                "paint": {"fill-color": match, "fill-opacity": 0.85},
            },
            {
                "id": f"{layer}-outline",
                "type": "line",
                "source": "overture",
                "source-layer": layer,
                "paint": {"line-color": BACKGROUND, "line-width": 0.3},
            },
        ],
    }


def flat_style(
    record: dict[str, Any], layer: str, colour: str, title: str
) -> dict[str, Any]:
    return {
        "version": 8,
        "name": title,
        "sources": {"overture": source_block(record, layer)},
        "layers": [
            {
                "id": "background",
                "type": "background",
                "paint": {"background-color": BACKGROUND},
            },
            {
                "id": f"{layer}-fill",
                "type": "fill",
                "source": "overture",
                "source-layer": layer,
                "paint": {"fill-color": colour, "fill-opacity": 0.5},
            },
            {
                "id": f"{layer}-outline",
                "type": "line",
                "source": "overture",
                "source-layer": layer,
                "paint": {"line-color": palette_edge(colour), "line-width": 0.6},
            },
        ],
    }


def palette_edge(colour: str) -> str:
    return "#e8f1f2"


def _assert_palettes_exclude_fallback() -> None:
    for theme, palette in THEME_PALETTES.items():
        if FALLBACK_COLOR in palette:
            raise SystemExit(
                f"{theme} palette contains the fallback colour "
                f"{FALLBACK_COLOR}; a matched category would read as unmatched"
            )


def main() -> int:
    _assert_palettes_exclude_fallback()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--collection", action="append", required=True)
    args = parser.parse_args()

    upstream = json.loads((SOURCES / "upstream.json").read_text())
    connection = duckdb.connect()
    connection.execute("INSTALL spatial; LOAD spatial;")

    for key in args.collection:
        record = upstream["collections"][key]
        theme, layer = key.split("/", 1)
        palette = THEME_PALETTES.get(theme, THEME_PALETTES["base"])
        directory = CATALOG / theme / layer / "styles"
        directory.mkdir(parents=True, exist_ok=True)
        glob = glob_for(record)

        print(f"  {key}: querying distributions", file=sys.stderr)
        picked = pick_column(connection, glob, record["columns"])
        if picked is None:
            sys.exit(
                f"{key}: no categorical column splits the data well enough. "
                "Choose one by hand rather than shipping a flat default."
            )
        column, values = picked
        print(
            f"    default on '{column}': "
            + ", ".join(f"{v} ({n:,})" for v, n in values),
            file=sys.stderr,
        )

        title = f"{layer.replace('_', ' ').title()} by {column}"
        (directory / "default.json").write_text(
            json.dumps(
                categorical_style(record, layer, column, values, palette, title),
                indent=2,
            )
            + "\n"
        )
        (directory / "flat.json").write_text(
            json.dumps(
                flat_style(
                    record,
                    layer,
                    palette[0],
                    f"{layer.replace('_', ' ').title()}, single colour",
                ),
                indent=2,
            )
            + "\n"
        )
        print(f"    wrote {directory.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
