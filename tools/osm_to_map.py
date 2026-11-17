#!/usr/bin/env python3
"""Convert an OpenStreetMap .osm XML export into a compact game map (JSON).

Usage:
    python tools/osm_to_map.py data/amherst.osm data/amherst_map.json [landmarks.json]

Landmarks from data/landmarks_amherst.json are applied automatically (a report is printed), and so are the
Nova Scotia Road Network streets from data/nsrn_amherst_extract.csv (real names, one-ways, speed limits, overpasses).

Output coordinates are local metres: x = east, y = south (screen-style, y grows
downwards), with the origin at the centre of the export.

Known limitation: multipolygon relations (large lakes, marshes, some buildings)
are not stitched yet; only simple closed ways are used.
"""
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

ATTRIBUTION = "Map data (c) OpenStreetMap contributors"

# highway tag -> (class, width in metres). Anything not listed is skipped.
HIGHWAY_CLASSES = {
    "motorway": ("main", 12), "motorway_link": ("main", 8),
    "trunk": ("main", 12), "trunk_link": ("main", 8),
    "primary": ("main", 11), "primary_link": ("main", 8),
    "secondary": ("main", 10), "secondary_link": ("main", 8),
    "tertiary": ("side", 9), "tertiary_link": ("side", 7),
    "residential": ("side", 8), "unclassified": ("side", 8),
    "living_street": ("side", 7),
    "service": ("lane", 5), "track": ("lane", 4),
}

MIN_BUILDING_AREA = 15.0  # m^2, drops sheds and slivers


def project(lat, lon, lat0, lon0):
    """Equirectangular projection to local metres (fine for a town-sized area).

    x grows east; y grows SOUTH so it matches screen coordinates.
    """
    x = math.radians(lon - lon0) * 6371000.0 * math.cos(math.radians(lat0))
    y = -math.radians(lat - lat0) * 6371000.0
    return x, y


def _perp_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def simplify(points, tol):
    """Douglas-Peucker polyline simplification (iterative, no recursion limit)."""
    n = len(points)
    if n < 3:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        best, idx = 0.0, -1
        for i in range(lo + 1, hi):
            d = _perp_dist(points[i], points[lo], points[hi])
            if d > best:
                best, idx = d, i
        if idx != -1 and best > tol:
            keep[idx] = True
            stack.append((lo, idx))
            stack.append((idx, hi))
    return [p for p, k in zip(points, keep) if k]


def polygon_area(points):
    s = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def classify_highway(tags):
    """Return (class, width) for a drivable highway tag, else None."""
    return HIGHWAY_CLASSES.get(tags.get("highway"))


def building_height(tags):
    """Building height in metres from OSM 'height' or 'building:levels' tags, else None."""
    raw = tags.get("height") or tags.get("building:height")
    if raw:
        m = re.match(r"(\d+(?:\.\d+)?)\s*(m|ft|')?$", raw.strip().lower())
        if m:
            v = float(m.group(1))
            if m.group(2) in ("ft", "'"):
                v *= 0.3048
            if v > 0:
                return round(min(max(v, 2.5), 120.0), 1)
    levels = tags.get("building:levels")
    if levels:
        try:
            n = float(levels)
        except ValueError:
            n = 0.0
        if n > 0:
            return round(min(n * 3.2 + 1.0, 120.0), 1)
    return None


def road_extras(tags):
    """Extra road info for the game: one-way direction, bridge/tunnel, service type."""
    extra = {}
    hw = tags.get("highway", "")
    ow = (tags.get("oneway") or "").lower()
    if ow in ("yes", "true", "1"):
        extra["oneway"] = 1
    elif ow in ("-1", "reverse"):
        extra["oneway"] = -1
    elif ow not in ("no", "false", "0") and (tags.get("junction") == "roundabout"
                                             or hw in ("motorway", "motorway_link")):
        extra["oneway"] = 1
    if tags.get("bridge", "no") not in ("no", ""):
        extra["bridge"] = True
    if tags.get("tunnel", "no") not in ("no", ""):
        extra["tunnel"] = True
    if hw == "service" and tags.get("service"):
        extra["service"] = tags["service"]
    return extra


def parse_osm(source):
    """Parse OSM XML (path or file object). Returns (nodes, ways, bounds, node_tags)."""
    nodes, ways, bounds, node_tags = {}, [], None, {}
    for _, el in ET.iterparse(source, events=("end",)):
        if el.tag == "node":
            nodes[el.get("id")] = (float(el.get("lat")), float(el.get("lon")))
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags:
                node_tags[el.get("id")] = tags
            el.clear()
        elif el.tag == "way":
            refs = [nd.get("ref") for nd in el.findall("nd")]
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            ways.append((refs, tags))
            el.clear()
        elif el.tag == "bounds":
            bounds = tuple(float(el.get(k)) for k in ("minlat", "minlon", "maxlat", "maxlon"))
    return nodes, ways, bounds, node_tags


def _mark_of(tags):
    """Street-furniture node -> {"kind": ..} for the game's street detail pass, or None.

    kinds: stop, signal, crossing (+ "style": zebra/marked/uncontrolled/unmarked/signals), rail_crossing,
    hydrant, bench, bin, bus_stop. Only what OpenStreetMap actually has is kept.
    """
    hw = tags.get("highway")
    if hw == "stop":
        return {"kind": "stop"}
    if hw == "traffic_signals":
        return {"kind": "signal"}
    if hw == "crossing":
        style = tags.get("crossing") or ("marked" if tags.get("crossing_ref") else "unknown")
        return {"kind": "crossing", "style": style}
    if tags.get("railway") == "level_crossing":
        return {"kind": "rail_crossing"}
    if tags.get("emergency") == "fire_hydrant":
        return {"kind": "hydrant"}
    if tags.get("amenity") == "bench" or tags.get("leisure") == "picnic_table":
        return {"kind": "bench"}
    if tags.get("amenity") == "waste_basket":
        return {"kind": "bin"}
    if hw == "bus_stop":
        return {"kind": "bus_stop"}
    return None


def _round_pts(pts):
    return [[round(x, 1), round(y, 1)] for x, y in pts]


KEEP_BUILDING_TAGS = ("name", "amenity", "building", "tourism", "historic", "leisure")
POI_AMENITIES = ("bank", "post_office", "place_of_worship", "courthouse", "townhall", "police", "fire_station")
POI_TOURISM = ("museum", "information")


def convert(source, landmarks=None, nsrn_csv=None, origin=None):
    """Convert OSM XML to game map data. landmarks: a spec dict (see tools/landmarks.py) or None.
    origin: (lat, lon) of game (0, 0); default the middle of the download (tools/extend_map.py passes the main map's)."""
    nodes, ways, bounds, node_tags = parse_osm(source)
    if not nodes:
        raise ValueError("No nodes found in OSM file")

    if origin:
        lat0, lon0 = origin
    elif bounds:
        lat0 = (bounds[0] + bounds[2]) / 2
        lon0 = (bounds[1] + bounds[3]) / 2
    else:
        lat0 = sum(n[0] for n in nodes.values()) / len(nodes)
        lon0 = sum(n[1] for n in nodes.values()) / len(nodes)

    def way_points(refs):
        return [project(*nodes[r], lat0, lon0) for r in refs if r in nodes]

    roads, buildings, rails, water, parks = [], [], [], [], []
    for refs, tags in ways:
        pts = way_points(refs)
        if len(pts) < 2:
            continue
        cls = classify_highway(tags)
        if cls:
            road = {"type": cls[0], "width": cls[1], "name": tags.get("name", ""),
                    "points": _round_pts(simplify(pts, 1.5))}
            road.update(road_extras(tags))
            roads.append(road)
        elif "building" in tags and len(pts) >= 4 and refs[0] == refs[-1]:
            ring = simplify(pts[:-1], 1.0)
            if len(ring) >= 3 and polygon_area(ring) >= MIN_BUILDING_AREA:
                b = {"points": _round_pts(ring)}
                height = building_height(tags)
                if height:
                    b["height"] = height
                keep = {k: tags[k] for k in KEEP_BUILDING_TAGS if k in tags}
                if keep:
                    b["tags"] = keep
                buildings.append(b)
        elif tags.get("railway") == "rail":
            rails.append({"points": _round_pts(simplify(pts, 2.0))})
        elif (tags.get("natural") == "water" or tags.get("waterway") == "riverbank"
              or tags.get("landuse") == "reservoir") and len(pts) >= 4 and refs[0] == refs[-1]:
            water.append({"points": _round_pts(simplify(pts[:-1], 2.0))})
        elif tags.get("leisure") == "park" and len(pts) >= 4 and refs[0] == refs[-1]:
            parks.append({"name": tags.get("name", ""), "points": _round_pts(simplify(pts[:-1], 1.0))})

    props, memorials, pois, marks = [], [], [], []
    for nid, tags in node_tags.items():
        if (tags.get("amenity") in POI_AMENITIES or tags.get("tourism") in POI_TOURISM) and nid in nodes:
            x, y = project(*nodes[nid], lat0, lon0)
            keep = {k: tags[k] for k in KEEP_BUILDING_TAGS if k in tags}
            pois.append({"x": round(x, 1), "y": round(y, 1), "tags": keep})
        if tags.get("historic") == "memorial" and nid in nodes:
            x, y = project(*nodes[nid], lat0, lon0)
            memorials.append({"name": tags.get("name", ""), "x": round(x, 1), "y": round(y, 1)})
        mk = _mark_of(tags)
        if mk and nid in nodes:
            x, y = project(*nodes[nid], lat0, lon0)
            marks.append(dict(mk, x=round(x, 1), y=round(y, 1)))
        kind = "tree" if tags.get("natural") == "tree" else "lamp" if tags.get("highway") == "street_lamp" else None
        if kind and nid in nodes:
            x, y = project(*nodes[nid], lat0, lon0)
            props.append({"kind": kind, "x": round(x, 1), "y": round(y, 1)})

    allpts = [p for grp in (roads, buildings, rails, water) for item in grp for p in item["points"]]
    if allpts:
        xs, ys = [p[0] for p in allpts], [p[1] for p in allpts]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    else:
        bbox = [-100, -100, 100, 100]

    data = {
        "meta": {"name": "Amherst", "origin_lat": lat0, "origin_lon": lon0,
                 "bounds": bbox, "attribution": ATTRIBUTION},
        "roads": roads, "buildings": buildings, "rails": rails, "water": water, "props": props,
        "parks": parks, "memorials": memorials, "pois": pois, "marks": marks,
    }
    if landmarks:
        import landmarks as lm
        area = None
        if bounds:
            ax0, ay1 = project(bounds[0], bounds[1], lat0, lon0)     # south-west corner (y grows south)
            ax1, ay0 = project(bounds[2], bounds[3], lat0, lon0)     # north-east corner
            area = (ax0, ay0, ax1, ay1)
        lm.apply_landmarks(data, landmarks, to_xy=lambda lat, lon: project(lat, lon, lat0, lon0), area=area)
    if nsrn_csv:
        import nsrn
        data["meta"]["road_report"] = nsrn.apply(data, nsrn_csv, nsrn.DEFAULT_OVERRIDES)
    return data


def main(argv):
    if len(argv) not in (3, 4):
        print(__doc__)
        return 1
    import landmarks as lm
    spec_path = argv[3] if len(argv) == 4 else lm.DEFAULT_SPEC
    spec = lm.load_spec(spec_path) if os.path.exists(spec_path) else None
    import nsrn
    data = convert(argv[1], landmarks=spec, nsrn_csv=nsrn.DEFAULT_EXTRACT if os.path.exists(nsrn.DEFAULT_EXTRACT) else None)
    for line in data["meta"].get("landmark_report", []):
        print("  landmark", line)
    if data["meta"].get("road_report"):
        print(" ", data["meta"]["road_report"])
    with open(argv[2], "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"roads={len(data['roads'])} buildings={len(data['buildings'])} "
          f"rails={len(data['rails'])} water={len(data['water'])} props={len(data['props'])} -> {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
