#!/usr/bin/env python3
"""Generate MapLibre styles from measured column distributions.

Three rules drive everything here.

**The browser derives a legend only from a `fill` layer whose `fill-color` is a
`match` or `step` array.** An `interpolate` or `case` expression yields no
legend, and line, circle, and symbol layers yield none at all. So a collection
that holds polygons gets a `fill` layer coloured by a `match` on a categorical
column, or by a `step` on an ordered numeric one.

A `fill` layer paints nothing over points or lines. Six of the fifteen
collections hold points or lines alone, so they get a `circle` or `line` layer
instead and no legend. Their colour still comes from the same `match`. Adding a
`fill` layer to force a legend would name colours the map never paints, which
is the defect the legend rule exists to prevent.

**Every branch is checked against real values first.** A legend listing ten
categories over a map painted one colour is the most common visible defect in a
new catalog. Phase 3 below re-queries each branch value and drops any the data
does not hold, so a branch for an absent value cannot be written.

**Every query is scoped to a bbox window.** Overture orders these tables
spatially and every part carries a GeoParquet 1.1 `bbox` covering struct. A
bbox predicate prunes to a few row groups, and `DISTINCT` then answers from the
parquet dictionary pages without decoding values. Measured on
`buildings/building`, 512 parts and 277 GB: a windowed `DISTINCT` returns in
about 7 seconds, while the same query unscoped does not return in four minutes.
The window list also prunes whole parts before the query runs, because each
part's bbox is already in `sources/upstream.json`.

Windowed sampling cannot prove a negative. A category that exists only outside
every window is invisible to this script. The run prints that limit and writes
it to `sources/style_sampling.json` so the catalog can carry it in
`known_issues`. Collections small enough to read whole skip the windows
entirely and get an exact answer instead.

Candidate columns are ranked by how well they split the data. A column where
one value holds almost everything makes a poor default, however many categories
it has: `divisions/division_area.class` is overwhelmingly `land`, so `subtype`
wins with 9 populated categories.

Usage:
    python3 tools/make_styles.py -c divisions/division_area
    python3 tools/make_styles.py -c buildings/building -c places/place
"""

from __future__ import annotations

import argparse
import gzip
import json
import struct
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
SOURCES = ROOT / "sources"

# Spread across the inhabited continents. One window cannot see a category that
# occurs only elsewhere, and each window costs a few seconds, so the cost of
# covering the world this way is small. Five of the seven touch a coast, which
# is what lets the water and land collections find their marine categories.
WINDOWS: dict[str, tuple[float, float, float, float]] = {
    "paris": (2.0, 48.6, 2.7, 49.0),
    "philadelphia": (-75.4, 39.7, -74.9, 40.1),
    "sao_paulo": (-46.9, -23.8, -46.4, -23.4),
    "lagos": (3.1, 6.3, 3.6, 6.7),
    "delhi": (76.9, 28.4, 77.4, 28.8),
    "tokyo": (139.5, 35.5, 140.0, 35.9),
    "sydney": (150.8, -34.1, 151.4, -33.7),
}

# Below this row count a collection is read whole. The answer is then exact and
# the sampling caveat does not apply. Measured: the five collections under this
# mark each screen every column in under a minute, while the smallest above it
# holds 55 million rows.
FULL_SCAN_ROWS = 10_000_000


# These colours come from the Overture styles in the St. Louis Data Browser.
# A category keeps the same meaning across collections. The generator fails if
# measured data introduces an unmapped branch, rather than assigning a colour
# from its row order and silently changing that meaning.
def colour_map(specification: str) -> dict[str, str]:
    return dict(pair.split(":", 1) for pair in specification.split())


CATEGORY_COLOURS: dict[str, dict[str, dict[str, str]]] = {
    "base/infrastructure": {
        "subtype": colour_map(
            "transportation:#9aa3a8 transit:#1e526b barrier:#b0a377 "
            "pedestrian:#538400 power:#e89d07 bridge:#585f63 "
            "waste_management:#b5651d emergency:#c03221 water:#4a9d9c "
            "utility:#7c5295"
        )
    },
    "base/land": {
        "class": colour_map(
            "tree:#538400 tree_row:#6b7f2a wood:#7fb356 forest:#7fb356 "
            "scrub:#adc487 shrub:#adc487 grassland:#95c68f wetland:#8fc6c0 "
            "grass:#95c68f bare_rock:#b6b1a8"
        ),
        "subtype": colour_map(
            "tree:#538400 forest:#7fb356 shrub:#adc487 grass:#95c68f "
            "wetland:#8fc6c0 rock:#b6b1a8 physical:#c9c25e sand:#e0d59f "
            "land:#dfe6ea reef:#4a9d9c"
        ),
    },
    "base/land_cover": {
        "subtype": colour_map(
            "shrub:#adc487 barren:#e0d59f forest:#7fb356 crop:#d6c977 "
            "urban:#d0c4b0 grass:#95c68f wetland:#8fc6c0 mangrove:#4a9d9c"
        )
    },
    "base/land_use": {
        "subtype": colour_map(
            "managed:#b8c9a0 recreation:#7fb356 residential:#e0b394 "
            "park:#538400 agriculture:#d6c977 horticulture:#adc487 "
            "developed:#d0c4b0 education:#e89d07 golf:#95c68f "
            "pedestrian:#c9b970"
        )
    },
    "base/water": {
        "subtype": colour_map(
            "human_made:#c9a0d6 stream:#5591b5 canal:#4a9d9c water:#a8d4e8 "
            "pond:#7fb3d0 river:#1e6f9c reservoir:#8fbdd6 physical:#8fc6c0 "
            "spring:#95d0c8 lake:#2874a6"
        ),
        "class": colour_map(
            "swimming_pool:#c9a0d6 stream:#5591b5 water:#a8d4e8 "
            "drain:#4a9d9c pond:#7fb3d0 river:#1e6f9c ditch:#b0a377 "
            "basin:#8fbdd6 canal:#4a9d9c wastewater:#8b6f47"
        ),
    },
    "divisions/division": {
        "class": colour_map("hamlet:#b7bec2 village:#7fb3d0 town:#e89d07 city:#c03221"),
        "subtype": colour_map(
            "locality:#7fb3d0 neighborhood:#95c68f microhood:#c98bab "
            "macrohood:#a99bd0 county:#e89d07 localadmin:#4a9d9c "
            "region:#5591b5 country:#174054 dependency:#9aa3a8"
        ),
    },
    "divisions/division_area": {
        "subtype": colour_map(
            "locality:#7fb3d0 neighborhood:#95c68f microhood:#c98bab "
            "macrohood:#a99bd0 county:#e89d07 localadmin:#4a9d9c "
            "region:#5591b5 country:#174054 dependency:#9aa3a8"
        )
    },
    "divisions/division_boundary": {
        "subtype": colour_map("county:#e89d07 region:#5591b5 country:#174054")
    },
    "transportation/segment": {
        "class": colour_map(
            "residential:#9aa3a8 service:#c9cfd3 footway:#538400 "
            "tertiary:#b8b83c unclassified:#b7bec2 unknown:#c2c9cd "
            "secondary:#d4b13f primary:#e89d07 path:#6b7f2a steps:#538400"
        )
    },
}

FLAT_COLOURS: dict[str, tuple[str, str]] = {
    "addresses/address": ("#1e526b", "#5591b5"),
    "base/bathymetry": ("#2874a6", "#174054"),
    "base/infrastructure": ("#e89d07", "#7c5295"),
    "base/land": ("#7fb356", "#538400"),
    "base/land_cover": ("#95c68f", "#538400"),
    "base/land_use": ("#e0b394", "#538400"),
    "base/water": ("#2874a6", "#4a9d9c"),
    "buildings/building": ("#b0a377", "#c6dbe8"),
    "buildings/building_part": ("#5591b5", "#2874a6"),
    "divisions/division": ("#e89d07", "#7fb3d0"),
    "divisions/division_area": ("#7fb3d0", "#95c68f"),
    "divisions/division_boundary": ("#174054", "#e89d07"),
    "places/place": ("#c03221", "#d95f38"),
    "transportation/connector": ("#c03221", "#d95f38"),
    "transportation/segment": ("#1e526b", "#9aa3a8"),
}

PREFERRED_COLUMNS = {"base/land": "subtype"}

POINT_RADII = {"division": 4.5}
# A `step` expression paints an ordered quantity, so its colours must read as
# ordered too. A categorical palette here would hide the ordering the column
# carries.
SEQUENTIAL_PALETTE: list[str] = [
    "#dfe6ea",
    "#c9dfe8",
    "#a8d4e8",
    "#8fbdd6",
    "#7fb3d0",
    "#5591b5",
    "#2874a6",
    "#1e6f9c",
    "#1e526b",
    "#174054",
]

# Reserved for values outside the match. No palette may contain it, or a
# matched category reads as unmatched.
FALLBACK_COLOR = "#9e9e9e"

OUTLINE = "#FFFFFF"
MIN_CATEGORIES = 3
MAX_CATEGORIES = 10
# Above this a column is an identifier or free text rather than a legend, and
# no amount of truncation makes it one.
MAX_DISTINCT = 40
# Only the best few candidates earn a GROUP BY. The screening pass is cheap
# because DISTINCT reads dictionary pages; counting is not.
RANK_CANDIDATES = 3
# A column whose top value holds more than this share splits the data poorly,
# whatever its category count.
MAX_DOMINANCE = 0.90
# The legend shows at most MAX_CATEGORIES branches, and everything else falls
# into one grey bucket. A column whose top branches cover less than this share
# paints most of the map grey, so it is rejected however evenly it spreads.
MIN_COVERAGE = 0.80
# A column that is null on most rows describes most of the map as "unknown",
# whatever its values look like. Coverage and dominance both measure the
# non-null rows only, so neither sees this. Measured on buildings/building over
# Paris: `facade_material` is non-null on 0.4% of 354,621 rows, and its top ten
# values then cover 100% of that 0.4%. The picker chose it, and the thumbnail
# came back the fallback grey. A legend that describes fewer than half the
# features is worse than an honest flat colour.
MIN_POPULATED = 0.50

# Columns that are identifiers, geometry, or free text rather than categories.
# Columns that are merely too varied need no entry here: the screening pass
# rejects anything above MAX_DISTINCT on measured cardinality.
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
    "division_ids",
    "parent_division_id",
    "building_id",
    "connector_ids",
    "hierarchies",
    "perspectives",
}


# --------------------------------------------------------------------------
# PMTiles
# --------------------------------------------------------------------------


def _range(url: str, start: int, length: int) -> bytes:
    request = urllib.request.Request(
        url, headers={"Range": f"bytes={start}-{start + length - 1}"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def pmtiles_facts(url: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The zoom range and layer names an archive really holds.

    The v3 header is 127 bytes and puts the minimum zoom at byte 100 and the
    maximum at byte 101. Both go on the style's source, because MapLibre
    otherwise assumes the archive reaches zoom 22, asks for a tile that is not
    there, and renders an empty frame.
    """
    if url in cache:
        return cache[url]
    header = _range(url, 0, 127)
    if header[:7] != b"PMTiles":
        raise SystemExit(f"{url} is not a PMTiles archive")
    offset, length = struct.unpack_from("<QQ", header, 24)
    raw = _range(url, offset, length)
    if header[97] == 2:
        raw = gzip.decompress(raw)
    metadata = json.loads(raw)
    facts = {
        "minzoom": header[100],
        "maxzoom": header[101],
        "layers": [layer["id"] for layer in metadata.get("vector_layers", [])],
    }
    cache[url] = facts
    return facts


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------


def window_predicate(window: tuple[float, float, float, float]) -> str:
    xmin, ymin, xmax, ymax = window
    return (
        f"bbox.xmin < {xmax} AND bbox.xmax > {xmin} "
        f"AND bbox.ymin < {ymax} AND bbox.ymax > {ymin}"
    )


def parts_in(
    record: dict[str, Any], window: tuple[float, float, float, float]
) -> list[str]:
    """The parts whose own bbox meets the window.

    Every part's bbox is already in upstream.json, so most files are discarded
    before DuckDB opens anything. On buildings this turns a 512-file read into
    a one- to four-file read.
    """
    xmin, ymin, xmax, ymax = window
    return [
        item["s3"]
        for item in record["items"]
        if item["bbox"][0] < xmax
        and item["bbox"][2] > xmin
        and item["bbox"][1] < ymax
        and item["bbox"][3] > ymin
    ]


def file_list(paths: list[str]) -> str:
    return "[" + ", ".join(f"'{path}'" for path in paths) + "]"


class Sampler:
    """Every query this script runs, scoped the same way.

    A collection small enough to read whole gets one exhaustive scan and no
    window. Anything larger is queried once per window and the results are
    unioned, which is why `exhaustive` is recorded: it is the difference
    between a fact and a sample.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection, record: dict[str, Any]):
        self.connection = connection
        self.record = record
        self.rows = sum(item["rows"] for item in record["items"])
        self.exhaustive = self.rows <= FULL_SCAN_ROWS
        self._counts: dict[str, list[tuple[Any, int]]] = {}
        self._rows: int | None = None
        if self.exhaustive:
            everything = [item["s3"] for item in record["items"]]
            self.scopes: list[tuple[str, str, str]] = [
                ("all", file_list(everything), "TRUE")
            ]
        else:
            self.scopes = []
            for name, window in WINDOWS.items():
                paths = parts_in(record, window)
                if paths:
                    self.scopes.append(
                        (name, file_list(paths), window_predicate(window))
                    )

    @property
    def window_names(self) -> list[str]:
        return [name for name, _, _ in self.scopes]

    def _each(self, build: Any) -> list[Any]:
        def run(scope: tuple[str, str, str]) -> Any:
            _name, paths, predicate = scope
            cursor = self.connection.cursor()
            try:
                return cursor.execute(build(paths, predicate)).fetchall()
            except duckdb.Error:
                # A struct or list column cannot be grouped or compared. It is
                # not a candidate, and that is the answer, not an error.
                return []
            finally:
                cursor.close()

        with ThreadPoolExecutor(max_workers=max(len(self.scopes), 1)) as pool:
            return list(pool.map(run, self.scopes))

    def distinct(
        self, column: str, limit: int
    ) -> tuple[list[set[str]], list[set[float]]]:
        """Distinct values of one column, one set per scope.

        `LIMIT` lets an identifier column stop early rather than reading the
        whole dictionary. Any column that fills the limit is over
        MAX_DISTINCT and is rejected on that alone.

        The sets stay separate rather than unioned, because the difference
        between them is what tells a category from a location. See `shared`.
        """

        def build(paths: str, predicate: str) -> str:
            return (
                f'SELECT DISTINCT "{column}" FROM read_parquet({paths}) '
                f'WHERE ({predicate}) AND "{column}" IS NOT NULL LIMIT {limit}'
            )

        text: list[set[str]] = []
        numbers: list[set[float]] = []
        for rows in self._each(build):
            window_text: set[str] = set()
            window_numbers: set[float] = set()
            for (value,) in rows:
                if isinstance(value, str):
                    window_text.add(value)
                elif isinstance(value, bool):
                    continue
                elif isinstance(value, int | float):
                    window_numbers.add(float(value))
            text.append(window_text)
            numbers.append(window_numbers)
        return text, numbers

    def counts(self, column: str) -> list[tuple[Any, int]]:
        """Value counts for one column, summed over the scopes.

        Cached, because the fallback pass re-ranks the same columns against
        looser thresholds and must not pay for the same GROUP BY twice.
        """
        if column in self._counts:
            return self._counts[column]

        def build(paths: str, predicate: str) -> str:
            return (
                f'SELECT "{column}" AS v, count(*) AS n FROM read_parquet({paths}) '
                f'WHERE ({predicate}) AND "{column}" IS NOT NULL GROUP BY 1'
            )

        totals: dict[Any, int] = {}
        for rows in self._each(build):
            for value, count in rows:
                totals[value] = totals.get(value, 0) + count
        ordered = sorted(totals.items(), key=lambda pair: -pair[1])
        self._counts[column] = ordered
        return ordered

    def sampled_rows(self) -> int:
        """Rows the sample covers, nulls included.

        `counts` filters nulls, so its total cannot answer how much of the data
        a column actually describes. This is one query per collection, not per
        column, and it is cached.
        """
        if self._rows is None:

            def build(paths: str, predicate: str) -> str:
                return f"SELECT count(*) FROM read_parquet({paths}) WHERE ({predicate})"

            self._rows = sum(rows[0][0] for rows in self._each(build) if rows)
        return self._rows

    def confirm(self, column: str, values: list[Any]) -> set[Any]:
        """The subset of `values` the data actually holds.

        This repeats work phase 1 already did, on purpose. It is the check
        that stops a legend from naming a category the map never paints, so it
        reads the data again rather than trusting the earlier pass.
        """
        if not values:
            return set()
        literals = ", ".join(
            "'" + str(v).replace("'", "''") + "'" if isinstance(v, str) else str(v)
            for v in values
        )

        def build(paths: str, predicate: str) -> str:
            return (
                f'SELECT DISTINCT "{column}" FROM read_parquet({paths}) '
                f'WHERE ({predicate}) AND "{column}" IN ({literals})'
            )

        found: set[Any] = set()
        for rows in self._each(build):
            found.update(value for (value,) in rows if value is not None)
        return found


# --------------------------------------------------------------------------
# Picking
# --------------------------------------------------------------------------


class Candidate:
    def __init__(self, column: str, values: list[tuple[Any, int]], total: int):
        self.column = column
        self.values = values[:MAX_CATEGORIES]
        self.dominance = values[0][1] / total
        self.coverage = sum(count for _, count in self.values) / total
        self.score = self.coverage * (1.0 - self.dominance)
        self.populated = 1.0


def shared(windows: list[set[Any]]) -> int:
    """How many values occur in at least half the windows.

    This is the test that separates a category from a location. Every window
    sits in one country, so `addresses/address.country` looks like a tidy
    seven-value column in the sample while it holds about two hundred values
    worldwide. A legend built from it would name seven countries and paint the
    rest of the world with the fallback colour.

    A real category behaves the other way. `buildings/building.subtype` returns
    almost the same twelve values in every window, because a subtype is a
    property of the building rather than of where the window is.

    One window cannot make the comparison, so an exhaustive read skips it. The
    count is exact there anyway.
    """
    if len(windows) < 2:
        return max((len(w) for w in windows), default=0)
    need = (len(windows) + 1) // 2
    counts: dict[Any, int] = {}
    for window in windows:
        for value in window:
            counts[value] = counts.get(value, 0) + 1
    return sum(1 for hits in counts.values() if hits >= need)


def screen(sampler: Sampler, columns: list[str]) -> tuple[list[str], list[str]]:
    """Phase 1: keep columns whose measured cardinality could be a legend.

    A `DISTINCT` per column, bbox-scoped. Cheap, because it answers from the
    parquet dictionary pages. Returns the survivors ranked so the phase that
    counts rows only has to count a few.

    A column must clear two tests. Its distinct count must fit a legend, and
    enough of its values must recur across windows. `shared` explains the
    second one.
    """
    survivors: list[tuple[int, str]] = []
    numeric: list[tuple[int, str]] = []
    for column in columns:
        if column in SKIP:
            continue
        text_windows, number_windows = sampler.distinct(column, MAX_DISTINCT + 1)
        text = set().union(*text_windows) if text_windows else set()
        numbers = set().union(*number_windows) if number_windows else set()
        if text:
            recurring = shared(text_windows)
            if len(text) > MAX_DISTINCT:
                print(
                    f"    reject {column}: {len(text)}+ distinct values, "
                    "an identifier or free text rather than a legend",
                    file=sys.stderr,
                )
            elif len(text) < MIN_CATEGORIES:
                print(
                    f"    reject {column}: only {len(text)} distinct value(s), "
                    f"fewer than the {MIN_CATEGORIES} a legend needs",
                    file=sys.stderr,
                )
            elif recurring < MIN_CATEGORIES:
                print(
                    f"    reject {column}: only {recurring} of its "
                    f"{len(text)} values recur across windows, so it tracks "
                    "location rather than category",
                    file=sys.stderr,
                )
            else:
                survivors.append((len(text), column))
            continue
        if numbers and MIN_CATEGORIES <= len(numbers) <= MAX_CATEGORIES:
            if shared(number_windows) < MIN_CATEGORIES:
                print(
                    f"    reject {column}: its numeric values do not recur "
                    "across windows, so they track location rather than band",
                    file=sys.stderr,
                )
                continue
            numeric.append((len(numbers), column))
        elif numbers:
            print(
                f"    reject {column}: numeric with {len(numbers)}+ distinct "
                "values, no natural step break",
                file=sys.stderr,
            )
        else:
            print(
                f"    reject {column}: no comparable value in the sample",
                file=sys.stderr,
            )

    # A count at or under MAX_CATEGORIES needs no truncation, so it can reach
    # full coverage. Prefer those, largest first; the rest follow, smallest
    # first, because they lose the least to truncation.
    def rank(entry: tuple[int, str]) -> tuple[int, int]:
        count, _ = entry
        return (0, -count) if count <= MAX_CATEGORIES else (1, count)

    survivors.sort(key=rank)
    numeric.sort(key=rank)
    return [column for _, column in survivors], [column for _, column in numeric]


def measure(
    sampler: Sampler, columns: list[str], relaxed: bool = False
) -> list[Candidate]:
    """Phase 2: count rows for the few survivors, and apply the thresholds.

    `relaxed` drops the two thresholds. It runs only after the strict pass and
    the numeric pass both come back empty, where the choice is no longer
    between a good column and a poor one but between a poor column and no
    legend at all. See `build` for why the poor column wins that.
    """
    ranked: list[Candidate] = []
    for column in columns:
        values = sampler.counts(column)
        values = [(v, n) for v, n in values if isinstance(v, str)]
        total = sum(count for _, count in values)
        if not values or not total:
            if not relaxed:
                print(f"    reject {column}: no rows in the sample", file=sys.stderr)
            continue
        candidate = Candidate(column, values, total)
        sampled = sampler.sampled_rows()
        candidate.populated = total / sampled if sampled else 0.0
        # Not gated on `relaxed`. Dominance and coverage say how good a legend
        # is, and `relaxed` trades a poor legend for none. This says whether a
        # legend describes the data at all. buildings/building carries
        # `facade_material` on 0.1% of rows: the relaxed pass took it, and the
        # thumbnail came back the fallback grey with a legend naming ten
        # materials the reader cannot find.
        if candidate.populated < MIN_POPULATED:
            print(
                f"    reject {column}: null on "
                f"{1 - candidate.populated:.1%} of the sample, so a legend "
                "would describe a minority of the features",
                file=sys.stderr,
            )
            continue
        if not relaxed and candidate.dominance > MAX_DOMINANCE:
            print(
                f"    reject {column}: top value holds "
                f"{candidate.dominance:.1%} of the sample",
                file=sys.stderr,
            )
            continue
        if not relaxed and candidate.coverage < MIN_COVERAGE:
            print(
                f"    reject {column}: top {len(candidate.values)} cover only "
                f"{candidate.coverage:.1%} of the sample",
                file=sys.stderr,
            )
            continue
        ranked.append(candidate)
    ranked.sort(key=lambda entry: -entry.score)
    return ranked


def measure_numeric(
    sampler: Sampler, columns: list[str], relaxed: bool = False
) -> Candidate | None:
    """A numeric column with few enough distinct values to become a `step`.

    Used only where no categorical column survives. `base/bathymetry` is the
    case that needs it: its depth is a coded band with ten values, so a `step`
    gives it both a correct render and a legend, where a flat fill would give
    it neither.
    """
    for column in columns:
        values = sampler.counts(column)
        values = [(v, n) for v, n in values if isinstance(v, int | float)]
        total = sum(count for _, count in values)
        if not values or not total:
            continue
        candidate = Candidate(column, values, total)
        sampled = sampler.sampled_rows()
        candidate.populated = total / sampled if sampled else 0.0
        # The same floor the categorical pass applies. A numeric column is no
        # more descriptive for being numeric: buildings/building has
        # `num_floors_underground` on a small minority of rows, and a step
        # legend over it bands the exceptions and leaves the rest unpainted.
        if candidate.populated < MIN_POPULATED:
            print(
                f"    reject {column}: null on "
                f"{1 - candidate.populated:.1%} of the sample, so a legend "
                "would describe a minority of the features",
                file=sys.stderr,
            )
            continue
        if not relaxed and candidate.dominance > MAX_DOMINANCE:
            print(
                f"    reject {column}: top band holds "
                f"{candidate.dominance:.1%} of the sample",
                file=sys.stderr,
            )
            continue
        candidate.values.sort(key=lambda pair: pair[0])
        return candidate
    return None


# --------------------------------------------------------------------------
# Styles
# --------------------------------------------------------------------------


def source_block(record: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "vector",
        "tiles": [f"pmtiles://{record['pmtiles']}/{{z}}/{{x}}/{{y}}"],
        "minzoom": facts["minzoom"],
        "maxzoom": facts["maxzoom"],
        "attribution": (
            '<a href="https://overturemaps.org/">Overture Maps</a>, '
            "&copy; OpenStreetMap contributors"
        ),
    }


def geometries(record: dict[str, Any]) -> set[str]:
    kinds: set[str] = set()
    for item in record["items"]:
        for name in item["geometry_types"]:
            if "Polygon" in name:
                kinds.add("polygon")
            elif "LineString" in name:
                kinds.add("line")
            elif "Point" in name:
                kinds.add("point")
    return kinds or {"polygon"}


def paint_layers(
    layer: str, record: dict[str, Any], colour: Any, flat: bool
) -> list[dict[str, Any]]:
    """The layers that draw the geometry this collection actually holds.

    A `fill` layer paints nothing over points or lines, so it is written only
    where the data holds polygons. Six of the fifteen collections are points or
    lines alone, and the browser reads a legend from a `fill` layer only, so
    those six get no legend. That is the honest outcome: a `fill` layer added
    to force one would name colours the map never paints. Their `circle` and
    `line` layers still carry the same `match`, because that is the right
    semantics for the data and costs nothing if the browser gains support.

    The `fill` comes first, so lines and points on the mixed collections sit on
    top of it rather than under it.
    """
    kinds = geometries(record)
    layers: list[dict[str, Any]] = []
    if "polygon" in kinds:
        layers.append(
            {
                "id": f"{layer}-fill",
                "type": "fill",
                "source": "overture",
                "source-layer": layer,
                "paint": {
                    "fill-color": colour,
                    "fill-opacity": 0.85,
                },
            }
        )
        layers.append(
            {
                "id": f"{layer}-outline",
                "type": "line",
                "source": "overture",
                "source-layer": layer,
                "filter": ["==", ["geometry-type"], "Polygon"],
                "paint": {
                    "line-color": OUTLINE,
                    # Zero below z6. A vector tile clips every polygon at its
                    # own boundary, so an outline draws that boundary too. At a
                    # global frame the tile grid then covers the map in a
                    # lattice of hairlines, which is what base/land and
                    # base/water rendered before this. The outline earns its
                    # place once features are large enough to have edges the
                    # reader can tell apart from the grid.
                    "line-width": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        5,
                        0,
                        7,
                        0.6 if flat else 0.3,
                    ],
                },
            }
        )
    if "line" in kinds:
        layers.append(
            {
                "id": f"{layer}-line",
                "type": "line",
                "source": "overture",
                "source-layer": layer,
                "filter": ["==", ["geometry-type"], "LineString"],
                "paint": {"line-color": colour, "line-width": 1.1},
            }
        )
    if "point" in kinds:
        layers.append(
            {
                "id": f"{layer}-point",
                "type": "circle",
                "source": "overture",
                "source-layer": layer,
                "filter": ["==", ["geometry-type"], "Point"],
                "paint": {
                    "circle-color": colour,
                    "circle-radius": POINT_RADII.get(layer, 2.4),
                    "circle-opacity": 0.9,
                    "circle-stroke-color": OUTLINE,
                    "circle-stroke-width": 1.1 if layer == "division" else 0.8,
                },
            }
        )
    return layers


def style_document(
    record: dict[str, Any],
    facts: dict[str, Any],
    layer: str,
    colour: Any,
    title: str,
    flat: bool = False,
) -> dict[str, Any]:
    return {
        "version": 8,
        "name": title,
        "sources": {"overture": source_block(record, facts)},
        # The browser composes data styles over its basemap. An opaque
        # background here would hide that context.
        "layers": paint_layers(layer, record, colour, flat),
    }


def match_expression(key: str, column: str, values: list[Any]) -> list[Any]:
    mapping = CATEGORY_COLOURS.get(key, {}).get(column)
    if mapping is None:
        raise SystemExit(f"{key}: no semantic colours defined for '{column}'")
    missing = [str(value) for value in values if str(value) not in mapping]
    if missing:
        raise SystemExit(
            f"{key}: no semantic colour for {column} value(s): {', '.join(missing)}"
        )

    expression: list[Any] = ["match", ["get", column]]
    for value in values:
        expression.extend([value, mapping[str(value)]])
    expression.append(FALLBACK_COLOR)
    return expression


def step_expression(column: str, breaks: list[float], palette: list[str]) -> list[Any]:
    """A `step` over measured breaks.

    The first colour paints everything below the lowest measured value, so the
    remaining breaks are the stops. The browser reads this into a legend the
    same way it reads a `match`.
    """
    expression: list[Any] = ["step", ["get", column], palette[0]]
    for index, value in enumerate(breaks[1:], start=1):
        expression.extend([value, palette[index % len(palette)]])
    return expression


def _assert_palettes_exclude_fallback() -> None:
    palettes: dict[str, list[str]] = {"sequential": SEQUENTIAL_PALETTE}
    palettes.update(
        {f"{key}.flat": list(colours) for key, colours in FLAT_COLOURS.items()}
    )
    for key, columns in CATEGORY_COLOURS.items():
        for column, mapping in columns.items():
            palettes[f"{key}.{column}"] = list(mapping.values())

    for label, palette in palettes.items():
        if FALLBACK_COLOR in palette:
            raise SystemExit(
                f"{label} colours contain the fallback {FALLBACK_COLOR}; "
                "a matched category would read as unmatched"
            )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def human(name: str) -> str:
    return name.replace("_", " ").title()


def graduate_by_zoom(style: dict[str, Any], minzoom: int, maxzoom: int) -> None:
    """Scale the point and line marks with zoom, in place.

    This changes size, never colour. An `interpolate` on `circle-radius` or
    `line-width` cannot affect the legend, because the browser reads the legend
    from `fill-color` alone.
    """
    for layer in style["layers"]:
        if layer["type"] == "circle":
            layer["paint"]["circle-radius"] = [
                "interpolate",
                ["linear"],
                ["zoom"],
                minzoom,
                1.0,
                maxzoom,
                4.0,
            ]
        elif layer["type"] == "line":
            layer["paint"]["line-width"] = [
                "interpolate",
                ["linear"],
                ["zoom"],
                minzoom,
                0.4,
                maxzoom,
                2.4,
            ]


def remove_stale_styles(directory: Path, written: set[str]) -> None:
    """Remove generated styles that the current choice no longer produces."""
    fixed = {"default.json", "flat.json", "zoom.json"}
    for path in directory.glob("*.json"):
        generated = path.name in fixed or path.name.startswith("by_")
        if generated and path.name not in written:
            path.unlink()


def write_flat_only(
    key: str,
    record: dict[str, Any],
    facts: dict[str, Any],
    layer: str,
    palette: list[str],
    sampler: Sampler,
) -> dict[str, Any]:
    """The two styles a collection gets when no column describes its features.

    Both are honest renderings of the same data. The default draws one colour.
    The alternate scales the marks with zoom, which is the difference that
    matters on a collection of hundreds of millions of points.
    """
    theme = key.split("/", 1)[0]
    directory = CATALOG / theme / layer / "styles"
    directory.mkdir(parents=True, exist_ok=True)

    default = style_document(
        record, facts, layer, palette[0], f"{human(layer)}, single colour", flat=True
    )
    (directory / "default.json").write_text(json.dumps(default, indent=2) + "\n")

    graduated = style_document(
        record, facts, layer, palette[1], f"{human(layer)}, scaled by zoom", flat=True
    )
    graduate_by_zoom(graduated, facts["minzoom"], facts["maxzoom"])
    (directory / "zoom.json").write_text(json.dumps(graduated, indent=2) + "\n")

    remove_stale_styles(directory, {"default.json", "zoom.json"})
    print("    wrote default.json, zoom.json", file=sys.stderr)
    return {
        "column": None,
        "expression": "flat",
        "values": [],
        "alternates": ["zoom"],
        "exhaustive": sampler.exhaustive,
        "windows": sampler.window_names,
        "dominance": None,
        "coverage": None,
        "thresholds_relaxed": False,
        "legend": False,
        "pmtiles_minzoom": facts["minzoom"],
        "pmtiles_maxzoom": facts["maxzoom"],
        "dominance_note": None,
        "note": (
            "No column of this collection describes its features. Every "
            "candidate is an identifier, or its values change with location "
            "rather than with the feature. The default draws one colour. This "
            "geometry carries no legend in the browser either way."
        ),
    }


def build(
    key: str,
    record: dict[str, Any],
    connection: duckdb.DuckDBPyConnection,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    theme, layer = key.split("/", 1)
    palette = FLAT_COLOURS[key]
    facts = pmtiles_facts(record["pmtiles"], cache)
    if layer not in facts["layers"]:
        raise SystemExit(
            f"{key}: the archive holds layers {facts['layers']}, not '{layer}'. "
            "A style naming a layer the archive lacks draws nothing."
        )

    sampler = Sampler(connection, record)
    if sampler.exhaustive:
        print(
            f"    scope: every part, no window "
            f"({sampler.rows:,} rows is under the {FULL_SCAN_ROWS:,} mark)",
            file=sys.stderr,
        )
    else:
        print(
            f"    windows: {', '.join(sampler.window_names)} ({sampler.rows:,} rows)",
            file=sys.stderr,
        )

    categorical, numeric = screen(sampler, record["columns"])
    ranked = measure(sampler, categorical[:RANK_CANDIDATES])
    preferred = PREFERRED_COLUMNS.get(key)
    if preferred:
        ranked.sort(key=lambda candidate: candidate.column != preferred)
    numeric_candidate = (
        None if ranked else measure_numeric(sampler, numeric[:RANK_CANDIDATES])
    )

    # Last resort. `divisions/division_boundary` is the collection that needs
    # it: 90.0% of its boundaries are `county`, a hair over MAX_DOMINANCE, and
    # every other column is worse. The thresholds still decide which column
    # wins whenever any column passes them. They only step aside when the
    # alternative is a style with no legend, because a legend that names three
    # real categories and says one of them holds most of the map states a true
    # fact about the data, while a flat fill states nothing. The relaxation is
    # recorded per collection in sources/style_sampling.json rather than
    # applied quietly.
    relaxed = False
    if not ranked and numeric_candidate is None:
        ranked = measure(sampler, categorical[:RANK_CANDIDATES], relaxed=True)
        if ranked:
            relaxed = True
        else:
            numeric_candidate = measure_numeric(
                sampler, numeric[:RANK_CANDIDATES], relaxed=True
            )
            relaxed = numeric_candidate is not None
        if relaxed:
            print(
                "    no column meets the thresholds; falling back to the best "
                "measured column so the style still carries a legend",
                file=sys.stderr,
            )

    if ranked:
        chosen = ranked[0]
        wanted = [value for value, _ in chosen.values]
        confirmed = sampler.confirm(chosen.column, wanted)
        values = [value for value in wanted if value in confirmed]
        missing = [value for value in wanted if value not in confirmed]
        if missing:
            print(
                f"    dropped unverified branches: {', '.join(map(str, missing))}",
                file=sys.stderr,
            )
        if len(values) < MIN_CATEGORIES:
            raise SystemExit(
                f"{key}: only {len(values)} branches of '{chosen.column}' survive "
                "verification, too few for a legend."
            )
        colour = match_expression(key, chosen.column, values)
        column = chosen.column
        kind = "match"
        print(
            f"    default on '{column}' ({kind}), dominance "
            f"{chosen.dominance:.1%}, coverage {chosen.coverage:.1%}",
            file=sys.stderr,
        )
        print(f"    verified branches: {', '.join(map(str, values))}", file=sys.stderr)
    elif numeric_candidate is None:
        # No column describes the feature. `addresses/address` is the case:
        # street, number, unit, and postcode are identifiers, and country
        # tracks the window rather than the address. A polygon collection in
        # this position loses a legend it could have had, so it fails instead.
        # A point or line collection loses nothing, because the browser reads
        # no legend from it either way, so a flat colour is the honest answer.
        if "polygon" in geometries(record):
            # This was a hard failure before MIN_POPULATED existed, on the
            # assumption that some column would always qualify. It does not.
            # buildings/building_part leaves every candidate above 83% null, so
            # no legend can describe the data. That is a fact about Overture's
            # attributes rather than a fault in this generator, and a flat
            # colour states it honestly. The reason goes in known_issues.
            print(
                "    no column describes enough of the data for a legend; "
                "every candidate is mostly null. The default is a flat "
                "colour, and known_issues records why",
                file=sys.stderr,
            )
        else:
            print(
                "    no column describes the feature; the default is a flat "
                "colour, and this geometry carries no legend either way",
                file=sys.stderr,
            )
        return write_flat_only(key, record, facts, layer, palette, sampler)
    else:
        candidate = numeric_candidate
        wanted = [value for value, _ in candidate.values]
        confirmed = sampler.confirm(candidate.column, wanted)
        values = [value for value in wanted if value in confirmed]
        missing = [value for value in wanted if value not in confirmed]
        if missing:
            print(
                f"    dropped unverified breaks: {', '.join(map(str, missing))}",
                file=sys.stderr,
            )
        if len(values) < MIN_CATEGORIES:
            raise SystemExit(
                f"{key}: only {len(values)} breaks of '{candidate.column}' survive "
                "verification, too few for a legend."
            )
        colour = step_expression(candidate.column, values, SEQUENTIAL_PALETTE)
        column = candidate.column
        kind = "step"
        chosen = candidate
        print(
            f"    default on '{column}' ({kind}), dominance {chosen.dominance:.1%}",
            file=sys.stderr,
        )
        print(f"    verified breaks: {', '.join(map(str, values))}", file=sys.stderr)

    directory = CATALOG / theme / layer / "styles"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "default.json").write_text(
        json.dumps(
            style_document(record, facts, layer, colour, f"{human(layer)} by {column}"),
            indent=2,
        )
        + "\n"
    )

    written = ["default.json"]

    # Every collection gets a flat alternate, so there is always a second
    # style to switch to even where only one column earned a legend.
    (directory / "flat.json").write_text(
        json.dumps(
            style_document(
                record,
                facts,
                layer,
                palette[0],
                f"{human(layer)}, single colour",
                flat=True,
            ),
            indent=2,
        )
        + "\n"
    )
    written.append("flat.json")

    alternates: list[str] = []
    for runner in ranked[1:]:
        runner_values = [value for value, _ in runner.values]
        runner_confirmed = sampler.confirm(runner.column, runner_values)
        runner_values = [v for v in runner_values if v in runner_confirmed]
        if len(runner_values) < MIN_CATEGORIES:
            continue
        name = f"by_{runner.column}.json"
        (directory / name).write_text(
            json.dumps(
                style_document(
                    record,
                    facts,
                    layer,
                    match_expression(key, runner.column, runner_values),
                    f"{human(layer)} by {runner.column}",
                ),
                indent=2,
            )
            + "\n"
        )
        written.append(name)
        alternates.append(runner.column)
        print(
            f"    alternate on '{runner.column}': {', '.join(map(str, runner_values))}",
            file=sys.stderr,
        )
    remove_stale_styles(directory, set(written))

    print(f"    wrote {', '.join(written)}", file=sys.stderr)

    return {
        "column": column,
        "expression": kind,
        "values": values,
        "alternates": alternates,
        "exhaustive": sampler.exhaustive,
        "windows": sampler.window_names,
        "dominance": round(chosen.dominance, 4),
        "coverage": round(chosen.coverage, 4),
        "thresholds_relaxed": relaxed,
        # The browser reads a legend from a fill layer only, and a fill layer
        # exists only where the data holds polygons.
        "legend": "polygon" in geometries(record),
        "pmtiles_minzoom": facts["minzoom"],
        "pmtiles_maxzoom": facts["maxzoom"],
        "dominance_note": (
            f"No column met the thresholds. '{column}' was chosen anyway "
            f"because its top value holds {chosen.dominance:.1%} of the "
            "sample, and the alternative was a style with no legend. The map "
            "reads as mostly one colour."
            if relaxed
            else None
        ),
        "note": (
            "Every legend value was read from the whole collection, so the "
            "legend names every category the data holds."
            if sampler.exhaustive
            else (
                "Legend values were sampled inside "
                f"{len(sampler.window_names)} bbox windows "
                f"({', '.join(sampler.window_names)}). Every value named is "
                "present in the data. A category that occurs only outside "
                "every window would not appear in the legend."
            )
        ),
    }


def main() -> int:
    _assert_palettes_exclude_fallback()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--collection", action="append", required=True)
    args = parser.parse_args()

    upstream = json.loads((SOURCES / "upstream.json").read_text())
    connection = duckdb.connect()
    connection.execute("INSTALL httpfs; LOAD httpfs;")
    connection.execute("SET s3_region='us-west-2';")

    report_path = SOURCES / "style_sampling.json"
    report: dict[str, Any] = {}
    if report_path.exists():
        report = json.loads(report_path.read_text())
    report.setdefault("release", upstream["release"])
    report.setdefault("collections", {})

    cache: dict[str, dict[str, Any]] = {}
    for key in args.collection:
        if key not in upstream["collections"]:
            raise SystemExit(f"{key} is not in sources/upstream.json")
        print(f"  {key}", file=sys.stderr)
        report["collections"][key] = build(
            key, upstream["collections"][key], connection, cache
        )

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {report_path.relative_to(ROOT)}", file=sys.stderr)
    sampled = [
        key
        for key, entry in report["collections"].items()
        if not entry["exhaustive"] and entry["values"]
    ]
    if sampled:
        print(
            "Windowed sampling proves a value is present, never that one is "
            "absent. A category outside every window is missing from the "
            f"legends of: {', '.join(sorted(sampled))}. "
            "sources/style_sampling.json carries that note per collection for "
            "known_issues.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
