#!/usr/bin/env python3
"""Grow data/amherst_map.json with an extra area, without moving the map's origin (so map edits, heights and
addresses keep lining up).

    python tools/extend_map.py --name hastings_loop --bbox 45.78913 -64.18574 45.85478 -64.11217
    python tools/extend_map.py --reapply            # after a re-download: add every area in data/map_extensions.json

What it does for one area:
  * roads: NSRN street segments inside the box (data/nsrn_<name>.csv, fetched from data.novascotia.ca the first
    time). Pieces that lie on a road the map already has are cut away, so only new road is added; each new piece
    keeps one point on the old road so the road graph joins them (game/roadgraph.py SNAP).
  * buildings, water, parks, trees, signs: OpenStreetMap (Overpass) for the box, converted with the main map's origin.
    A building whose centre is inside one the map already has is skipped.
  * homes: civic points (data/addresses.json) in the box with no building get the house the LiDAR roof surface shows
    there (tools/find_homes.py), since OSM maps few rural buildings.
  * the area is recorded in data/map_extensions.json so --reapply (run by update_map.py) adds it again.

Next steps after extending: python tools/fetch_heights.py (LiDAR heights for the new buildings), then
python tools/map_editor.py --fix-all.
"""
import argparse
import csv
import json
import math
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import fetch_osm  # noqa: E402
import nsrn  # noqa: E402
import osm_to_map  # noqa: E402
from game.mapedits import samples, seg_dist  # noqa: E402

DATA = os.path.join(ROOT, "data")
MAP = os.path.join(DATA, "amherst_map.json")
EXTENSIONS = os.path.join(DATA, "map_extensions.json")
NSRN_API = "https://data.novascotia.ca/resource/484g-adjn.csv"
COVERED = 2.5          # a new road sample this close to an existing road is already on the map
MIN_PIECE = 8.0        # shorter new road pieces are dropped (slivers where two roads meet at a slant)
CELL = 50.0


def fetch_nsrn(bbox, path):
    """NSRN rows intersecting bbox (S, W, N, E), saved with the upper-case headers nsrn.py expects."""
    s, w, n, e = bbox
    poly = "POLYGON((%f %f, %f %f, %f %f, %f %f, %f %f))" % (w, s, e, s, e, n, w, n, w, s)
    q = urllib.parse.urlencode({"$where": "intersects(the_geom, '%s')" % poly, "$limit": "50000"})
    req = urllib.request.Request(NSRN_API + "?" + q, headers={"User-Agent": fetch_osm.USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode("utf-8")
    upper_csv(text.splitlines(), path)


def upper_csv(lines, path):
    rows = list(csv.reader(lines))
    with open(path, "w", newline="", encoding="utf-8") as f:
        out = csv.writer(f)
        out.writerow([h if h == "the_geom" else h.upper() for h in rows[0]])
        out.writerows(rows[1:])
    return len(rows) - 1


class Lines:
    """Grid of polyline segments for fast 'how far to the nearest existing road' checks."""

    def __init__(self, polylines):
        self.grid = {}
        for pts in polylines:
            for a, b in zip(pts, pts[1:]):
                for k in self._cells(a, b):
                    self.grid.setdefault(k, []).append((a[0], a[1], b[0], b[1]))

    def _cells(self, a, b):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        return [(i, j) for i in range(int(math.floor(x0 / CELL)), int(math.floor(x1 / CELL)) + 1)
                for j in range(int(math.floor(y0 / CELL)), int(math.floor(y1 / CELL)) + 1)]

    def dist(self, x, y):
        best = 1e9
        i, j = int(math.floor(x / CELL)), int(math.floor(y / CELL))
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for s in self.grid.get((i + di, j + dj), ()):
                    best = min(best, seg_dist(x, y, *s))
        return best


def new_pieces(points, old, covered=COVERED, min_len=MIN_PIECE):
    """The parts of a polyline that are not already on the map, each with one covered point kept at a cut end."""
    pts = samples(points, 2.0)
    on = [old.dist(x, y) <= covered for x, y in pts]
    pieces, run = [], []
    for k, p in enumerate(pts):
        if not on[k]:
            if not run and k > 0:
                run.append(pts[k - 1])                   # start on the old road
            run.append(p)
        elif run:
            run.append(p)                                # end on the old road
            pieces.append(run)
            run = []
    if run:
        pieces.append(run)
    keep = []
    for run in pieces:
        length = sum(math.dist(a, b) for a, b in zip(run, run[1:]))
        if length >= min_len:
            keep.append([[round(x, 1), round(y, 1)] for x, y in nsrn._simplify(run, 0.8)])
    return keep


def centre(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def inside(x, y, poly):
    hit = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def merge(data, ext):
    """Add the new parts of map `ext` (same origin) to map `data` in place. Returns counts."""
    old = Lines([r["points"] for r in data["roads"]])
    roads = 0
    for r in ext["roads"]:
        for pts in new_pieces(r["points"], old):
            data["roads"].append(dict(r, points=pts))
            roads += 1

    rail_old = Lines([r["points"] for r in data.get("rails", [])])
    for r in ext.get("rails", []):
        for pts in new_pieces(r["points"], rail_old, covered=4.0, min_len=20.0):
            data.setdefault("rails", []).append(dict(r, points=pts))

    grid = {}
    for b in data["buildings"]:
        cx, cy = centre(b["points"])
        grid.setdefault((int(cx // CELL), int(cy // CELL)), []).append(b["points"])
    blds = 0
    for b in ext["buildings"]:
        cx, cy = centre(b["points"])
        i, j = int(cx // CELL), int(cy // CELL)
        near = [p for di in (-1, 0, 1) for dj in (-1, 0, 1) for p in grid.get((i + di, j + dj), ())]
        if any(inside(cx, cy, p) or math.dist((cx, cy), centre(p)) < 1.5 for p in near):
            continue
        data["buildings"].append(b)
        grid.setdefault((i, j), []).append(b["points"])
        blds += 1

    def add_points(key, dmin):
        have = [(p["x"], p["y"]) for p in data.get(key, [])]
        n = 0
        for p in ext.get(key, []):
            if all(math.dist((p["x"], p["y"]), q) > dmin for q in have):
                data.setdefault(key, []).append(p)
                n += 1
        return n

    def add_polys(key):
        have = [centre(p["points"]) for p in data.get(key, [])]
        n = 0
        for p in ext.get(key, []):
            if all(math.dist(centre(p["points"]), q) > 5.0 for q in have):
                data.setdefault(key, []).append(p)
                n += 1
        return n

    counts = {"roads": roads, "buildings": blds, "water": add_polys("water"), "parks": add_polys("parks"),
              "marks": add_points("marks", 2.0), "props": add_points("props", 1.0), "pois": add_points("pois", 2.0),
              "memorials": add_points("memorials", 2.0)}
    allpts = [p for grp in ("roads", "buildings", "rails", "water") for item in data.get(grp, []) for p in item["points"]]
    b = data["meta"]["bounds"]
    data["meta"]["bounds"] = [min(b[0], min(p[0] for p in allpts)), min(b[1], min(p[1] for p in allpts)),
                              max(b[2], max(p[0] for p in allpts)), max(b[3], max(p[1] for p in allpts))]
    return counts


def extension_map(data, name, bbox, log=print):
    """Map data for one extension area, in the main map's coordinates (downloads what is not cached)."""
    csv_path = os.path.join(DATA, "nsrn_%s.csv" % name)
    if not os.path.exists(csv_path):
        log("downloading NSRN roads for %s" % name)
        fetch_nsrn(bbox, csv_path)
    osm_path = os.path.join(DATA, "%s.osm" % name)
    if not os.path.exists(osm_path):
        log("downloading OpenStreetMap for %s" % name)
        raw = fetch_osm.ensure_bounds(fetch_osm.download(fetch_osm.build_query(bbox)), bbox)
        with open(osm_path, "wb") as f:
            f.write(raw)
    m = data["meta"]
    ext = osm_to_map.convert(osm_path, origin=(m["origin_lat"], m["origin_lon"]))
    x0, y0, x1, y1 = box_xy(m, bbox)
    project = lambda lat, lon: osm_to_map.project(lat, lon, m["origin_lat"], m["origin_lon"])   # noqa: E731
    ext["roads"] = nsrn.build_roads(nsrn.read_rows(csv_path), project, (x0, y0, x1, y1),
                                    nsrn.load_overrides(nsrn.DEFAULT_OVERRIDES), margin=0.0)
    return ext


def box_xy(meta, bbox):
    """(x0, y0, x1, y1) map metres of a (S, W, N, E) box."""
    s, w, n, e = bbox
    x0, y1 = osm_to_map.project(s, w, meta["origin_lat"], meta["origin_lon"])
    x1, y0 = osm_to_map.project(n, e, meta["origin_lat"], meta["origin_lon"])
    return x0, y0, x1, y1


def load_extensions():
    if os.path.exists(EXTENSIONS):
        with open(EXTENSIONS) as f:
            return json.load(f)
    return {"_about": "Extra areas added to the map by tools/extend_map.py (re-added by --reapply).", "areas": []}


def extend(path, name, bbox, homes=True, log=print):
    with open(path) as f:
        data = json.load(f)
    counts = merge(data, extension_map(data, name, bbox, log))
    if homes:
        import find_homes
        counts["LiDAR homes and outbuildings"] = find_homes.homes_for(data, box_xy(data["meta"], bbox), log)
    data["meta"].setdefault("extensions", [])
    if name not in data["meta"]["extensions"]:
        data["meta"]["extensions"].append(name)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    log("%s: added %s" % (name, ", ".join("%d %s" % (v, k) for k, v in counts.items() if v)))
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=MAP)
    ap.add_argument("--name", help="short name for the area (file names, map_extensions.json)")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("SOUTH", "WEST", "NORTH", "EAST"))
    ap.add_argument("--reapply", action="store_true", help="add every recorded area again (after a re-download)")
    args = ap.parse_args(argv)
    doc = load_extensions()
    if args.reapply:
        for area in doc["areas"]:
            extend(args.map, area["name"], tuple(area["bbox"]))
        return 0
    if not args.name or not args.bbox:
        ap.error("--name and --bbox are needed (or --reapply)")
    with open(args.map) as f:
        if args.name in json.load(f)["meta"].get("extensions", []):
            raise SystemExit("%s is already in %s" % (args.name, args.map))
    extend(args.map, args.name, tuple(args.bbox))
    doc["areas"] = [a for a in doc["areas"] if a["name"] != args.name] + [{"name": args.name, "bbox": list(args.bbox)}]
    with open(EXTENSIONS, "w") as f:
        json.dump(doc, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
