#!/usr/bin/env python3
"""Measure every building's real height and roof shape from LiDAR and save data/building_heights.json.

    python tools/fetch_heights.py                 # all buildings in data/amherst_map.json
    python tools/fetch_heights.py --workers 16    # more parallel downloads

Source: Natural Resources Canada, High Resolution Digital Elevation Model (HRDEM), LiDAR project NS-NSDNR_2020
(1 m, Nova Scotia Dept. of Natural Resources 2020 survey), Open Government Licence - Canada. The 1 m digital surface
model (roofs, trees) minus the digital terrain model (bare ground) gives the height of whatever stands there.

Only the 512 x 512 m tiles under the town's buildings are downloaded (about 250 MB once), from cloud-optimised
GeoTIFFs on AWS, with HTTP range requests; decoded tiles are cached in data/.lidar_cache (not in git), so re-runs are
quick. Needs internet the first time; standard library + numpy only (tools/cog.py reads the files).

How a building is measured
  * OSM outlines are often traced a few metres off; the shift that best lines the outlines up with the LiDAR roofs is
    found per 500 m cell (searched in 1 m steps up to 6 m) and applied before measuring.
  * Height above ground is sampled every 0.5 m inside the footprint (1 m for big buildings).
  * Four-cornered footprints get a roof fitted: height = ridge - drop * (distance from the ridge line) (gable), plus a
    drop towards both ends (hip). Small drops mean a flat roof. Walls are the ridge minus the roof height.
  * Other footprints get one height (the 80th percentile) and a flat roof.
  * Buildings with too little data, or nothing taller than 1.8 m (demolished since OSM was traced), are left out, so
    the game keeps its estimate for them.

File format:
    {"source": ..., "licence": ..., "fields": ["x", "y", "h", "roof", "rh"], "buildings": [[x, y, 6.1, "gable", 2.4], ...]}
x, y = footprint centre in map metres (the key the game matches on, within 3 m), h = wall height, rh = roof height.
"""
import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cog  # noqa: E402

BASE = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-lidar/NS-NSDNR_2020-1m-%s.tif"
SOURCE = "NRCan HRDEM LiDAR, project NS-NSDNR_2020 (1 m DSM - DTM)"
LICENCE = "Contains information licensed under the Open Government Licence - Canada."
EARTH_R = 6371000.0
CELL = 500.0                    # metres: one alignment shift per cell
MAX_SHIFT = 6                   # metres searched each way
MIN_CELL_BUILDINGS = 8
TREE_AREA, TREE_TOP = 250.0, 10.5   # a footprint this small measuring taller than this is almost surely under a tree
FLAT_DROP = 0.7                 # metres: a roof dropping less than this from ridge to eave counts as flat


# ----------------------------------------------------------------------------- geometry helpers
def to_3979(x, y, lat0, lon0):
    """Map metres (x east, y south) -> EPSG:3979 metres, through the map's own projection."""
    lat = lat0 - np.degrees(np.asarray(y, float) / EARTH_R)
    lon = lon0 + np.degrees(np.asarray(x, float) / (EARTH_R * math.cos(math.radians(lat0))))
    return cog.lcc3979(lat, lon)


def inside(px, py, poly):
    """Even-odd point-in-polygon for numpy arrays of points."""
    res = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    for k in range(n):
        x0, y0 = poly[k]
        x1, y1 = poly[(k + 1) % n]
        if y0 == y1:
            continue
        cross = ((y0 > py) != (y1 > py)) & (px < (x1 - x0) * (py - y0) / (y1 - y0) + x0)
        res ^= cross
    return res


def area(poly):
    return abs(sum(poly[k][0] * poly[k - 1][1] - poly[k - 1][0] * poly[k][1] for k in range(len(poly)))) / 2.0


def centre(poly):
    return sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)


def grid_points(poly, step):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    gx, gy = np.meshgrid(np.arange(min(xs) + step / 2, max(xs), step), np.arange(min(ys) + step / 2, max(ys), step))
    gx, gy = gx.ravel(), gy.ravel()
    m = inside(gx, gy, poly)
    return gx[m], gy[m]


def frame(poly):
    """(centre, unit vector along the long side, half length, half width) of a 4-cornered footprint."""
    cx, cy = centre(poly)
    e1 = (poly[1][0] - poly[0][0], poly[1][1] - poly[0][1])
    e2 = (poly[2][0] - poly[1][0], poly[2][1] - poly[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    if l1 >= l2:
        return (cx, cy), (e1[0] / l1, e1[1] / l1), l1 / 2.0, l2 / 2.0
    return (cx, cy), (e2[0] / l2, e2[1] / l2), l2 / 2.0, l1 / 2.0


# ----------------------------------------------------------------------------- roof fitting
def fit_roof(px, py, hag, poly):
    """(wall height, roof kind, roof height, ridge across?) from heights above ground inside a 4-cornered footprint.
    Both ridge directions are tried (along the long side, and across it for cross-gabled houses); the one that fits
    the LiDAR best wins."""
    (cx, cy), (ux, uy), hl, hw = frame(poly)
    if hw < 1.5:
        return None
    fits = [f for f in (_fit_one(px, py, hag, cx, cy, ux, uy, hl, hw, False),
                        _fit_one(px, py, hag, cx, cy, -uy, ux, hw, hl, True)) if f]
    if not fits:
        return None
    pitched = [f for f in fits if f[1] != "flat"]
    best = min(pitched or fits, key=lambda f: f[4])
    return best[0], best[1], best[2], best[3]


def _fit_one(px, py, hag, cx, cy, ux, uy, hl, hw, across):
    """One ridge direction: (wall h, kind, roof h, across, rms error) or None. hl = half length along the ridge."""
    if hw < 1.5:
        return None
    u = (px - cx) * ux + (py - cy) * uy
    v = -(px - cx) * uy + (py - cy) * ux
    fv = np.clip(np.abs(v) / hw, 0, 1)                         # 0 on the ridge line, 1 at the eaves
    fu = np.clip((np.abs(u) - max(0.0, hl - hw)) / hw, 0, 1)   # hip: 0 away from the ends, 1 at the end walls
    ok = np.isfinite(hag) & (hag > 1.2)
    if ok.sum() < 8:
        return None
    best, rms = None, 1e9
    for _round in range(2):                                    # second round drops outliers (trees, chimneys, dormers)
        A = np.stack([np.ones(ok.sum()), fv[ok], fu[ok]], axis=1)
        coef, *_ = np.linalg.lstsq(A, hag[ok], rcond=None)
        res = hag[ok] - A @ coef
        best, rms = coef, float(np.sqrt(np.mean(res * res)))
        keep = np.abs(res) < max(0.8, 2.0 * np.std(res))
        idx = np.flatnonzero(ok)
        ok = ok.copy()
        ok[idx[~keep]] = False
        if ok.sum() < 8:
            break
    ridge, drop_v, drop_u = best[0], -best[1], -best[2]
    if drop_v < FLAT_DROP:
        top = np.nanpercentile(hag[np.isfinite(hag) & (hag > 1.2)], 75)
        return float(top), "flat", 0.0, False, rms
    rh = float(min(drop_v, 0.75 * ridge))
    kind = "hip" if drop_u > 0.5 * drop_v else "gable"
    return float(ridge - rh), kind, rh, across, rms


def measure(poly, shift, dsm, dtm, lat0, lon0):
    """Measured {h, roof, rh} for one building, or None."""
    a = area(poly)
    if a < 15.0:
        return None
    step = 0.5 if a < 2000 else 1.0
    gx, gy = grid_points(poly, step)
    if len(gx) < 10:
        return None
    sx, sy = shift
    X, Y = to_3979(gx + sx, gy + sy, lat0, lon0)
    top, ground = dsm.sample(X, Y), dtm.sample(X, Y)
    valid = np.isfinite(top) & np.isfinite(ground)
    if valid.mean() < 0.6:
        return None
    g = float(np.median(ground[valid]))
    hag = np.where(valid, top - g, np.nan)
    tall = np.nanpercentile(hag, 90)
    if not np.isfinite(tall) or tall < 1.8:
        return None
    out = None
    if len(poly) == 4:
        fit = fit_roof(gx, gy, hag, poly)
        if fit:
            h, kind, rh, across = fit
            if 1.8 <= h + rh <= 70:
                out = {"h": round(max(2.0, h), 1), "roof": kind, "rh": round(rh, 1)}
                if across and kind != "flat":
                    out["across"] = True
    if out is None:
        out = {"h": round(max(2.0, min(70.0, float(np.nanpercentile(hag, 80)))), 1), "roof": "flat", "rh": 0.0}
    if a < TREE_AREA and out["h"] + out["rh"] > TREE_TOP:
        return None                                            # a house under a big tree: the canopy, not the roof
    return out


# ----------------------------------------------------------------------------- alignment
def contrast(blds, shift, dsm, dtm, lat0, lon0):
    """Median height inside footprints minus median height in a 3 m ring outside, with the footprints shifted."""
    ins_x, ins_y, out_x, out_y = [], [], [], []
    for poly in blds:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        gx, gy = np.meshgrid(np.arange(min(xs) - 3, max(xs) + 3, 1.0), np.arange(min(ys) - 3, max(ys) + 3, 1.0))
        gx, gy = gx.ravel(), gy.ravel()
        m = inside(gx, gy, poly)
        ins_x.append(gx[m]); ins_y.append(gy[m]); out_x.append(gx[~m]); out_y.append(gy[~m])
    res = []
    for xs, ys in ((ins_x, ins_y), (out_x, out_y)):
        X, Y = to_3979(np.concatenate(xs) + shift[0], np.concatenate(ys) + shift[1], lat0, lon0)
        res.append(np.nanmedian(dsm.sample(X, Y) - dtm.sample(X, Y)))
    return res[0] - res[1]


def cell_shifts(buildings, dsm, dtm, lat0, lon0, log=print):
    cells = {}
    for poly in buildings:
        cx, cy = centre(poly)
        cells.setdefault((int(cx // CELL), int(cy // CELL)), []).append(poly)
    shifts, found = {}, []
    for key, blds in sorted(cells.items()):
        if len(blds) < MIN_CELL_BUILDINGS:
            continue
        sample = blds[:40]
        coarse = max(((contrast(sample, (dx, dy), dsm, dtm, lat0, lon0), dx, dy)
                      for dx in range(-MAX_SHIFT, MAX_SHIFT + 1, 2) for dy in range(-MAX_SHIFT, MAX_SHIFT + 1, 2)))
        fine = max(((contrast(sample, (coarse[1] + dx, coarse[2] + dy), dsm, dtm, lat0, lon0), coarse[1] + dx, coarse[2] + dy)
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1)))
        shifts[key] = (fine[1], fine[2])
        found.append((fine[1], fine[2]))
    default = (float(np.median([s[0] for s in found])), float(np.median([s[1] for s in found]))) if found else (0.0, 0.0)
    log("alignment: %d cells measured, median shift %+.0f m east, %+.0f m south" % (len(found), default[0], default[1]))
    return shifts, default


# ----------------------------------------------------------------------------- main
def needed_tiles(buildings, grid, lat0, lon0, margin=MAX_SHIFT + 4):
    tiles = set()
    for poly in buildings:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        X, Y = to_3979([min(xs) - margin, max(xs) + margin, min(xs) - margin, max(xs) + margin],
                       [min(ys) - margin, min(ys) - margin, max(ys) + margin, max(ys) + margin], lat0, lon0)
        c0, r0 = grid.pixel(X.min(), Y.max())
        c1, r1 = grid.pixel(X.max(), Y.min())
        for a in range(int(c0) // grid.tw, int(c1) // grid.tw + 1):
            for b in range(int(r0) // grid.th, int(r1) // grid.th + 1):
                tiles.add((a, b))
    return sorted(tiles)


def prefetch(grid, tiles, workers, log=print):
    """Download the tiles in parallel (threads), then decode them in parallel (processes: LZW is pure Python)."""
    from concurrent.futures import ProcessPoolExecutor
    t0 = time.time()
    todo = [t for t in tiles if not grid.cached(*t)]
    raws = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, path in enumerate(ex.map(lambda t: (t, grid.download(*t)), todo), 1):
            if path[1]:
                raws.append(path)
            if k % 20 == 0 or k == len(todo):
                log("  %s: downloaded %d / %d tiles (%.0f MB, %.0f s)" % (grid.name, k, len(todo), grid.bytes_read / 1e6,
                                                                          time.time() - t0))
    if raws:
        with ProcessPoolExecutor() as ex:
            jobs = [ex.submit(cog.decode_file, raw, grid._cache_path(t[0], t[1], "npy"), grid.decode_spec())
                    for t, raw in raws]
            for k, j in enumerate(jobs, 1):
                j.result()
                if k % 20 == 0 or k == len(jobs):
                    log("  %s: decoded %d / %d tiles (%.0f s)" % (grid.name, k, len(jobs), time.time() - t0))


def main(argv=None, open_grid=None, log=print):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--out", default=None, help="output (default: building_heights.json next to the map)")
    ap.add_argument("--cache", default=None, help="tile cache folder (default: .lidar_cache next to the map)")
    ap.add_argument("--workers", type=int, default=8, help="parallel downloads")
    args = ap.parse_args(argv)
    base = os.path.dirname(os.path.abspath(args.map))
    with open(args.map, encoding="utf-8") as f:
        data = json.load(f)
    lat0, lon0 = data["meta"]["origin_lat"], data["meta"]["origin_lon"]
    polys = [b["points"] for b in data["buildings"]]
    cache = args.cache or os.path.join(base, ".lidar_cache")
    if open_grid is None:
        def open_grid(kind):
            return cog.COG(BASE % kind, cache_dir=os.path.join(cache, kind), name=kind)
    dsm, dtm = open_grid("dsm"), open_grid("dtm")
    tiles = needed_tiles(polys, dsm, lat0, lon0)
    log("%d buildings need %d LiDAR tiles from each of the surface and terrain models" % (len(polys), len(tiles)))
    prefetch(dsm, tiles, args.workers, log)
    prefetch(dtm, tiles, args.workers, log)

    shifts, default = cell_shifts(polys, dsm, dtm, lat0, lon0, log)
    out, kinds = [], {}
    t0 = time.time()
    for i, poly in enumerate(polys):
        cx, cy = centre(poly)
        shift = shifts.get((int(cx // CELL), int(cy // CELL)), default)
        m = measure(poly, shift, dsm, dtm, lat0, lon0)
        if m:
            row = [round(cx, 2), round(cy, 2), m["h"], m["roof"], m["rh"]]
            if m.get("across"):
                row.append(1)                                      # optional 6th field: ridge runs across the short side
            out.append(row)
            kinds[m["roof"]] = kinds.get(m["roof"], 0) + 1
        if (i + 1) % 1000 == 0:
            log("  measured %d / %d (%.0f s)" % (i + 1, len(polys), time.time() - t0))
    path = args.out or os.path.join(base, "building_heights.json")
    doc = {"source": SOURCE, "licence": LICENCE, "fields": ["x", "y", "h", "roof", "rh", "across (optional)"],
           "alignment": {"cell": CELL, "median_shift": list(default)}, "buildings": out}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
        f.write("\n")
    tops = sorted(b[2] + b[4] for b in out)
    log("wrote %s: %d of %d buildings measured (%s); top heights median %.1f m, 90%% under %.1f m, tallest %.1f m"
        % (path, len(out), len(polys), ", ".join("%d %s" % (v, k) for k, v in sorted(kinds.items())),
           tops[len(tops) // 2], tops[int(len(tops) * 0.9)], tops[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
