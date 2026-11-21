#!/usr/bin/env python3
"""Download the surface parking lots (OpenStreetMap amenity=parking areas) for the map and save data/parking.json.

    python tools/fetch_parking.py              # every lot inside the bounds of data/amherst_map.json
    python tools/fetch_parking.py --report     # also list the biggest lots and the driveway roads inside them

The NSRN road data draws the aisles of a big parking lot as a tangle of driveway roads. With the lots known, the game
draws each lot as one open paved area (with painted stalls up close) and tools/map_editor.py --fix-all cuts the
driveway roads back to the lot edge (only the stubs that reach the street stay).

Multi-storey and underground parking are left out (they are buildings, not open ground). Map data (c) OpenStreetMap
contributors (ODbL).

File format:  {"source": ..., "lots": [{"points": [[x, y], ...], "name": "...", "area": m2}, ...]}   x/y in game metres
"""
import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import fetch_osm  # noqa: E402
import osm_to_map  # noqa: E402

MIN_AREA = 250.0          # m2: smaller lots are a few stalls beside a house; the driveway already covers them
OUT = os.path.join(ROOT, "data", "parking.json")


def query(bbox, timeout=120):
    s, w, n, e = bbox
    return (f"[out:xml][timeout:{timeout}];\n"
            f'way["amenity"="parking"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
            f"(._;>;);\nout body;\n")


def area(pts):
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2.0


def lots_from_osm(path, meta):
    """[{"points", "name", "area"}] in map metres from an OSM XML file of parking ways."""
    nodes, ways, _bounds, _tags = osm_to_map.parse_osm(path)
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]
    out = []
    for refs, tags in ways:
        if tags.get("amenity") != "parking" or tags.get("parking") in ("multi-storey", "underground", "rooftop"):
            continue
        if len(refs) < 4 or refs[0] != refs[-1]:
            continue
        pts = [osm_to_map.project(*nodes[r], lat0, lon0) for r in refs[:-1] if r in nodes]
        if len(pts) < 3 or area(pts) < MIN_AREA:
            continue
        lot = {"points": [[round(x, 1), round(y, 1)] for x, y in pts], "area": round(area(pts))}
        if tags.get("name"):
            lot["name"] = tags["name"]
        out.append(lot)
    return out


def map_bbox(meta):
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]
    x0, y0, x1, y1 = meta["bounds"]
    k = 180.0 / (math.pi * 6371000.0)
    return (lat0 - y1 * k, lon0 + x0 * k / math.cos(math.radians(lat0)),
            lat0 - y0 * k, lon0 + x1 * k / math.cos(math.radians(lat0)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--osm", help="use an OSM file you already downloaded instead of asking Overpass")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    with open(args.map) as f:
        data = json.load(f)
    meta = data["meta"]
    path = args.osm
    if not path:
        bbox = map_bbox(meta)
        print("asking Overpass for parking lots in %.4f,%.4f - %.4f,%.4f ..." % bbox, flush=True)
        raw = fetch_osm.download(query(bbox))
        path = os.path.join(ROOT, "data", "parking.osm")           # git-ignored, like the other raw downloads
        with open(path, "wb") as f:
            f.write(raw)
    lots = lots_from_osm(path, meta)
    lots.sort(key=lambda lot: -lot["area"])
    doc = {"source": "OpenStreetMap amenity=parking (surface lots), map data (c) OpenStreetMap contributors, ODbL",
           "lots": lots}
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
        f.write("\n")
    print("wrote %s: %d lots, %.1f ha" % (OUT, len(lots), sum(lot["area"] for lot in lots) / 1e4))
    if args.report:
        from game.mapedits import inside
        for lot in lots[:25]:
            pts = lot["points"]
            inner = [r for r in data["roads"] if r.get("service") in ("driveway", "parking_aisle") and
                     sum(inside(x, y, pts) for x, y in r["points"]) * 2 >= len(r["points"])]
            cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            print("  %6d m2 at (%6.0f, %6.0f) %-28s %d driveway roads mostly inside"
                  % (lot["area"], cx, cy, lot.get("name", ""), len(inner)))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    sys.exit(main())
