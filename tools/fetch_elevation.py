#!/usr/bin/env python3
"""Download real ground heights for the map and save them as data/elevation.json.

    python tools/fetch_elevation.py                  # covers the whole map in data/amherst_map.json
    python tools/fetch_elevation.py --radius 4000    # only 4 km around the spawn point (smaller file)
    python tools/fetch_elevation.py --from-asc dem.asc   # use your own ESRI ASCII grid (lat/lon degrees)

Heights come from the free "Terrarium" terrain tiles on AWS (Mapzen Terrain Tiles; built from NRCan CDEM, SRTM and
other public sources). Needs internet access. The game reads data/elevation.json next to the map; with no file the
world is flat. Re-running overwrites the file. Convert once, no need to repeat it when you rebuild the map.
"""
import argparse
import io
import json
import math
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EARTH_R = 6371000.0
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
USER_AGENT = "amherst-run/0.1 (hobby game; elevation tool)"
ATTRIBUTION = "Elevation: Terrain Tiles on AWS (Mapzen; sources include NRCan CDEM and SRTM)."
UNIT = 0.1                      # file stores heights in tenths of a metre
MAX_NODES = 420000              # keeps the file near 2.5 MB: the step grows for very large maps


# ---------------------------------------------------------------------------- coordinates
def xy_to_latlon(x, y, lat0, lon0):
    """Game metres (x east, y south of the origin) -> latitude, longitude (inverse of the map projection)."""
    return lat0 - math.degrees(y / EARTH_R), lon0 + math.degrees(x / (EARTH_R * math.cos(math.radians(lat0))))


def latlon_to_pixel(lat, lon, z):
    """Global web-mercator pixel position (256 px tiles) of a coordinate at zoom z."""
    n = 256.0 * (1 << z)
    px = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    py = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return px, py


def decode_terrarium(r, g, b):
    """Terrarium encoding: metres = R*256 + G + B/256 - 32768."""
    return r * 256.0 + g + b / 256.0 - 32768.0


# ---------------------------------------------------------------------------- tile source
class TileSource:
    """Bilinear height lookups by latitude/longitude from Terrarium PNG tiles (downloaded once each)."""

    def __init__(self, zoom=13, fetch=None):
        self.zoom = zoom
        self.fetch = fetch or self._http
        self.tiles = {}
        self.downloaded = 0

    @staticmethod
    def _http(url):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    def _tile(self, tx, ty):
        key = (tx, ty)
        t = self.tiles.get(key)
        if t is None:
            import pygame                                   # only for PNG decoding
            data = self.fetch(TILE_URL.format(z=self.zoom, x=tx, y=ty))
            surf = pygame.image.load(io.BytesIO(data))
            rgb = pygame.Surface(surf.get_size(), 0, 24)   # blit, not convert(): convert needs an open window
            rgb.blit(surf, (0, 0))
            raw = pygame.image.tostring(rgb, "RGB")
            t = [decode_terrarium(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
            if len(t) != 256 * 256:
                raise ValueError("unexpected tile size for %s" % (key,))
            self.tiles[key] = t
            self.downloaded += 1
        return t

    def _pixel(self, px, py):
        tx, ty = int(px // 256), int(py // 256)
        return self._tile(tx, ty)[(int(py) - ty * 256) * 256 + (int(px) - tx * 256)]

    def height(self, lat, lon):
        px, py = latlon_to_pixel(lat, lon, self.zoom)
        px, py = px - 0.5, py - 0.5                         # pixel centres
        x0, y0 = math.floor(px), math.floor(py)
        fx, fy = px - x0, py - y0
        a, b = self._pixel(x0, y0), self._pixel(x0 + 1, y0)
        c, d = self._pixel(x0, y0 + 1), self._pixel(x0 + 1, y0 + 1)
        top = a + (b - a) * fx
        return top + (c + (d - c) * fx - top) * fy


def asc_source(path):
    """Height lookups from an ESRI ASCII grid in geographic coordinates (degrees). Returns a height(lat, lon) function."""
    head, rows = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0][0].isalpha():
                head[parts[0].lower()] = float(parts[1])
            else:
                rows.append([float(v) for v in parts])
    n, m = int(head["nrows"]), int(head["ncols"])
    if len(rows) != n or any(len(r) != m for r in rows):
        raise ValueError("%s: grid is not %d x %d" % (path, m, n))
    cell = head.get("cellsize") or head["dx"]
    xll = head.get("xllcorner", head.get("xllcenter", 0.0) - cell / 2)
    yll = head.get("yllcorner", head.get("yllcenter", 0.0) - cell / 2)
    if abs(xll) > 360 or abs(yll) > 90:
        raise ValueError("%s uses projected coordinates; re-export it in latitude/longitude (EPSG:4326)" % path)
    nodata = head.get("nodata_value", -9999.0)

    def height(lat, lon):
        fx, fy = (lon - xll) / cell - 0.5, (yll + n * cell - lat) / cell - 0.5
        i0, j0 = math.floor(fx), math.floor(fy)
        tx, ty = fx - i0, fy - j0

        def at(i, j):
            v = rows[min(max(j, 0), n - 1)][min(max(i, 0), m - 1)]
            return None if v == nodata else v
        vals = [at(i0, j0), at(i0 + 1, j0), at(i0, j0 + 1), at(i0 + 1, j0 + 1)]
        good = [v for v in vals if v is not None]
        if not good:
            return 0.0
        a, b, c, d = [v if v is not None else sum(good) / len(good) for v in vals]
        top = a + (b - a) * tx
        return top + (c + (d - c) * tx - top) * ty
    return height


# ---------------------------------------------------------------------------- grid
def choose_step(width, height, step=25.0, max_nodes=MAX_NODES):
    """The requested step, widened if the area would need more than max_nodes grid points."""
    while (width / step + 1) * (height / step + 1) > max_nodes:
        step *= 1.1
    return round(step, 1)


def build_grid(height_fn, lat0, lon0, bounds, step=25.0, progress=None):
    """Sample height_fn(lat, lon) on a regular game-metre grid covering bounds = (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = bounds
    step = choose_step(x1 - x0, y1 - y0, step)
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    h = []
    for j in range(ny):
        for i in range(nx):
            lat, lon = xy_to_latlon(x0 + i * step, y0 + j * step, lat0, lon0)
            h.append(int(round(height_fn(lat, lon) / UNIT)))
        if progress and j % 40 == 0:
            progress(j, ny)
    return {"step": step, "x0": x0, "y0": y0, "nx": nx, "ny": ny, "unit": UNIT, "h": h,
            "attribution": ATTRIBUTION}


def area_bounds(meta, radius=None):
    """(x0, y0, x1, y1) in game metres: the whole map, or `radius` metres around the spawn point."""
    bx0, by0, bx1, by1 = meta["bounds"]
    if radius:
        sx, sy = meta.get("spawn", [0.0, 0.0])[:2]
        return (max(bx0, sx - radius), max(by0, sy - radius), min(bx1, sx + radius), min(by1, sy + radius))
    return bx0, by0, bx1, by1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"), help="converted map file")
    ap.add_argument("--out", default=None, help="output file (default: elevation.json next to the map)")
    ap.add_argument("--radius", type=float, default=None, help="only this many metres around the spawn point")
    ap.add_argument("--step", type=float, default=25.0, help="grid spacing in metres (default 25)")
    ap.add_argument("--zoom", type=int, default=13, help="tile zoom level (13 is about 13 m per pixel here)")
    ap.add_argument("--from-asc", default=None, metavar="FILE", help="read an ESRI ASCII grid instead of downloading")
    args = ap.parse_args(argv)

    with open(args.map, encoding="utf-8") as f:
        meta = json.load(f)["meta"]
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.map)), "elevation.json")
    bounds = area_bounds(meta, args.radius)
    try:
        src = asc_source(args.from_asc) if args.from_asc else TileSource(args.zoom).height
    except (OSError, ValueError, KeyError) as e:
        print("cannot read %s: %s" % (args.from_asc, e))
        return 1

    t0 = time.time()
    try:
        data = build_grid(src, lat0, lon0, bounds, args.step,
                          progress=lambda j, n: print("  row %d / %d" % (j, n), flush=True))
    except (OSError, ValueError) as e:
        print("elevation download failed: %s" % e)
        print("Check your internet connection, or try --from-asc with your own grid. The game still runs (flat).")
        return 1
    if args.from_asc:
        data["attribution"] = "Elevation: user supplied grid (%s)." % os.path.basename(args.from_asc)
    lo, hi = min(data["h"]) * UNIT, max(data["h"]) * UNIT
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print("wrote %s: %d x %d points every %.0f m, heights %.1f to %.1f m (%.1f s)"
          % (out, data["nx"], data["ny"], data["step"], lo, hi, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
