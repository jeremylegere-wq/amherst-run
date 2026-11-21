#!/usr/bin/env python3
"""Rebuild data/elevation.json from the 2020 LiDAR ground model: a finer grid (12.5 m instead of 25 m) with the real
shape of the land: road cuts, the rail embankment, river banks, the drop at the Pumping Station dam.

    python tools/fetch_lidar_ground.py              # same area as the current data/elevation.json, 12.5 m
    python tools/fetch_lidar_ground.py --step 25    # coarser, if a slow machine needs it

Source: NRCan HRDEM, project NS-NSDNR_2020, digital terrain model (bare ground), read from the file's 8 m overview
(tools/cog.py level 3: about 20 tiles for the whole map instead of over a thousand at 1 m). Open Government Licence -
Canada. Where the LiDAR has no data (across the border in New Brunswick) the old heights stay, shifted by the median
difference between the two sources so they meet without a step.

The heights are stored as 0.1 m int16 values, zlib-compressed and base64-encoded ("h16z"), which game/terrain.py reads.
"""
import argparse
import base64
import json
import math
import os
import sys
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import cog  # noqa: E402
import fetch_heights as FH  # noqa: E402

OUT = os.path.join(ROOT, "data", "elevation.json")
LEVEL = 3                 # 8 m overview of the 1 m model
SOURCE = "NRCan HRDEM LiDAR DTM, project NS-NSDNR_2020 (8 m overview), Open Government Licence - Canada"


def encode(heights, unit=0.1):
    q = np.clip(np.round(np.asarray(heights, dtype=np.float64) / unit), -32768, 32767).astype("<i2")
    return base64.b64encode(zlib.compress(q.tobytes(), 9)).decode("ascii")


def decode(text):
    return np.frombuffer(zlib.decompress(base64.b64decode(text)), dtype="<i2")


def build(old, lat0, lon0, step, grid, log=print):
    """(doc, report) for a new elevation document covering the old one's area at `step` metres."""
    x0, y0 = old["x0"], old["y0"]
    x1 = x0 + (old["nx"] - 1) * old["step"]
    y1 = y0 + (old["ny"] - 1) * old["step"]
    nx, ny = int(round((x1 - x0) / step)) + 1, int(round((y1 - y0) / step)) + 1
    xs = x0 + np.arange(nx) * step
    out = np.full((ny, nx), np.nan)
    for j in range(ny):                                          # one row at a time keeps memory small
        y = y0 + j * step
        X, Y = FH.to_3979(xs, np.full(nx, y), lat0, lon0)
        out[j] = grid.sample(X, Y)
        if j % 200 == 0:
            log("  row %d / %d" % (j, ny))
    # the old grid, resampled onto the new nodes (bilinear), for the places the LiDAR does not cover
    unit = old.get("unit", 0.1)
    oh = (decode(old["h16z"]) if "h16z" in old else np.asarray(old["h"])).reshape(old["ny"], old["nx"]) * unit
    gx = (xs - x0) / old["step"]
    prev = np.empty((ny, nx))
    for j in range(ny):
        fy = (y0 + j * step - y0) / old["step"]
        j0 = min(int(fy), old["ny"] - 2)
        ty = fy - j0
        i0 = np.minimum(gx.astype(int), old["nx"] - 2)
        tx = gx - i0
        top = oh[j0, i0] * (1 - tx) + oh[j0, i0 + 1] * tx
        bot = oh[j0 + 1, i0] * (1 - tx) + oh[j0 + 1, i0 + 1] * tx
        prev[j] = top * (1 - ty) + bot * ty
    have = np.isfinite(out)
    shift = float(np.median(out[have] - prev[have])) if have.any() else 0.0
    out[~have] = prev[~have] + shift
    doc = {"step": step, "x0": x0, "y0": y0, "nx": nx, "ny": ny, "unit": unit, "h16z": encode(out.ravel(), unit),
           "previous_shift": round(shift, 2),
           "attribution": SOURCE + "; elsewhere: " + old.get("attribution", "earlier elevation data")}
    report = ("%d x %d nodes at %.1f m, %.0f%% from LiDAR, old heights shifted %+.1f m to match; %.0f to %.0f m"
              % (nx, ny, step, 100.0 * have.mean(), shift, np.nanmin(out), np.nanmax(out)))
    return doc, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--step", type=float, default=12.5)
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", ".lidar_cache", "dtm"))
    args = ap.parse_args(argv)
    with open(args.map) as f:
        meta = json.load(f)["meta"]
    with open(OUT) as f:
        old = json.load(f)
    if "previous" in old:
        old = old["previous"]                                    # always rebuild from the original source
    elif "h" in old:                                             # keep the original grid, compressed
        old = dict(old, h16z=encode(np.asarray(old["h"], dtype=np.float64) * old.get("unit", 0.1), old.get("unit", 0.1)))
        del old["h"]
    grid = cog.COG(FH.BASE % "dtm", cache_dir=args.cache, name="dtm", level=LEVEL)
    doc, report = build(old, meta["origin_lat"], meta["origin_lon"], args.step, grid)
    doc["previous"] = old                                        # the coarse source grid (fallback outside the LiDAR)
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print("wrote %s: %s (%.1f MB)" % (OUT, report, os.path.getsize(OUT) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
