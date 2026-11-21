"""Your own buildings: a small JSON file of presets placed by latitude/longitude that the game drops into the map.

    data/custom_buildings.json   (see docs/BUILDING.md)
    {"buildings": [{"name": "Grandma's place", "preset": "house", "lat": 45.8301, "lon": -64.2112}]}

Check a file without starting the game:   python -m game.builder data/custom_buildings.json

This module is pure logic (no pygame): it turns specs into the same building dicts the map uses, and describes roof
shapes (gable, hip, mansard) as faces the renderer can draw.
"""
import json
import math
import os
import sys

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "custom_buildings.json")

# width = along the street, depth = away from it (metres). Materials are the ones the renderer knows:
# sandstone, brick, clapboard, granite (or "colour": [r, g, b] for your own).
PRESETS = {
    "house":           dict(width=9.0, depth=8.0, height=6.2, roof="gable", roof_height=2.8, material="clapboard"),
    "cottage":         dict(width=7.5, depth=7.0, height=4.8, roof="hip", roof_height=2.2, material="clapboard"),
    "victorian":       dict(width=10.0, depth=9.0, height=8.6, roof="mansard", roof_height=2.6, material="brick"),
    "sandstone_block": dict(width=16.0, depth=12.0, height=11.0, roof="flat", roof_height=0.0, material="sandstone"),
    "shop":            dict(width=8.0, depth=14.0, height=5.6, roof="flat", roof_height=0.0, material="brick"),
    "apartments":      dict(width=32.0, depth=14.0, height=13.5, roof="flat", roof_height=0.0, material="brick"),
    "church":          dict(width=11.0, depth=24.0, height=9.0, roof="gable", roof_height=4.2, material="sandstone",
                            landmark="church"),
    "barn":            dict(width=22.0, depth=12.0, height=6.0, roof="gable", roof_height=3.6, material=None,
                            colour=(170, 60, 52)),
    "garage":          dict(width=6.0, depth=6.5, height=3.0, roof="gable", roof_height=1.5, material="clapboard"),
}
STYLES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "building_styles.json")


def load_styles(path=STYLES_PATH):
    """Named looks from data/building_styles.json ({} if the file is missing or broken)."""
    try:
        with open(path, encoding="utf-8") as f:
            styles = json.load(f).get("styles", {})
        return {k: v for k, v in styles.items() if isinstance(v, dict) and not k.startswith("_")}
    except (OSError, ValueError, AttributeError):
        return {}


STYLES = load_styles()
ROOFS = ("flat", "gable", "hip", "mansard", "cone")
PASS_THROUGH = ("dormers", "plinth", "arch", "storeys", "shopfront", "tower", "steeple", "ridge_across",
                "front", "door", "door_at", "sidelights", "shutters",
                "front_windows", "plaque", "window_h", "plinth_h")
ROOF_COLOURS = {"slate": (74, 80, 100), "shingle": (126, 66, 58), "copper": (74, 140, 120), "tin": (150, 156, 166)}
DEFAULT_ROOF_COLOUR = {"mansard": "slate", "gable": "shingle", "hip": "shingle", "cone": "slate"}
MAX_SIZE = 200.0   # malls are ~175 m wide
MIN_SIZE = 0.5     # garden arbours and porch posts are thin
ORIGIN = (45.8167, -64.2167)      # map origin when a map file does not say (the Amherst maps use this)


# ------------------------------------------------------------------ geometry
def project(meta, lat, lon):
    """Latitude/longitude -> map metres (x east, y south), the same projection as tools/osm_to_map.py."""
    lat0, lon0 = meta.get("origin_lat", ORIGIN[0]), meta.get("origin_lon", ORIGIN[1])
    return (math.radians(lon - lon0) * 6371000.0 * math.cos(math.radians(lat0)),
            -math.radians(lat - lat0) * 6371000.0)


def unproject(meta, x, y):
    lat0, lon0 = meta.get("origin_lat", ORIGIN[0]), meta.get("origin_lon", ORIGIN[1])
    return (lat0 - math.degrees(y / 6371000.0),
            lon0 + math.degrees(x / (6371000.0 * math.cos(math.radians(lat0)))))


def compass_vec(bearing):
    """Compass bearing in degrees (0 = north, 90 = east) -> unit vector in map coordinates."""
    b = math.radians(bearing)
    return math.sin(b), -math.cos(b)


def compass_of(dx, dy):
    return math.degrees(math.atan2(dx, -dy)) % 360.0


def nearest_road(roads, x, y, drivable_only=True):
    """(distance to the road edge, nearest point on its centreline, road) - None if there are no roads."""
    best = None
    for r in roads:
        if drivable_only and (r.get("service") in ("driveway", "private", "track") or r.get("bridge")):
            continue
        pts = r["points"]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            if ll < 1e-9:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ll))
            qx, qy = ax + t * dx, ay + t * dy
            d = math.hypot(x - qx, y - qy) - r["width"] / 2.0
            if best is None or d < best[0]:
                best = (d, (qx, qy), r)
    return best


def _crosses_box(pts, x0, y0, x1, y1):
    """True if any segment's own bounding box overlaps the box (a long straight road with no point inside it)."""
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        if min(ax, bx) <= x1 and max(ax, bx) >= x0 and min(ay, by) <= y1 and max(ay, by) >= y0:
            return True
    return False


def polygon_footprint(cx, cy, facing, width, sides):
    """Regular polygon (a round tower or bay drawn with `sides` flat faces) of diameter `width`, a face to the front."""
    out = []
    r = width / 2.0
    for k in range(sides):
        a = math.radians(facing) + math.pi / sides + 2 * math.pi * k / sides
        out.append([round(cx + r * math.sin(a), 2), round(cy - r * math.cos(a), 2)])
    return out


def footprint(cx, cy, facing, width, depth):
    """Rectangle centred on (cx, cy) whose front (a `width`-long side) looks along compass bearing `facing`."""
    fx, fy = compass_vec(facing)
    sx, sy = -fy, fx                                    # along the frontage
    out = []
    for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        out.append([round(cx + sx * width / 2 * a + fx * depth / 2 * b, 2),
                    round(cy + sy * width / 2 * a + fy * depth / 2 * b, 2)])
    return out


def roof_faces(pts, h, kind, rh, across=False):
    """Roof polygons (lists of (x, y, z)) for a 4-cornered footprint; [] for flat roofs or other footprints.
    The ridge runs along the long side, or across it (the short way) when `across` is true (cross-gabled houses).
    A "cone" roof works on any footprint: one face from each wall up to a point over the middle (towers, round bays)."""
    if kind == "cone" and rh > 0 and len(pts) >= 3:
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        n = len(pts)
        return [[(pts[k][0], pts[k][1], h), (pts[(k + 1) % n][0], pts[(k + 1) % n][1], h), (cx, cy, h + rh)]
                for k in range(n)]
    if kind not in ("gable", "hip", "mansard") or rh <= 0 or len(pts) != 4:
        return []
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    e1 = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    e2 = (pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    if l1 < 0.1 or l2 < 0.1:
        return []
    if (l1 >= l2) != bool(across):
        u, hl, hw = (e1[0] / l1, e1[1] / l1), l1 / 2.0, l2 / 2.0
    else:
        u, hl, hw = (e2[0] / l2, e2[1] / l2), l2 / 2.0, l1 / 2.0
    v = (-u[1], u[0])

    def P(a, b, z):
        return (cx + u[0] * a + v[0] * b, cy + u[1] * a + v[1] * b, z)

    top = h + rh
    if kind == "gable":
        return [[P(-hl, -hw, h), P(hl, -hw, h), P(hl, 0, top), P(-hl, 0, top)],
                [P(hl, hw, h), P(-hl, hw, h), P(-hl, 0, top), P(hl, 0, top)],
                [P(hl, -hw, h), P(hl, hw, h), P(hl, 0, top)],
                [P(-hl, hw, h), P(-hl, -hw, h), P(-hl, 0, top)]]
    if kind == "hip":
        r = max(0.0, hl - hw)
        return [[P(-hl, -hw, h), P(hl, -hw, h), P(r, 0, top), P(-r, 0, top)],
                [P(hl, hw, h), P(-hl, hw, h), P(-r, 0, top), P(r, 0, top)],
                [P(hl, -hw, h), P(hl, hw, h), P(r, 0, top)],
                [P(-hl, hw, h), P(-hl, -hw, h), P(-r, 0, top)]]
    i = min(rh * 0.55, hw * 0.5, hl * 0.5)               # mansard: steep skirt, flat top
    eave = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
    crown = [(-(hl - i), -(hw - i)), (hl - i, -(hw - i)), (hl - i, hw - i), (-(hl - i), hw - i)]
    faces = []
    for k in range(4):
        a, b = eave[k], eave[(k + 1) % 4]
        c, d = crown[(k + 1) % 4], crown[k]
        faces.append([P(a[0], a[1], h), P(b[0], b[1], h), P(c[0], c[1], top), P(d[0], d[1], top)])
    faces.append([P(a, b, top) for a, b in crown])
    return faces


def face_normal(face, pivot):
    """Unit normal of a roof face pointing away from the building (pivot = a point inside it)."""
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = face[0], face[1], face[2]
    ux, uy, uz, vx, vy, vz = x1 - x0, y1 - y0, z1 - z0, x2 - x0, y2 - y0, z2 - z0
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / n, ny / n, nz / n
    mx = sum(p[0] for p in face) / len(face) - pivot[0]
    my = sum(p[1] for p in face) / len(face) - pivot[1]
    mz = sum(p[2] for p in face) / len(face) - pivot[2]
    if nx * mx + ny * my + nz * mz < 0:
        nx, ny, nz = -nx, -ny, -nz
    return nx, ny, nz


# ------------------------------------------------------------------ specs -> buildings
def resolve(spec):
    """Spec merged over its preset. Returns (settings dict, [problems])."""
    problems = []
    style = {}
    if spec.get("style") is not None:
        style = STYLES.get(spec["style"])
        if style is None:
            problems.append("unknown style %r (see data/building_styles.json)" % (spec["style"],))
            style = {}
    spec = dict(style, **{k: v for k, v in spec.items() if v is not None})    # the spec overrides the style
    preset = spec.get("preset", "house")
    if preset not in PRESETS:
        problems.append("unknown preset %r (choose from %s)" % (preset, ", ".join(sorted(PRESETS))))
        preset = "house"
    s = dict(PRESETS[preset])
    for k in ("width", "depth", "height", "roof", "roof_height", "roof_colour", "material", "colour", "landmark", "label",
              "chimney", "sides") + PASS_THROUGH:
        if k in spec and spec[k] is not None:
            s[k] = spec[k]
    if s["roof"] not in ROOFS:
        problems.append("unknown roof %r (flat, gable, hip, mansard)" % (s["roof"],))
        s["roof"] = "flat"
    for k in ("width", "depth"):
        if not isinstance(s[k], (int, float)) or not MIN_SIZE <= s[k] <= MAX_SIZE:
            problems.append("%s must be between %g and %d metres" % (k, MIN_SIZE, MAX_SIZE))
            s[k] = PRESETS[preset][k]
    if not isinstance(s["height"], (int, float)) or not 0.5 <= s["height"] <= 60.0:     # 0.5: decks, hedges, fences
        problems.append("height must be between 0.5 and 60 metres")
        s["height"] = PRESETS[preset]["height"]
    return s, problems


def make_building(spec, meta, roads):
    """One spec -> (building dict, [warnings]). Raises ValueError if the spec has no usable position."""
    warnings = []
    if "lat" in spec and "lon" in spec:
        x, y = project(meta, float(spec["lat"]), float(spec["lon"]))
    elif "x" in spec and "y" in spec:
        x, y = float(spec["x"]), float(spec["y"])
    else:
        raise ValueError("needs \"lat\" and \"lon\" (or \"x\" and \"y\")")
    s, problems = resolve(spec)
    warnings.extend(problems)
    near = nearest_road(roads, x, y)
    if "facing" in spec:
        facing = float(spec["facing"]) % 360.0
    elif near is not None:                                   # default: the front faces the nearest street
        facing = compass_of(near[1][0] - x, near[1][1] - y) if math.hypot(near[1][0] - x, near[1][1] - y) > 0.3 else 0.0
    else:
        facing = 0.0
    if "setback" in spec and near is not None and math.hypot(near[1][0] - x, near[1][1] - y) > 0.3:
        fx, fy = compass_vec(facing)                         # slide along the facing line to sit `setback` off the kerb
        qx, qy = near[1]
        road_half = near[2]["width"] / 2.0
        dist = road_half + float(spec["setback"]) + s["depth"] / 2.0
        d0 = math.hypot(qx - x, qy - y) or 1.0
        x, y = qx - (qx - x) / d0 * dist, qy - (qy - y) / d0 * dist
    sides = int(s.get("sides") or 4)
    pts = polygon_footprint(x, y, facing, s["width"], sides) if sides >= 5 else footprint(x, y, facing, s["width"], s["depth"])
    samples = list(pts) + [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts, pts[1:] + pts[:1])] + [(x, y)]
    bx0, by0 = min(p[0] for p in pts) - 50.0, min(p[1] for p in pts) - 50.0
    bx1, by1 = max(p[0] for p in pts) + 50.0, max(p[1] for p in pts) + 50.0
    near = [r for r in roads or () if any(bx0 <= q[0] <= bx1 and by0 <= q[1] <= by1 for q in r["points"])
            or _crosses_box(r["points"], bx0, by0, bx1, by1)]       # only roads near this building (load time)
    if near and any((nearest_road(near, px, py) or (1e9,))[0] < 0.5 for px, py in samples):
        warnings.append("overlaps a road - move it back or set \"setback\"")
    b = {"points": pts, "height": float(s["height"]), "custom": True,
         "tags": {"building": "yes", "custom": str(spec.get("name", spec.get("style") or spec.get("preset", "building")))}}
    if s.get("material"):
        b["material"] = s["material"]
    if s.get("colour"):
        b["colour"] = [int(c) for c in s["colour"]][:3]
    if s["roof"] != "flat":
        b["roof"] = s["roof"]
        b["roof_height"] = float(s["roof_height"])
        rc = s.get("roof_colour") or DEFAULT_ROOF_COLOUR.get(s["roof"], "slate")
        b["roof_colour"] = list(ROOF_COLOURS[rc]) if isinstance(rc, str) and rc in ROOF_COLOURS else [int(c) for c in rc][:3]
        if s.get("chimney") is not None and s["chimney"] is not False:
            b["chimney"] = 0.3 if s["chimney"] is True else max(-0.9, min(0.9, float(s["chimney"])))
    for k in PASS_THROUGH:
        if s.get(k) is not None:
            b[k] = list(s[k]) if isinstance(s[k], tuple) else s[k]
    if s.get("landmark"):
        b["landmark"] = s["landmark"]
    if s.get("label"):
        b["label"] = str(s["label"])
    return b, warnings


def centroid(b):
    n = len(b["points"])
    return sum(p[0] for p in b["points"]) / n, sum(p[1] for p in b["points"]) / n


def apply_custom(data, doc):
    """Add the buildings of a custom-buildings document to a map dict (in place). Returns a list of report lines."""
    report = []
    meta, roads = data["meta"], data["roads"]
    added = 0
    for n, spec in enumerate(doc.get("buildings", []), 1):
        name = spec.get("name") or "#%d" % n
        try:
            b, warns = make_building(spec, meta, roads)
        except (ValueError, TypeError, KeyError) as e:
            report.append("SKIPPED %s: %s" % (name, e))
            continue
        x0, y0, x1, y1 = meta["bounds"]
        cx, cy = centroid(b)
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            report.append("SKIPPED %s: outside the map" % name)
            continue
        rr = float(spec.get("replace_radius", 0) or 0)
        if rr > 0:                                           # swap out the OpenStreetMap building(s) already there
            keep = [o for o in data["buildings"] if math.hypot(centroid(o)[0] - cx, centroid(o)[1] - cy) > rr]
            report.append("%s: replaced %d existing building(s)" % (name, len(data["buildings"]) - len(keep)))
            data["buildings"][:] = keep
        data["buildings"].append(b)
        added += 1
        for w in warns:
            report.append("WARNING %s: %s" % (name, w))
    report.insert(0, "custom buildings: %d added" % added)
    return report


def load_doc(path):
    if not os.path.exists(path):
        return {"buildings": []}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict) or not isinstance(doc.get("buildings", []), list):
        raise ValueError("%s: expected {\"buildings\": [...]}" % path)
    return doc


def save_doc(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_PATH
    mp = argv[2] if len(argv) > 2 else os.path.join(os.path.dirname(path), "amherst_map.json")
    with open(mp, encoding="utf-8") as f:
        data = json.load(f)
    for line in apply_custom(data, load_doc(path)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
