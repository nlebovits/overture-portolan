#!/usr/bin/env python3
"""Render collection thumbnails with chiitiler against Overture's remote PMTiles.

Nothing is downloaded. chiitiler reads the PMTiles archive over HTTP range
requests, so a 19.8 GB archive costs a few kilobytes to render from.

Framing follows `portolan-thumbnails`. The margin is applied per axis first, so
the aspect is unchanged, then the frame is padded toward 3:2 but never past
MAX_CONTEXT times the data span, then it is clamped to the Mercator world by a
shift rather than a squash.

Gate 1 is the blank probe. A probe render carries the collection's layers with
no basemap, and a blank render carries the background alone. Identical hashes
mean no data landed in the frame. A probe within BLANK_TOLERANCE of the blank's
size means almost none did. Gate 1 replaces a file-size check, which passes any
image chiitiler manages to encode, including a uniform one.

Gate 2 is a human or vision pass over every image. It cannot be automated, and
this script does not pretend otherwise. It prints the framing record that Gate 2
needs.

Three chiitiler details, each of which fails with a useless error:

1. The route is `/clip.png`, not `/clip`.
2. The body is `{"style": {...}}`. A bare style returns `400 invalid stylejson`.
3. The vector source needs a tile template, not a TileJSON `url`. A `url:` fails
   with `render error: Invalid value. at offset 0`.

Usage:
    docker run -d --name chiitiler -p 3000:3000 ghcr.io/kanahiro/chiitiler
    python3 tools/make_thumbnails.py -c divisions/division_area
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
SOURCES = ROOT / "sources"

CHIITILER = "http://localhost:3000"
EARTH_CIRC = 40075016.685578488
MAX_LAT = 85.05112878

# From portolan-thumbnails. The browser card is 350-700 px wide and 250 px tall,
# so 3:2 fills the narrowest column without distortion.
TARGET_ASPECT = 1.5
MARGIN = 0.05
MAX_CONTEXT = 2.5
SIZE = 1024
# The skill probes at 256 for speed. That produces false negatives on sparse
# point layers: a 2.4 px circle survives at 1024 and vanishes at 256, so the
# probe matches the blank and the gate rejects a good image. Measured on
# addresses/address over Amsterdam, which renders 222 KB of address points at
# 1024 and reports FAIL-empty when probed at 256. A render costs about a
# second, so correctness is worth the extra one.
PROBE_SIZE = SIZE
BLANK_TOLERANCE = 1.15
BACKGROUND = "#101418"

# Strategy B, per portolan-thumbnails. A collection lands here when a full
# extent frame renders blank or flat, and each entry records why.
#
# Eight of the fifteen render blank globally. The reason is measurable: the
# layer's own minzoom inside the PMTiles archive, which is not the archive's
# range. A global frame sits near z2, so any layer whose data starts above that
# draws nothing. Read with tools/survey_layers.py.
#
# Each entry is (centre longitude, centre latitude, zoom). The frame is derived
# from the zoom, so it always clears the layer's floor.
WINDOWS: dict[str, tuple[float, float, int]] = {
    # Layer starts at z14. Amsterdam, dense and completely covered.
    "addresses/address": (4.895, 52.370, 16),
    "places/place": (4.895, 52.370, 16),
    # Layer starts at z13.
    "base/infrastructure": (2.343, 48.858, 14),
    "transportation/connector": (2.343, 48.858, 14),
    # Layer starts at z8.
    "buildings/building_part": (4.895, 52.370, 13),
    # Layer starts at z4. Close enough that thinning does not show as holes.
    "buildings/building": (2.343, 48.858, 13),
    "transportation/segment": (2.343, 48.858, 11),
    # Renders globally, but `subtype` is hierarchical, so a global frame shows
    # only `country` and paints one colour.
    "divisions/division_area": (4.0, 50.9, 6),
    # These render globally and read as one grey continent against one grey
    # ocean. The categorical variety is regional, so a region shows it. South
    # Scandinavia and the Baltic carry coast, lakes, rivers, forest, and
    # farmland inside one frame.
    "base/land": (16.0, 59.5, 6),
    "base/water": (17.0, 59.35, 9),
    "base/land_cover": (16.0, 59.5, 6),
    "base/land_use": (16.0, 59.5, 8),
}


def window_bbox(lon: float, lat: float, zoom: int) -> list[float]:
    """A 3:2 frame centred on a point, at the span one zoom level covers.

    The skill's table at SIZE=1024: 78.3 km at z11, 39.1 at z12, 19.6 at z13,
    9.8 at z14. This derives the same figure rather than hard-coding a bbox, so
    a window that renders too coarse is fixed by changing one integer.
    """
    span = EARTH_CIRC * SIZE / (256 * 2**zoom)
    cx, cy = mercator(lon, lat)
    half_w, half_h = span / 2, span / (2 * TARGET_ASPECT)
    lon0, lat0 = unmercator(cx - half_w, cy - half_h)
    lon1, lat1 = unmercator(cx + half_w, cy + half_h)
    return [lon0, lat0, lon1, lat1]


def mercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    x = EARTH_CIRC * lon / 360.0
    y = (
        EARTH_CIRC
        * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        / (2 * math.pi)
    )
    return x, y


def unmercator(x: float, y: float) -> tuple[float, float]:
    lon = x * 360.0 / EARTH_CIRC
    lat = math.degrees(
        2 * math.atan(math.exp(y * 2 * math.pi / EARTH_CIRC)) - math.pi / 2
    )
    return lon, lat


def frame(bbox: list[float]) -> tuple[list[float], dict[str, Any]]:
    """A 3:2 frame around the data, per the portolan-thumbnails algorithm."""
    x0, y0 = mercator(bbox[0], bbox[1])
    x1, y1 = mercator(bbox[2], bbox[3])
    warnings: list[str] = []

    for lo, hi, axis in ((x0, x1, "x"), (y0, y1, "y")):
        if abs(hi - lo) < 1.0:
            warnings.append(f"degenerate-{axis}: span floored at 1 km")

    data_w, data_h = max(x1 - x0, 1000.0), max(y1 - y0, 1000.0)

    # Margin first, per axis, so the aspect does not move.
    x0 -= data_w * MARGIN
    x1 += data_w * MARGIN
    y0 -= data_h * MARGIN
    y1 += data_h * MARGIN

    width, height = x1 - x0, y1 - y0
    if width / height < TARGET_ASPECT:
        pad = (min(height * TARGET_ASPECT, data_w * MAX_CONTEXT) - width) / 2
        if pad > 0:
            x0, x1 = x0 - pad, x1 + pad
    else:
        pad = (min(width / TARGET_ASPECT, data_h * MAX_CONTEXT) - height) / 2
        if pad > 0:
            y0, y1 = y0 - pad, y1 + pad

    # Padding alone cannot reach 3:2 on a worldwide extent. The data already
    # spans the frame, so MAX_CONTEXT caps the growth and the image stays
    # nearly square. base/land and base/water both came out at 1024x868 and
    # 1024x775 before this. Crop the taller axis instead, centred, which is
    # what a world map does anyway. Cropping is not distortion: nothing is
    # stretched, and the discarded band is the emptiest part of the frame.
    width, height = x1 - x0, y1 - y0
    if width / height < TARGET_ASPECT:
        keep = width / TARGET_ASPECT
        centre = (y0 + y1) / 2
        y0, y1 = centre - keep / 2, centre + keep / 2
        warnings.append(f"cropped-y to reach {TARGET_ASPECT}:1")

    # Clamp by shifting, never by squashing.
    half = EARTH_CIRC / 2
    for lo, hi, axis in ((x0, x1, "x"), (y0, y1, "y")):
        span = hi - lo
        if span > EARTH_CIRC:
            warnings.append(f"clamped-{axis}: frame larger than the world")
    if x1 - x0 <= EARTH_CIRC:
        if x0 < -half:
            x1 += -half - x0
            x0 = -half
            warnings.append("shifted-x")
        if x1 > half:
            x0 -= x1 - half
            x1 = half
            warnings.append("shifted-x")
    y0, y1 = max(y0, -half), min(y1, half)

    lon0, lat0 = unmercator(x0, y0)
    lon1, lat1 = unmercator(x1, y1)
    final_w, final_h = x1 - x0, y1 - y0
    report = {
        "aspect": round(final_w / final_h, 2) if final_h else 0,
        "fill": round(min(data_w / final_w, data_h / final_h), 3),
        "warnings": warnings,
    }
    return [lon0, lat0, lon1, lat1], report


def pmtiles_zooms(url: str) -> tuple[int, int]:
    """Zoom range straight from the PMTiles v3 header, bytes 100 and 101."""
    request = urllib.request.Request(url, headers={"Range": "bytes=0-126"})
    with urllib.request.urlopen(request, timeout=60) as response:
        header = response.read()
    if header[:7] != b"PMTiles":
        sys.exit(f"not a PMTiles archive: {url}")
    return header[100], header[101]


def render(style: dict[str, Any], bbox: list[float], size: int) -> bytes:
    body = json.dumps({"style": style}).encode()
    url = (
        f"{CHIITILER}/clip.png"
        f"?bbox={','.join(str(round(v, 6)) for v in bbox)}"
        f"&size={size}&quality=100"
    )
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            if response.status != 200:
                sys.exit(f"chiitiler returned {response.status}")
            return response.read()
    except urllib.error.HTTPError as error:
        sys.exit(f"chiitiler {error.code}: {error.read().decode()[:200]}")
    except urllib.error.URLError as error:
        sys.exit(
            f"chiitiler unreachable at {CHIITILER}: {error}. "
            "Start it with: docker run -d --name chiitiler -p 3000:3000 "
            "ghcr.io/kanahiro/chiitiler"
        )


def probe_styles(style: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The probe and blank styles Gate 1 compares.

    A symbol layer with no glyphs endpoint crashes MapLibre GL Native outright,
    so it is stripped from both.
    """
    layers = [layer for layer in style["layers"] if layer.get("type") != "symbol"]
    probe = {**style, "layers": layers}
    blank = {
        **style,
        "layers": [layer for layer in layers if layer.get("type") == "background"],
    }
    return probe, blank


def gate_one(style: dict[str, Any], bbox: list[float]) -> tuple[str, str]:
    probe_style, blank_style = probe_styles(style)
    probe = render(probe_style, bbox, PROBE_SIZE)
    blank = render(blank_style, bbox, PROBE_SIZE)
    if hashlib.sha256(probe).hexdigest() == hashlib.sha256(blank).hexdigest():
        return "FAIL-empty", "probe is byte-identical to the blank"
    if len(probe) < len(blank) * BLANK_TOLERANCE:
        return (
            "WARN-sparse",
            f"probe {len(probe)}B is within "
            f"{BLANK_TOLERANCE:.0%} of blank {len(blank)}B",
        )
    return "PASS", f"probe {len(probe)}B against blank {len(blank)}B"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--collection", action="append", required=True)
    args = parser.parse_args()

    upstream = json.loads((SOURCES / "upstream.json").read_text())
    records: list[str] = []

    for key in args.collection:
        record = upstream["collections"][key]
        theme, layer = key.split("/", 1)
        directory = CATALOG / theme / layer
        style = json.loads((directory / "styles" / "default.json").read_text())

        minzoom, maxzoom = pmtiles_zooms(record["pmtiles"])
        for source in style["sources"].values():
            source["minzoom"], source["maxzoom"] = minzoom, maxzoom

        window = WINDOWS.get(key)
        strategy = "window" if window else "full-extent"
        if window:
            box, report = (
                window_bbox(*window),
                {
                    "aspect": TARGET_ASPECT,
                    "fill": 1.0,
                    "warnings": [],
                },
            )
        else:
            box, report = frame(record["extent"]["spatial"]["bbox"][0])
        print(
            f"  {key}: bbox={[round(v, 3) for v in box]} "
            f"aspect={report['aspect']} fill={report['fill']} "
            f"zoom={minzoom}-{maxzoom}",
            file=sys.stderr,
        )
        for warning in report["warnings"]:
            print(f"    warn {warning}", file=sys.stderr)

        verdict, detail = gate_one(style, box)

        # The skill budgets three retries per collection. A blank frame on a
        # windowed collection almost always means the frame sits a level or two
        # below where the layer carries data, so step in rather than give up.
        # The layer floor in the archive is where data starts, not where it
        # reads: addresses/address declares z14 and needs z16 to show anything.
        if verdict == "FAIL-empty" and window:
            for step in (1, 2, 3):
                deeper = (window[0], window[1], window[2] + step)
                box = window_bbox(*deeper)
                verdict, detail = gate_one(style, box)
                print(f"    retry at z{deeper[2]}: {verdict}", file=sys.stderr)
                if verdict != "FAIL-empty":
                    print(
                        f"    NOTE: {key} needs z{deeper[2]}, not "
                        f"z{window[2]}. Update WINDOWS.",
                        file=sys.stderr,
                    )
                    window = deeper
                    break

        print(f"    gate 1: {verdict}, {detail}", file=sys.stderr)
        if verdict == "FAIL-empty":
            sys.exit(
                f"{key}: nothing rendered after three retries. Check the "
                "source-layer name, the zoom range, and the bbox."
            )

        image = render(style, box, SIZE)
        (directory / "thumbnail.png").write_bytes(image)
        print(
            f"    wrote {(directory / 'thumbnail.png').relative_to(ROOT)} "
            f"({len(image):,} bytes)",
            file=sys.stderr,
        )
        records.append(
            f"{key}\t{strategy}\t{','.join(str(round(v, 4)) for v in box)}\t"
            f"{minzoom}-{maxzoom}\t{verdict}"
        )

    trail = SOURCES / "framing.tsv"
    trail.write_text(
        "collection\tstrategy\tbbox\tzoom\tgate1\n" + "\n".join(records) + "\n"
    )
    print(
        "\nGate 2 is not automated. Look at every image before you publish.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
