#!/usr/bin/env python3
"""Download OpenStreetMap data for a town from the Overpass API and (optionally) convert it.

Standard library only, no extra installs.

Examples (run from the project root):
    python tools/fetch_osm.py                      # Amherst NS, 6 x 6 km around town -> data/amherst.osm
    python tools/fetch_osm.py --convert            # ...and also write data/amherst_map.json
    python tools/fetch_osm.py --radius 3000        # bigger area
    python tools/fetch_osm.py --bbox 45.80 -64.25 45.84 -64.18 --convert
    python tools/fetch_osm.py --place "Springhill, Nova Scotia" --out data/springhill.osm

What it downloads: drivable roads, buildings, railways, water polygons, and individual
trees and street lamps (footpaths, steps and cycleways are left out to keep the file small).

Please be polite to the free public servers: download once, then reuse the file.
Map data (c) OpenStreetMap contributors, Open Database Licence (ODbL).
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Default area: a 6 x 6 km square that covers downtown (court house 45.8332, -64.2132), the south end
# and Highway 104, and the edge of the marsh to the west. (An earlier default centred on 45.8167, -64.2167
# was 1.8 km too far south and missed downtown.)
DEFAULT_CENTER = (45.8260, -64.2180)
DEFAULT_RADIUS_M = 3000

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AmherstRunHobbyGame/0.1 (personal non-commercial project)"

# Highway types we do not want to drive on
SKIP_HIGHWAYS = "footway|path|steps|cycleway|pedestrian|bridleway|corridor|elevator|proposed|construction|platform"


def bbox_from_center(lat, lon, radius_m):
    """Return (south, west, north, east) for a square of half-size radius_m around a point."""
    dlat = math.degrees(radius_m / 6371000.0)
    dlon = math.degrees(radius_m / (6371000.0 * math.cos(math.radians(lat))))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def build_query(bbox, timeout=120):
    s, w, n, e = bbox
    return (
        f"[out:xml][timeout:{timeout}];\n"
        f"(\n"
        f'  way["highway"]["highway"!~"{SKIP_HIGHWAYS}"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  way["building"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  way["railway"="rail"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  way["natural"="water"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  way["waterway"="riverbank"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  way["landuse"="reservoir"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  node["natural"="tree"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  way["leisure"="park"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  node["historic"="memorial"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  node["amenity"~"^(bank|post_office|place_of_worship|courthouse|townhall|police|fire_station)$"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  node["tourism"~"^(museum|information)$"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f'  node["highway"="street_lamp"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});\n'
        f");\n"
        f"(._;>;);\n"   # also fetch every node the ways use
        f"out body;\n"
    )


def ensure_bounds(xml_bytes, bbox):
    """Add a <bounds> element (the converter uses it as the map origin) if Overpass left it out."""
    if b"<bounds" in xml_bytes:
        return xml_bytes
    s, w, n, e = bbox
    tag = f'\n  <bounds minlat="{s:.6f}" minlon="{w:.6f}" maxlat="{n:.6f}" maxlon="{e:.6f}"/>'.encode()
    m = re.search(rb"<osm[^>]*>", xml_bytes)
    if not m:
        raise ValueError("Response does not look like OSM XML")
    return xml_bytes[:m.end()] + tag + xml_bytes[m.end():]


def looks_like_osm(data):
    head = data[:400].lstrip()
    return b"<osm" in data[:2000] and (head.startswith(b"<?xml") or head.startswith(b"<osm"))


def geocode(place):
    """Look up a place name with Nominatim. Returns (lat, lon)."""
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        results = json.loads(resp.read().decode("utf-8"))
    if not results:
        raise SystemExit(f"Could not find a place called {place!r}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def download(query, urls=OVERPASS_URLS, attempts=3, timeout=180):
    """POST the query to each Overpass server in turn, with back-off. Returns raw bytes."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last_error = None
    for attempt in range(attempts):
        for url in urls:
            host = urllib.parse.urlparse(url).netloc
            print(f"  asking {host} (attempt {attempt + 1}/{attempts}) ...", flush=True)
            req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = resp.read()
                if looks_like_osm(data):
                    return data
                last_error = f"{host} returned something that is not OSM XML: {data[:120]!r}"
            except urllib.error.HTTPError as exc:
                last_error = f"{host} answered HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"{host} failed: {exc}"
            print(f"  {last_error}", flush=True)
        if attempt < attempts - 1:
            wait = 10 * (attempt + 1)
            print(f"  waiting {wait} s before retrying ...", flush=True)
            time.sleep(wait)
    raise SystemExit(f"Download failed. Last problem: {last_error}\n"
                     "Fallback: use https://overpass-turbo.eu (run the query, Export > raw OSM data) "
                     "or the Export button on openstreetmap.org, and save the file as data/amherst.osm")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/amherst.osm", help="where to save the OSM XML")
    ap.add_argument("--center", nargs=2, type=float, metavar=("LAT", "LON"), default=None)
    ap.add_argument("--radius", type=float, default=DEFAULT_RADIUS_M, help="half-size of the square area in metres")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("SOUTH", "WEST", "NORTH", "EAST"), default=None)
    ap.add_argument("--place", default=None, help='look up a place name instead, e.g. "Amherst, Nova Scotia"')
    ap.add_argument("--convert", action="store_true", help="also run the map converter after downloading")
    ap.add_argument("--no-nsrn", action="store_true",
                    help="keep the OpenStreetMap roads instead of applying data/nsrn_amherst_extract.csv")
    ap.add_argument("--map-out", default=None, help="converted map path (default: next to --out, *_map.json)")
    ap.add_argument("--print-query", action="store_true", help="print the Overpass query and exit")
    args = ap.parse_args(argv)

    if args.bbox:
        bbox = tuple(args.bbox)
    else:
        if args.place:
            center = geocode(args.place)
            print(f"Found {args.place!r} at {center[0]:.4f}, {center[1]:.4f}")
        else:
            center = tuple(args.center) if args.center else DEFAULT_CENTER
        bbox = bbox_from_center(center[0], center[1], args.radius)

    s, w, n, e = bbox
    if not (-90 <= s < n <= 90 and -180 <= w < e <= 180):
        raise SystemExit(f"Invalid bounding box: {bbox}")
    area_km2 = (n - s) * 111.2 * (e - w) * 111.2 * math.cos(math.radians((n + s) / 2))
    if area_km2 > 100:
        raise SystemExit(f"That area is {area_km2:.0f} km2, which is too big for the public server. Use a smaller radius.")

    query = build_query(bbox)
    if args.print_query:
        print(query)
        return 0

    print(f"Area: {area_km2:.1f} km2  (S {s:.4f}, W {w:.4f}, N {n:.4f}, E {e:.4f})")
    data = ensure_bounds(download(query), bbox)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"Saved {len(data) / 1024:.0f} KB to {args.out}")

    if args.convert:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import landmarks as lm
        import osm_to_map
        map_out = args.map_out or os.path.splitext(args.out)[0] + "_map.json"
        spec = lm.load_spec() if os.path.exists(lm.DEFAULT_SPEC) else None
        import nsrn
        game_map = osm_to_map.convert(args.out, landmarks=spec,
                                      nsrn_csv=nsrn.DEFAULT_EXTRACT if os.path.exists(nsrn.DEFAULT_EXTRACT) and not args.no_nsrn else None)
        if game_map["meta"].get("road_report"):
            print(" ", game_map["meta"]["road_report"])
        for line in game_map["meta"].get("landmark_report", []):
            print("  landmark", line)
        with open(map_out, "w") as f:
            json.dump(game_map, f, separators=(",", ":"))
        print(f"Converted: roads={len(game_map['roads'])} buildings={len(game_map['buildings'])} "
              f"rails={len(game_map['rails'])} water={len(game_map['water'])} -> {map_out}")
        print("Run the game with:  python -m game.main")
    else:
        print("Next: python tools/osm_to_map.py", args.out, os.path.splitext(args.out)[0] + "_map.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
