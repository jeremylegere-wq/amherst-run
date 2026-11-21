#!/usr/bin/env python3
"""Download the OpenStreetMap layers the main map download leaves out, and save them as data/osm_extras.json:

  areas       land use as flat ground colour: grass, meadows, farm fields, cemeteries, sports pitches, playgrounds,
              running tracks, golf courses, wetlands, scrub and sand
  waterways   rivers, streams, canals and ditches as lines (with a width)
  power       power lines: the poles or towers they hang from, in order, so the wires can be strung between them;
              plus poles mapped on their own
  fences      fences, walls, hedges and guard rails as lines

    python tools/fetch_osm_extras.py             # everything inside the bounds of data/amherst_map.json

game/extras.py loads the file beside the map. Map data (c) OpenStreetMap contributors (ODbL).
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import fetch_osm  # noqa: E402
import fetch_parking  # noqa: E402
import osm_to_map  # noqa: E402

OUT = os.path.join(ROOT, "data", "osm_extras.json")
AREA_KINDS = {   # (tag, value) -> kind the renderer knows
    ("landuse", "grass"): "grass", ("landuse", "village_green"): "grass", ("landuse", "recreation_ground"): "grass",
    ("leisure", "garden"): "grass", ("leisure", "dog_park"): "grass", ("natural", "grassland"): "meadow",
    ("landuse", "meadow"): "meadow", ("landuse", "farmland"): "farmland", ("landuse", "farmyard"): "farmland",
    ("landuse", "orchard"): "farmland", ("landuse", "allotments"): "farmland",
    ("landuse", "cemetery"): "cemetery", ("amenity", "grave_yard"): "cemetery",
    ("leisure", "pitch"): "pitch", ("leisure", "stadium"): "pitch", ("leisure", "playground"): "playground",
    ("leisure", "track"): "track", ("leisure", "golf_course"): "golf", ("leisure", "sports_centre"): "grass",
    ("natural", "wetland"): "wetland", ("natural", "scrub"): "scrub", ("natural", "heath"): "scrub",
    ("natural", "sand"): "sand", ("natural", "beach"): "sand",
    ("landuse", "construction"): "dirt", ("landuse", "brownfield"): "dirt",
}
WATER_WIDTH = {"river": 9.0, "canal": 5.0, "stream": 2.4, "ditch": 1.4, "drain": 1.4}
FENCE_KINDS = {"fence": "fence", "wall": "wall", "retaining_wall": "wall", "hedge": "hedge", "guard_rail": "guard_rail"}


def query(bbox, timeout=180):
    s, w, n, e = bbox
    B = "(%f,%f,%f,%f)" % (s, w, n, e)
    sel = [
        'way["landuse"~"^(farmland|meadow|grass|cemetery|recreation_ground|orchard|allotments|village_green|brownfield|construction|farmyard)$"]',
        'way["leisure"~"^(pitch|playground|sports_centre|golf_course|track|stadium|garden|dog_park)$"]',
        'way["amenity"="grave_yard"]',
        'way["natural"~"^(wetland|scrub|heath|grassland|beach|sand)$"]',
        'way["barrier"~"^(fence|wall|hedge|retaining_wall|guard_rail)$"]',
        'way["power"~"^(line|minor_line)$"]',
        'node["power"~"^(pole|tower)$"]',
        'way["waterway"~"^(river|stream|ditch|canal|drain)$"]',
    ]
    return "[out:xml][timeout:%d];\n(\n%s\n);\n(._;>;);\nout body;\n" % (timeout, "\n".join(" %s%s;" % (x, B) for x in sel))


def convert(path, meta):
    """The extras document from an OSM XML file, in map metres."""
    nodes, ways, _bounds, node_tags = osm_to_map.parse_osm(path)
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]

    def xy(ref):
        x, y = osm_to_map.project(*nodes[ref], lat0, lon0)
        return [round(x, 1), round(y, 1)]
    areas, waterways, power, fences = [], [], [], []
    hung = set()
    for refs, tags in ways:
        pts = [xy(r) for r in refs if r in nodes]
        if len(pts) < 2:
            continue
        kind = next((AREA_KINDS[(k, tags[k])] for k in ("landuse", "leisure", "amenity", "natural")
                     if (k, tags.get(k)) in AREA_KINDS), None)
        if kind and refs[0] == refs[-1] and len(pts) >= 4:
            areas.append({"kind": kind, "points": pts[:-1]})
        elif tags.get("waterway") in WATER_WIDTH and tags.get("tunnel") not in ("yes", "culvert"):
            waterways.append({"kind": tags["waterway"], "width": WATER_WIDTH[tags["waterway"]],
                              "points": [[round(x, 1), round(y, 1)] for x, y in osm_to_map.simplify(pts, 1.5)]})
        elif tags.get("power") in ("line", "minor_line"):
            poles = []
            for r in refs:
                if r in nodes:
                    t = node_tags.get(r, {})
                    poles.append(xy(r) + [1 if t.get("power") == "tower" or tags["power"] == "line" and t.get("power") != "pole" else 0])
                    hung.add(r)
            power.append({"kind": tags["power"], "poles": poles})
        elif tags.get("barrier") in FENCE_KINDS:
            fences.append({"kind": FENCE_KINDS[tags["barrier"]], "points": pts})
    lone = [xy(r) + [1 if t.get("power") == "tower" else 0] for r, t in node_tags.items()
            if t.get("power") in ("pole", "tower") and r not in hung and r in nodes]
    return {"source": "OpenStreetMap (land use, waterways, power lines, barriers), (c) OpenStreetMap contributors, ODbL",
            "areas": areas, "waterways": waterways, "power": power, "lone_poles": lone, "fences": fences}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--osm", help="convert an OSM file you already downloaded instead of asking Overpass")
    args = ap.parse_args(argv)
    with open(args.map) as f:
        meta = json.load(f)["meta"]
    path = args.osm
    if not path:
        bbox = fetch_parking.map_bbox(meta)
        print("asking Overpass for land use, waterways, power lines and fences in %.4f,%.4f - %.4f,%.4f ..." % bbox, flush=True)
        raw = fetch_osm.download(query(bbox), timeout=300)
        path = os.path.join(ROOT, "data", "osm_extras.osm")          # git-ignored raw download
        with open(path, "wb") as f:
            f.write(raw)
    doc = convert(path, meta)
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
        f.write("\n")
    print("wrote %s: %d areas, %d waterways, %d power lines (%d poles), %d lone poles, %d fences"
          % (OUT, len(doc["areas"]), len(doc["waterways"]), len(doc["power"]),
             sum(len(p["poles"]) for p in doc["power"]), len(doc["lone_poles"]), len(doc["fences"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
