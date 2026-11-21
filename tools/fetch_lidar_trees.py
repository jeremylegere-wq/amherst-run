#!/usr/bin/env python3
"""Find the real trees from the 2020 LiDAR survey and save them as data/lidar_trees.json, so the game's trees stand
where real ones do, at their real heights: woods, tree lines, street trees and yard trees.

    python tools/fetch_lidar_trees.py              # the whole map (about 150 tiles of the 4 m overview, cached)

Method: canopy height = surface model - ground model (NRCan HRDEM, project NS-NSDNR_2020, 4 m overview, Open
Government Licence - Canada). A tree top is a canopy pixel 2.5-40 m up that is strictly higher than all eight of its
neighbours (flat roofs tie with their neighbours and drop out), stands above their average by TOP_RISE, and curves
down in all four directions by CURVE (a roof ridge is level along its length, a crown is not); its crown radius grows
with its height. The game drops tops that fall on a building or a road when it plants them.

Also saved: which COVER_CELL squares the survey covers, so the game knows where to keep its random woods instead
(across the border in New Brunswick there is no survey).

File: {"source", "unit_xy", "unit_h", "x", "y", "h" (zlib + base64 little-endian int16), "cover": {"x0", "y0",
"cell", "nx", "ny", "bits" (zlib + base64, one byte per cell)}}
"""
import argparse
import base64
import json
import os
import sys
import time
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cog  # noqa: E402
import fetch_heights as FH  # noqa: E402

OUT = os.path.join(ROOT, "data", "lidar_trees.json")
LEVEL = 2                 # 4 m overview of the 1 m models
STEP = 4.0                # metres between canopy samples (the overview's pixel)
MIN_H, MAX_H = 2.5, 40.0  # canopy height of a tree top
TOP_RISE = 0.4            # metres a top must stand above the average of its eight neighbours
CURVE = 0.15              # ...and above the middle of each opposite pair (across, along, both diagonals)
BLOCK = 512               # samples per side of a processing block
COVER_CELL = 160.0        # metres: the coverage grid
UNIT_XY, UNIT_H = 0.5, 0.1
SOURCE = ("NRCan HRDEM LiDAR, project NS-NSDNR_2020 (4 m overview of the DSM and DTM), "
          "Open Government Licence - Canada")


def pack(a):
    return base64.b64encode(zlib.compress(np.asarray(a).astype("<i2").tobytes(), 9)).decode("ascii")


def tops(chm):
    """(rows, cols) of tree tops in a canopy height block (NaN = no data)."""
    c = np.nan_to_num(chm, nan=-1.0)
    core = c[1:-1, 1:-1]
    higher = np.ones(core.shape, dtype=bool)
    total = np.zeros(core.shape)
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            if dj == 0 and di == 0:
                continue
            nb = c[1 + dj:c.shape[0] - 1 + dj, 1 + di:c.shape[1] - 1 + di]
            higher &= core > nb
            total += nb
    ok = higher & (core >= MIN_H) & (core <= MAX_H) & (core - total / 8.0 >= TOP_RISE)
    for (aj, ai), (bj, bi) in (((0, -1), (0, 1)), ((-1, 0), (1, 0)), ((-1, -1), (1, 1)), ((-1, 1), (1, -1))):
        a = c[1 + aj:c.shape[0] - 1 + aj, 1 + ai:c.shape[1] - 1 + ai]
        b = c[1 + bj:c.shape[0] - 1 + bj, 1 + bi:c.shape[1] - 1 + bi]
        ok &= core - (a + b) / 2.0 >= CURVE           # a crown falls away every way; a roof ridge stays level along it
    r, k = np.nonzero(ok)
    return r + 1, k + 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", ".lidar_cache"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    with open(args.map) as f:
        meta = json.load(f)["meta"]
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]
    x0, y0, x1, y1 = meta["bounds"]
    dsm = cog.COG(FH.BASE % "dsm", cache_dir=os.path.join(args.cache, "dsm"), name="dsm", level=LEVEL)
    dtm = cog.COG(FH.BASE % "dtm", cache_dir=os.path.join(args.cache, "dtm"), name="dtm", level=LEVEL)
    corners = [[[x0, y0], [x1, y1]]]
    tiles = FH.needed_tiles(corners, dsm, lat0, lon0, margin=STEP * 2)
    print("map %.1f x %.1f km: %d tiles from each model at %d m" % ((x1 - x0) / 1e3, (y1 - y0) / 1e3, len(tiles), STEP))
    FH.prefetch(dsm, tiles, args.workers)
    FH.prefetch(dtm, tiles, args.workers)
    nx, ny = int((x1 - x0) / STEP) + 1, int((y1 - y0) / STEP) + 1
    cnx, cny = int((x1 - x0) / COVER_CELL) + 1, int((y1 - y0) / COVER_CELL) + 1
    seen = np.zeros((cny, cnx))
    valid = np.zeros((cny, cnx))
    xs_all, ys_all, hs_all = [], [], []
    t0 = time.time()
    for bj in range(0, ny, BLOCK - 2):                       # blocks overlap by one sample each side
        for bi in range(0, nx, BLOCK - 2):
            gi = np.arange(bi, min(nx, bi + BLOCK))
            gj = np.arange(bj, min(ny, bj + BLOCK))
            gx, gy = np.meshgrid(x0 + gi * STEP, y0 + gj * STEP)
            X, Y = FH.to_3979(gx.ravel(), gy.ravel(), lat0, lon0)
            chm = (dsm.sample(X, Y) - dtm.sample(X, Y)).reshape(gx.shape)
            ci = ((gx - x0) // COVER_CELL).astype(int)
            cj = ((gy - y0) // COVER_CELL).astype(int)
            np.add.at(seen, (cj, ci), 1)
            np.add.at(valid, (cj, ci), np.isfinite(chm))
            r, k = tops(chm)
            inner = (r > 0) & (k > 0) & (r < chm.shape[0] - 1) & (k < chm.shape[1] - 1)
            r, k = r[inner], k[inner]
            xs_all.append(gx[r, k])
            ys_all.append(gy[r, k])
            hs_all.append(chm[r, k])
        print("  rows %d / %d, %d trees so far (%.0f s)" % (min(ny, bj + BLOCK), ny, sum(len(a) for a in xs_all),
                                                           time.time() - t0), flush=True)
    xs, ys, hs = np.concatenate(xs_all), np.concatenate(ys_all), np.concatenate(hs_all)
    key = np.round(xs / UNIT_XY).astype(np.int64) * 100000 + np.round(ys / UNIT_XY).astype(np.int64)
    _u, first = np.unique(key, return_index=True)                # tops found twice in the block overlaps
    xs, ys, hs = xs[first], ys[first], hs[first]
    cover = (valid / np.maximum(seen, 1)) > 0.5
    doc = {"source": SOURCE, "unit_xy": UNIT_XY, "unit_h": UNIT_H, "count": int(len(xs)),
           "x": pack(np.round(xs / UNIT_XY)), "y": pack(np.round(ys / UNIT_XY)), "h": pack(np.round(hs / UNIT_H)),
           "cover": {"x0": x0, "y0": y0, "cell": COVER_CELL, "nx": cnx, "ny": cny,
                     "bits": base64.b64encode(zlib.compress(cover.astype(np.uint8).tobytes(), 9)).decode("ascii")}}
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print("wrote %s: %d trees, median %.1f m tall, survey covers %.0f%% of the map (%.1f MB)"
          % (OUT, len(xs), float(np.median(hs)), 100.0 * cover.mean(), os.path.getsize(OUT) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
