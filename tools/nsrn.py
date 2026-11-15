"""Nova Scotia Road Network (NSRN) import: real street names, road classes, one-way flags, bridges and speed limits.

The NSRN is the province's road centreline file (https://data.novascotia.ca, dataset 484g-adjn). This module
turns its CSV export into game roads and swaps them into a converted map, so the map keeps its OpenStreetMap
buildings, parks and landmarks but gets authoritative streets.

What the NSRN does NOT contain is posted speed limits. The limits here are DEFAULTS derived from road class and
distance from downtown (see RULES). Override any street in data/speed_overrides.json: {"Victoria St E": 60}.

Usage (normally through tools/osm_to_map.py, or on its own):
    python tools/nsrn_to_roads.py data/nsrn_amherst_extract.csv data/amherst_map.json
"""
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict

ATTRIBUTION = ("Road data: Nova Scotia Road Network. Contains information licensed under the "
               "Open Government Licence - Nova Scotia.")

csv.field_size_limit(10 ** 9)

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DEFAULT_EXTRACT = os.path.join(_DATA, "nsrn_amherst_extract.csv")
DEFAULT_OVERRIDES = os.path.join(_DATA, "speed_overrides.json")

DOWNTOWN = (45.83315, -64.21318)          # Court House; "urban" speed limits apply around here
URBAN_RADIUS = 2200.0                      # metres
LIFT = 5.2                                 # deck height (m) of a bridge that carries a road over another road
LIFT_MAX_LENGTH = 250.0                    # longer bridges cross water/marsh, not an interchange, so they stay flat
MIN_CROSS_ANGLE = 0.25                     # |sin| of the crossing angle needed to count as a real crossing

# ROADCLASS code -> (game type, default width m, urban km/h, rural km/h, service tag or None)
RULES = {
    "TC": ("main", 9.0, 100, 100, None),      # Trans-Canada: width is per carriageway (they are separate lines)
    "HW": ("main", 9.0, 90, 90, None),
    "LH": ("main", 9.0, 80, 80, None),
    "AT": ("main", 10.0, 50, 80, None),
    "LA": ("main", 9.0, 50, 70, None),
    "CO": ("side", 9.0, 50, 70, None),
    "LC": ("side", 9.0, 50, 70, None),
    "LO": ("side", 8.0, 50, 50, None),
    "RP": ("side", 7.0, 50, 50, None),
    "SL": ("lane", 5.0, 30, 30, None),
    "DW": ("lane", 5.0, 40, 40, None),
    "SE": ("lane", 4.0, 30, 30, None),
    "PR": ("lane", 4.0, 30, 30, "private"),
    "DR": ("lane", 4.0, 20, 20, "driveway"),
    "TK": ("lane", 4.0, 30, 30, "track"),
}
# Skipped: rail (RR, AR), trails (TR), water access (WA), median crossovers (MC), ferries (FC), restricted (RS).


def parse_wkt(geom):
    """MULTILINESTRING ((lon lat, lon lat), (...)) -> list of [(lon, lat), ...]."""
    parts = []
    for part in re.findall(r"\(([^()]+)\)", geom):
        pts = []
        for pair in part.split(","):
            xy = pair.split()
            if len(xy) >= 2:
                pts.append((float(xy[0]), float(xy[1])))
        if len(pts) >= 2:
            parts.append(pts)
    return parts


def read_rows(path):
    """Yield CSV rows (dicts) with a parsed 'parts' list."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row["parts"] = parse_wkt(row.get("the_geom", ""))
            if row["parts"]:
                yield row


def write_extract(src, dst, lat_range, lon_range):
    """Copy the rows that touch a lat/lon box into a small CSV (same columns) that can live in the repo."""
    n = 0
    with open(src, newline="", encoding="utf-8-sig") as fin, open(dst, "w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            pts = [p for part in parse_wkt(row["the_geom"]) for p in part]
            if any(lon_range[0] <= x <= lon_range[1] and lat_range[0] <= y <= lat_range[1] for x, y in pts):
                writer.writerow({k: row[k] for k in reader.fieldnames})
                n += 1
    return n


def display_name(raw, rule_class):
    """Street name as shown on the HUD ('' for driveways, tracks and unnamed roads)."""
    name = (raw or "").strip()
    if not name or name in ("None", "Driveway", "Track", "Railroad", "Active Rail Road", "Bridge"):
        return ""
    m = re.match(r"^Highway (\d+) (?:EB|WB|NB|SB)$", name)
    if m:
        return "Highway " + m.group(1)
    m = re.match(r"^Highway (\d+) (?:EB|WB|NB|SB) (Exit \d+ (?:On|Off) Ramp)(?: Branch)?$", name)
    if m:
        return "Hwy %s %s" % (m.group(1), m.group(2))
    return name


def _speed(code, name, urban, overrides):
    if name in overrides:
        return overrides[name]
    _t, _w, kmh_urban, kmh_rural, _s = RULES[code]
    kmh = kmh_urban if urban else kmh_rural
    if code == "RP":
        kmh = 60 if "Exit" in name else 40
    if "Scalehouse" in name:
        kmh = 30
    return kmh


def _width(code, feat_desc):
    base = RULES[code][1]
    d = feat_desc or ""
    if code in ("LO", "RP", "LC", "CO", "LA", "AT") and "1 Lane" in d:
        return min(base, 6.5)
    if "3 Lanes" in d or "4 Lanes" in d:
        return 11.5
    return base


def _simplify(pts, tol):
    try:
        from osm_to_map import simplify
    except ImportError:                                  # imported from outside tools/
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from osm_to_map import simplify
    return simplify(pts, tol)


def _lanes(feat):
    """Lane count from an NSRN description such as 'ROAD - Local - 2 Lanes - Paved' (None if not stated)."""
    m = re.search(r"(\d) Lanes?", feat or "")
    return int(m.group(1)) if m else None


def _road_key(r):
    return (r.get("name", "") if not r.get("bridge") else "", r["type"], r["width"], r.get("oneway", 0),
            r["speed"], bool(r.get("bridge")), r.get("ref", ""), r.get("service", ""), bool(r.get("ramp")),
            r.get("rc", ""), r.get("surface", ""), r.get("lanes", 0))


def _chain(polys, directed):
    """Join polylines that meet end to end. Directed: end of one must meet the start of the next."""
    alive = {i: list(p) for i, p in enumerate(polys)}
    changed = True
    while changed:
        changed = False
        ends = defaultdict(list)
        for i, p in alive.items():
            ends[(round(p[0][0], 2), round(p[0][1], 2))].append((i, "s"))
            ends[(round(p[-1][0], 2), round(p[-1][1], 2))].append((i, "e"))
        for lst in ends.values():
            if len(lst) != 2 or lst[0][0] == lst[1][0]:
                continue
            (i, a), (j, b) = lst
            if directed:
                if {a, b} != {"s", "e"}:
                    continue
                if a == "s":                              # make i the one that ends at the joint
                    i, j = j, i
                new = alive[i] + alive[j][1:]
            else:
                pi, pj = alive[i], alive[j]
                if a == "s":
                    pi = pi[::-1]
                if b == "e":
                    pj = pj[::-1]
                new = pi + pj[1:]
            alive[i] = new
            del alive[j]
            changed = True
            break
    return list(alive.values())


def _length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _crosses(a, b):
    """True if two polylines properly cross (interior points, not just touching at a shared node)."""
    for (ax, ay), (bx, by) in zip(a, a[1:]):
        for (cx, cy), (dx, dy) in zip(b, b[1:]):
            rx, ry, sx, sy = bx - ax, by - ay, dx - cx, dy - cy
            den = rx * sy - ry * sx
            la, lb = math.hypot(rx, ry), math.hypot(sx, sy)
            if la < 1e-6 or lb < 1e-6 or abs(den) / (la * lb) < MIN_CROSS_ANGLE:
                continue
            t = ((cx - ax) * sy - (cy - ay) * sx) / den
            u = ((cx - ax) * ry - (cy - ay) * rx) / den
            if 0.02 < t < 0.98 and 0.02 < u < 0.98:
                return True
    return False


def mark_lifts(roads):
    """Give bridges that carry a road over another drivable road a 'lift' (deck height in metres)."""
    ground = [r for r in roads if not r.get("bridge") and r.get("service") not in ("driveway", "track", "private")]
    n = 0
    for r in roads:
        if not r.get("bridge") or _length(r["points"]) > LIFT_MAX_LENGTH:
            continue
        x0 = min(p[0] for p in r["points"]) - 20
        x1 = max(p[0] for p in r["points"]) + 20
        y0 = min(p[1] for p in r["points"]) - 20
        y1 = max(p[1] for p in r["points"]) + 20
        for o in ground:
            ox = [p[0] for p in o["points"]]
            oy = [p[1] for p in o["points"]]
            if max(ox) < x0 or min(ox) > x1 or max(oy) < y0 or min(oy) > y1:
                continue
            if _crosses(r["points"], o["points"]):
                r["lift"] = LIFT
                n += 1
                break
    return n


def build_roads(rows, project, bounds, overrides=None, margin=250.0):
    """Game road dicts from NSRN rows. project(lat, lon) -> (x, y) metres; bounds = (x0, y0, x1, y1)."""
    overrides = overrides or {}
    dxy = project(*DOWNTOWN)
    x0, y0, x1, y1 = bounds[0] - margin, bounds[1] - margin, bounds[2] + margin, bounds[3] + margin
    raw = []
    for row in rows:
        code = row["ROADCLASS"]
        if code not in RULES or row["TRAFFICDIR"] == "5":              # unknown class or impassable
            continue
        feat = row["FEAT_DESC"] or ""
        if feat.startswith(("RAILROAD", "TRAIL", "WALK", "DAM", "FERRY")):
            continue
        rtype, _w, _ku, _kr, service = RULES[code]
        name = display_name(row["STREET"], code)
        ref = row["RTE_NO"] if row["RTE_NO"] not in ("", "0") else ""
        for part in row["parts"]:
            pts = [project(lat, lon) for lon, lat in part]
            if not any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts):
                continue
            mx, my = pts[len(pts) // 2]
            urban = math.hypot(mx - dxy[0], my - dxy[1]) <= URBAN_RADIUS
            road = {"type": rtype, "width": _width(code, feat), "name": name, "points": pts,
                    "speed": _speed(code, name, urban, overrides)}
            td = row["TRAFFICDIR"]
            if td == "2":
                road["oneway"] = 1
            elif td == "3":
                road["oneway"] = 1
                road["points"] = pts[::-1]                              # store in travel direction
            if feat.startswith("BRIDGE"):
                road["bridge"] = True
            elif feat.startswith("TUNNEL"):
                road["tunnel"] = True
            if ref:
                road["ref"] = ref
            if service:
                road["service"] = service
            if code == "RP":
                road["ramp"] = True
            road["rc"] = code                                           # NSRN road class: decides the paint on it
            if "Unpaved" in feat or code == "TK":
                road["surface"] = "gravel"
            lanes = _lanes(feat)
            if lanes:
                road["lanes"] = lanes
            raw.append(road)

    groups = defaultdict(list)
    for r in raw:
        groups[_road_key(r)].append(r)
    roads = []
    for key, members in groups.items():
        polys = _chain([m["points"] for m in members], directed=bool(key[3]))
        for pts in polys:
            r = {k: v for k, v in members[0].items() if k != "points"}
            if r.get("bridge"):                                          # name of the longest piece
                r["name"] = max(members, key=lambda m: _length(m["points"]))["name"]
            r["points"] = [[round(x, 1), round(y, 1)] for x, y in _simplify(pts, 0.8)]
            if len(r["points"]) >= 2 and _length(r["points"]) >= 1.0:
                roads.append(r)
    mark_lifts(roads)
    return roads


def load_overrides(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    return {}


def _snap_spawn(data):
    """Put the spawn on the nearest two-way street (the old one was snapped to OpenStreetMap geometry)."""
    spawn = data["meta"].get("spawn")
    if not spawn:
        return
    best = None
    for r in data["roads"]:
        if r.get("oneway") or r["type"] == "lane" or r.get("service") or r.get("bridge"):
            continue
        for (ax, ay), (bx, by) in zip(r["points"], r["points"][1:]):
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            if ll < 1e-6:
                continue
            t = max(0.0, min(1.0, ((spawn[0] - ax) * dx + (spawn[1] - ay) * dy) / ll))
            qx, qy = ax + t * dx, ay + t * dy
            d = math.hypot(spawn[0] - qx, spawn[1] - qy)
            if best is None or d < best[0]:
                best = (d, qx, qy, math.atan2(dy, dx))
    if best:
        data["meta"]["spawn"] = [round(best[1], 1), round(best[2], 1), round(best[3], 4)]


def apply(data, csv_path, overrides_path=None, project=None):
    """Replace data['roads'] with NSRN roads (in place). Returns a one-line report."""
    meta = data["meta"]
    lat0, lon0 = meta["origin_lat"], meta["origin_lon"]
    if project is None:
        def project(lat, lon):
            return (math.radians(lon - lon0) * 6371000.0 * math.cos(math.radians(lat0)),
                    -math.radians(lat - lat0) * 6371000.0)
    roads = build_roads(read_rows(csv_path), project, meta["bounds"], load_overrides(overrides_path))
    if not roads:
        return "NSRN: no roads inside the map area (is the extract for this region?) - roads left unchanged"
    data["roads"] = roads
    meta["road_source"] = "NSRN"
    base = "Map data (c) OpenStreetMap contributors"
    meta["attribution"] = base + ". " + ATTRIBUTION
    _snap_spawn(data)
    lifts = sum(1 for r in roads if r.get("lift"))
    named = len({r["name"] for r in roads if r["name"]})
    speeds = Counter(r["speed"] for r in roads if not r.get("service"))
    return "NSRN: %d roads, %d named streets, %d overpass spans, speed limits %s" % (
        len(roads), named, lifts, dict(sorted(speeds.items())))
