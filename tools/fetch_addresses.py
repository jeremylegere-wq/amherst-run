#!/usr/bin/env python3
"""Download real civic addresses (house numbers + street names) for the map and save them as data/addresses.json.

    python tools/fetch_addresses.py               # every civic point inside the bounds of data/amherst_map.json
    python tools/fetch_addresses.py --map other.json

Source: Nova Scotia Civic Address File - Civic Points (data.novascotia.ca, dataset tntn-er5g), queried through the
portal's open API with a bounding box, so only the points on the map are fetched (about 7,000 for Amherst, ~0.4 MB
saved). Licence: Open Government Licence - Nova Scotia. Needs internet access. The game reads data/addresses.json next
to the map; without it, parcel jobs make up house numbers as before.

File format:
    {"source": ..., "licence": ..., "fields": ["x", "y", "number", "street"],
     "points": [[x, y, "12A", "Victoria St E"], ...]}       x/y in game metres (x east, y south), like the map
"""
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EARTH_R = 6371000.0
API = "https://data.novascotia.ca/resource/tntn-er5g.json"
SOURCE = "Nova Scotia Civic Address File - Civic Points (data.novascotia.ca, tntn-er5g)"
LICENCE = "Contains information licensed under the Open Government Licence - Nova Scotia."
USER_AGENT = "amherst-run/0.1 (hobby game; address tool)"
PAGE = 5000


def xy_to_latlon(x, y, lat0, lon0):
    """Game metres -> latitude, longitude (inverse of tools/osm_to_map.project)."""
    return lat0 - math.degrees(y / EARTH_R), lon0 + math.degrees(x / (EARTH_R * math.cos(math.radians(lat0))))


def latlon_to_xy(lat, lon, lat0, lon0):
    """Same equirectangular projection as tools/osm_to_map.project."""
    return (math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0)),
            -math.radians(lat - lat0) * EARTH_R)


def street_of(row):
    """'Victoria St E' from the NSCAF street parts (prefix, name, suffix, direction)."""
    parts = [row.get(k, "").strip() for k in ("strprefix", "strname", "strsuffix", "strdir")]
    return " ".join(p for p in parts if p)


def number_of(row):
    """'12' or '12A' (civic number + suffix). Unit numbers are left out: one drop point per building."""
    num = str(row.get("civicnum", "")).strip()
    if num.endswith(".0"):
        num = num[:-2]
    return num + str(row.get("civsuffix", "")).strip()


def convert(rows, lat0, lon0):
    """API rows -> sorted, de-duplicated [[x, y, number, street], ...]."""
    seen, out = set(), []
    for r in rows:
        try:
            lat, lon = float(r["lat"]), float(r["long"])
        except (KeyError, TypeError, ValueError):
            continue
        num, street = number_of(r), street_of(r)
        if not num or not street:
            continue
        key = (num, street)
        if key in seen:                     # several units at one address: keep the first point
            continue
        seen.add(key)
        x, y = latlon_to_xy(lat, lon, lat0, lon0)
        out.append([round(x, 1), round(y, 1), num, street])
    out.sort(key=lambda p: (p[3], p[1], p[0]))
    return out


def query_url(bbox, offset):
    """Socrata query for the civic points in bbox = (south, west, north, east), one page."""
    s, w, n, e = bbox
    params = {
        "$select": "civicnum,civsuffix,strprefix,strname,strsuffix,strdir,lat,long",
        "$where": "within_box(the_geom,%.6f,%.6f,%.6f,%.6f)" % (n, w, s, e),     # NW corner then SE corner
        "$order": "pntid",
        "$limit": str(PAGE),
        "$offset": str(offset),
    }
    return API + "?" + urllib.parse.urlencode(params)


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_rows(bbox, fetch=http_json):
    rows, offset = [], 0
    while True:
        page = fetch(query_url(bbox, offset))
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        offset += PAGE


def map_bbox(meta):
    """(south, west, north, east) covering the map's bounds."""
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]
    x0, y0, x1, y1 = meta["bounds"]
    n, w = xy_to_latlon(x0, y0, lat0, lon0)
    s, e = xy_to_latlon(x1, y1, lat0, lon0)
    return s, w, n, e


def main(argv=None, fetch=http_json):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"), help="converted map file")
    ap.add_argument("--out", default=None, help="output file (default: addresses.json next to the map)")
    args = ap.parse_args(argv)
    with open(args.map, encoding="utf-8") as f:
        meta = json.load(f)["meta"]
    bbox = map_bbox(meta)
    print("asking data.novascotia.ca for civic points in %.4f,%.4f - %.4f,%.4f ..." % bbox, flush=True)
    rows = fetch_rows(bbox, fetch)
    pts = convert(rows, meta["origin_lat"], meta["origin_lon"])
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.map)), "addresses.json")
    doc = {"source": SOURCE, "licence": LICENCE, "fields": ["x", "y", "number", "street"], "points": pts}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
        f.write("\n")
    streets = len({p[3] for p in pts})
    print("wrote %s: %d addresses on %d streets (from %d points)" % (out, len(pts), streets, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
