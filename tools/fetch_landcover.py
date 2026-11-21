"""Download the Nova Scotia Topographic Database land cover (treed areas, tree lines, orchards) around Amherst and
convert it to data/landcover.json, which the game turns into real woods.

    python tools/fetch_landcover.py                 # downloads from data.novascotia.ca (needs internet)
    python tools/fetch_landcover.py landcover.json  # or convert a file you already saved (SODA .json or GeoJSON)

Data: Nova Scotia Topographic DataBase - Land Cover (Poly), Service Nova Scotia, dataset xed8-vvg5, licensed under the
Open Government Licence - Nova Scotia. Standard library only.
"""
import json
import math
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PATH = os.path.join(ROOT, "data", "amherst_map.json")
OUT_PATH = os.path.join(ROOT, "data", "landcover.json")
BASE = "https://data.novascotia.ca/resource/xed8-vvg5.json"
MIN_AREA = 150.0          # m2: ignore specks
SIMPLIFY = 3.0            # metres: drop ring vertices closer than this


def download(bounds_ll):
    """All land cover polygons inside the lat/lon box (south, west, north, east), via the Socrata API."""
    s, w, n, e = bounds_ll
    where = "within_box(the_geom, %f, %f, %f, %f)" % (s, w, n, e)
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"$where": where, "$limit": 5000, "$offset": offset})
        with urllib.request.urlopen(BASE + "?" + q, timeout=120) as r:
            page = json.load(r)
        rows += page
        if len(page) < 5000:
            return rows
        offset += 5000


def geometries(doc):
    """Yield (geometry, properties) from a SODA row list or a GeoJSON document."""
    if isinstance(doc, dict) and doc.get("type") == "FeatureCollection":
        for f in doc["features"]:
            yield f["geometry"], f.get("properties", {})
    else:
        for row in doc:
            yield row.get("the_geom"), {k: v for k, v in row.items() if k != "the_geom"}


def to_game(lon, lat, meta):
    r = 6371000.0
    return (math.radians(lon - meta["origin_lon"]) * r * math.cos(math.radians(meta["origin_lat"])),
            -math.radians(lat - meta["origin_lat"]) * r)


def ring_area(ring):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))) / 2.0


def thin(ring):
    out = [ring[0]]
    for p in ring[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= SIMPLIFY:
            out.append(p)
    return out if len(out) >= 3 else ring


def convert(doc, meta):
    woods = []
    for geom, props in geometries(doc):
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for poly in polys:
            rings = []
            for ring in poly:
                pts = [tuple(round(v, 1) for v in to_game(c[0], c[1], meta)) for c in ring[:-1]]
                if len(pts) >= 3:
                    rings.append([list(p) for p in thin(pts)])
            if rings and ring_area(rings[0]) >= MIN_AREA:
                woods.append({"rings": rings})
    return woods


def download_box(meta):
    """(south, west, north, east): the map's whole extent (it grows with tools/extend_map.py), and at least the
    16 x 19 km box around town the first download used."""
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]
    x0, y0, x1, y1 = meta["bounds"]
    k = 180.0 / (math.pi * 6371000.0)
    north, south = lat0 - y0 * k, lat0 - y1 * k
    west, east = lon0 + x0 * k / math.cos(math.radians(lat0)), lon0 + x1 * k / math.cos(math.radians(lat0))
    box = (min(south, lat0 - 0.08), min(west, lon0 - 0.12), max(north, lat0 + 0.08), max(east, lon0 + 0.12))
    print("downloading land cover for %.4f, %.4f - %.4f, %.4f ..." % box)
    return box


def main(argv):
    with open(MAP_PATH) as f:
        meta = json.load(f)["meta"]
    if len(argv) > 1:
        with open(argv[1]) as f:
            doc = json.load(f)
    else:
        doc = download(download_box(meta))
    woods = convert(doc, meta)
    out = {"_about": "Treed areas, tree lines and orchards (NSTDB Land Cover, Open Government Licence - Nova Scotia) in "
                     "game metres. Made by tools/fetch_landcover.py.", "woods": woods}
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    area = sum(ring_area(w["rings"][0]) for w in woods) / 1e4
    print("wrote %s: %d polygons, %.0f hectares" % (OUT_PATH, len(woods), area))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
