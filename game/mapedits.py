"""Hand edits to the map that survive re-downloading it: data/map_edits.json, plus overlap finding and fixing.

The map editor (tools/map_editor.py) writes this file and World.load applies it, so the converted map is never
touched. Edits find their building or road by position, not by number (OpenStreetMap ids and list order change when
the map is fetched again):

    {"version": 1,
     "buildings": {"delete":  [[x, y], ...],                              # x, y = centre of the building (metres)
                   "replace": [{"at": [x, y], "points": [[x, y], ...], "height": 7.5}]},
     "roads":     {"delete":  [[x, y], ...],                              # x, y = middle of the road (along its length)
                   "replace": [{"at": [x, y], "points": [...], "type": "side", "width": 8.0, "name": "Main St"}],
                   "add":     [{"points": [...], "type": "side", "width": 8.0, "name": "New St"}]}}

New buildings are not here: they are specs in data/custom_buildings.json (see game/builder.py). This module is pure
logic (no pygame).
"""
import json
import math
import os

EDITS_NAME = "map_edits.json"
TOLERANCE = 3.0                     # metres: how far the map may have moved since the edit was made
ROAD_FIELDS = ("type", "width", "name", "speed", "rc", "lanes", "oneway", "surface", "service", "ref")
BUILDING_FIELDS = ("height", "material", "colour", "roof", "roof_height", "roof_colour", "landmark", "label", "role",
                   "chimney", "ridge_across", "arch", "tower", "steeple", "storeys", "shopfront", "dormers", "plinth",
                   "front", "door", "door_at", "sidelights", "shutters",
                   "front_windows", "plaque", "window_h", "plinth_h")   # house details: see Renderer3D._house
MIN_OVERLAP = 0.35                  # metres of intrusion before something counts as overlapping (walls touch in rows)


# ------------------------------------------------------------------ keys
def centre(points):
    n = len(points)
    return sum(p[0] for p in points) / n, sum(p[1] for p in points) / n


def road_mid(points):
    """The point half way along a road's length: a stable way to name a road."""
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))
    if total <= 0:
        return tuple(points[0])
    half, run = total / 2.0, 0.0
    for a, b in zip(points, points[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if run + seg >= half and seg > 0:
            t = (half - run) / seg
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        run += seg
    return tuple(points[-1])


def _find(keys, at, used=None):
    """Index of the key nearest `at` (within TOLERANCE), or None. keys: one (x, y) per item, made once per apply()."""
    best, best_d = None, TOLERANCE
    ax, ay = at[0], at[1]
    for i, k in enumerate(keys):
        if abs(k[0] - ax) > TOLERANCE or abs(k[1] - ay) > TOLERANCE or (used is not None and i in used):
            continue
        d = math.hypot(k[0] - ax, k[1] - ay)
        if d < best_d:
            best, best_d = i, d
    return best


def _project(meta, lat, lon):
    """Latitude/longitude -> map metres (same projection as tools/osm_to_map.py), or None without an origin."""
    lat0, lon0 = meta.get("origin_lat"), meta.get("origin_lon")
    if lat0 is None or lon0 is None:
        return None
    return (math.radians(lon - lon0) * 6371000.0 * math.cos(math.radians(lat0)),
            -math.radians(lat - lat0) * 6371000.0)


def _apply_cars(data, cars):
    """Parked cars (the one in a driveway...): {"lat", "lon", "bearing" (compass degrees the nose points), "model"
    (game.car.MODELS), "colour": [r, g, b]}. They go in data["parked"] with x, y and a map heading (radians)."""
    n = 0
    for c in cars:
        xy = _project(data.get("meta", {}), c["lat"], c["lon"])
        if xy is None:
            return "parked cars skipped: the map has no origin"
        b = math.radians(c.get("bearing", 0.0))
        q = {k: v for k, v in c.items() if k not in ("lat", "lon", "bearing") and not k.startswith("_")}
        q.update(x=round(xy[0], 2), y=round(xy[1], 2), heading=round(math.atan2(-math.cos(b), math.sin(b)), 4))
        data.setdefault("parked", []).append(q)
        n += 1
    return "parked cars added: %d" % n


def _apply_props(data, props):
    """Hand-placed props (big trees in a yard...): {"kind", "lat", "lon", other prop fields}. Lat/lon so they survive
    a re-download that moves the map origin."""
    n = 0
    for p in props:
        xy = _project(data.get("meta", {}), p["lat"], p["lon"])
        if xy is None:
            return "prop edits skipped: the map has no origin"
        q = {k: v for k, v in p.items() if k not in ("lat", "lon", "lat2", "lon2") and not k.startswith("_")}
        q["x"], q["y"] = round(xy[0], 2), round(xy[1], 2)
        if "lat2" in p:                                           # a fence runs from (lat, lon) to (lat2, lon2)
            x2, y2 = _project(data.get("meta", {}), p["lat2"], p["lon2"])
            q["x2"], q["y2"] = round(x2, 2), round(y2, 2)
        data.setdefault("props", []).append(q)
        n += 1
    return "props added: %d" % n


def _apply_spawn(data, sp):
    """Move the start point. sp = {"lat", "lon", "bearing"} (bearing: compass degrees the car faces, 0 = north,
    90 = east). Stored as latitude/longitude so it survives a re-download that moves the map origin."""
    meta = data.setdefault("meta", {})
    xy = _project(meta, sp["lat"], sp["lon"])
    if xy is None:
        return "spawn edit skipped: the map has no origin"
    x, y = xy
    b = math.radians(sp.get("bearing", 90.0))
    meta["spawn"] = [round(x, 2), round(y, 2), round(math.atan2(-math.cos(b), math.sin(b)), 4)]
    return "spawn moved to %.5f, %.5f" % (sp["lat"], sp["lon"])


def _bkey(b):
    return centre(b["points"])


def _rkey(r):
    return road_mid(r["points"])


# ------------------------------------------------------------------ file
def empty():
    return {"version": 1, "buildings": {"delete": [], "replace": []},
            "roads": {"delete": [], "replace": [], "add": []}}


def load_beside(map_path):
    """The edits next to a map file (None when there are none)."""
    return load(os.path.join(os.path.dirname(os.path.abspath(map_path)), EDITS_NAME))


def load(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        print("map edits ignored: %s is not valid JSON" % path)
        return None
    return doc if isinstance(doc, dict) else None


def save(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def count(doc):
    if not doc:
        return 0
    b, r = doc.get("buildings", {}), doc.get("roads", {})
    return sum(len(x) for x in (b.get("delete", []), b.get("replace", []), r.get("delete", []), r.get("replace", []),
                                r.get("add", [])))


# ------------------------------------------------------------------ applying
def apply(data, doc, mark=False):
    """Apply an edits document to a map dict in place. Returns report lines.

    mark=True (the editor) keeps deleted buildings/roads in the lists with "_deleted": True instead of removing them,
    so the editor can bring them back and its list positions stay stable.
    """
    report = []
    if not doc:
        return report
    blds, roads = data["buildings"], data["roads"]
    bdoc, rdoc = doc.get("buildings", {}), doc.get("roads", {})
    if doc.get("spawn"):
        report.append(_apply_spawn(data, doc["spawn"]))
    if doc.get("props", {}).get("add"):
        report.append(_apply_props(data, doc["props"]["add"]))
    if doc.get("cars", {}).get("add"):
        report.append(_apply_cars(data, doc["cars"]["add"]))
    gone_b, gone_r = set(), set()
    bkeys = [_bkey(b) for b in blds]                  # computed once: a linear rescan per edit cost seconds at load
    rkeys = [_rkey(r) for r in roads]
    done = 0
    for at in bdoc.get("delete", []):
        i = _find(bkeys, at, gone_b)
        if i is None:
            report.append("edit skipped: no building near %s to delete" % (at,))
        else:
            gone_b.add(i)
            done += 1
    for rep in bdoc.get("replace", []):
        i = _find(bkeys, rep["at"], gone_b)
        if i is None:
            report.append("edit skipped: no building near %s to change" % (rep["at"],))
            continue
        if "points" in rep:
            blds[i]["points"] = [list(p) for p in rep["points"]]
            bkeys[i] = _bkey(blds[i])
        for k in BUILDING_FIELDS:
            if k in rep:
                blds[i][k] = rep[k]
        if rep.get("_note"):
            blds[i]["_note"] = rep["_note"]               # kept so the map editor writes it back
        if "roof" in rep and "ridge_across" not in rep:
            blds[i].pop("ridge_across", None)            # a hand-set roof replaces the measured one completely
        blds[i]["edited"] = True
        done += 1
    for at in rdoc.get("delete", []):
        i = _find(rkeys, at, gone_r)
        if i is None:
            report.append("edit skipped: no road near %s to delete" % (at,))
        else:
            gone_r.add(i)
            done += 1
    for rep in rdoc.get("replace", []):
        i = _find(rkeys, rep["at"], gone_r)
        if i is None:
            report.append("edit skipped: no road near %s to change" % (rep["at"],))
            continue
        if "points" in rep:
            roads[i]["points"] = [list(p) for p in rep["points"]]
            rkeys[i] = _rkey(roads[i])
        if rep.get("_note"):
            roads[i]["_note"] = rep["_note"]
        for k in ROAD_FIELDS:
            if k in rep:
                roads[i][k] = rep[k]
        done += 1
    if mark:
        for i in gone_b:
            blds[i]["_deleted"] = True
        for i in gone_r:
            roads[i]["_deleted"] = True
    else:
        if gone_b:
            blds[:] = [b for i, b in enumerate(blds) if i not in gone_b]
        if gone_r:
            roads[:] = [r for i, r in enumerate(roads) if i not in gone_r]
    for new in rdoc.get("add", []):
        r = {"type": "side", "width": 8.0, "name": "", "speed": 50, "rc": "LO", "points": []}
        r.update({k: v for k, v in new.items() if k in ROAD_FIELDS or k == "points"})
        r["points"] = [list(p) for p in new["points"]]
        if mark:
            r["_new"] = True
        roads.append(r)
        done += 1
    report.insert(0, "map edits: %d applied" % done)
    return report


# ------------------------------------------------------------------ geometry
def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def inside(x, y, pts):
    ins, j = False, len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def edge_dist(x, y, pts):
    """Distance from a point to the outline of a polygon."""
    return min(seg_dist(x, y, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:] + pts[:1]))


def bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def samples(points, step=2.0):
    """Points along a polyline every `step` metres (including the ends)."""
    out = [tuple(points[0])]
    for a, b in zip(points, points[1:]):
        n = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return out


def road_intrusion(pts, road, along=None):
    """(depth, x, y) of the worst place where the building `pts` is on the road surface; depth <= 0 means clear.
    `along` = precomputed samples(road["points"], 2.0)."""
    half = road.get("width", 6.0) / 2.0
    best = (-1e9, 0.0, 0.0)
    x0, y0, x1, y1 = bbox(pts)
    for x, y in (along if along is not None else samples(road["points"], 2.0)):
        if x < x0 - half - 1 or x > x1 + half + 1 or y < y0 - half - 1 or y > y1 + half + 1:
            continue
        if inside(x, y, pts):
            d = half + edge_dist(x, y, pts)               # the road's centre line is inside the building
        else:
            d = half - edge_dist(x, y, pts)               # how far the wall pokes into the road's width
        if d > best[0]:
            best = (d, x, y)
    return best


def _drivable(road):
    return not (road.get("bridge") or road.get("lift") or road.get("ramp"))


def buildings_overlap(a, b):
    """True if two footprints share real floor area (touching walls in a row of houses do not count)."""
    ax0, ay0, ax1, ay1 = bbox(a)
    bx0, by0, bx1, by1 = bbox(b)
    if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
        return False
    for p, q in ((a, b), (b, a)):
        for x, y in p:
            if inside(x, y, q) and edge_dist(x, y, q) > MIN_OVERLAP:
                return True
    cx, cy = centre(a)
    if inside(cx, cy, b) and edge_dist(cx, cy, b) > MIN_OVERLAP:
        return True
    cx, cy = centre(b)
    return inside(cx, cy, a) and edge_dist(cx, cy, a) > MIN_OVERLAP


class Index:
    """Grid of buildings and roads so overlap checks only compare neighbours."""
    CELL = 40.0

    def __init__(self, buildings, roads, skip_lanes=True):
        self.buildings, self.roads = buildings, roads
        self.skip_lanes = skip_lanes
        self.bgrid, self.rgrid = {}, {}
        self._along = {}
        for i, b in enumerate(buildings):
            if b.get("_deleted"):
                continue
            for c in self._cells(bbox(b["points"]), 0.0):
                self.bgrid.setdefault(c, []).append(i)
        for j, r in enumerate(roads):
            if r.get("_deleted") or not _drivable(r) or (skip_lanes and r.get("type") == "lane"):
                continue
            pad = r.get("width", 6.0) / 2.0 + 1.0
            seen = set()
            for x, y in samples(r["points"], 8.0):
                for c in self._cells((x, y, x, y), pad):
                    if c not in seen:
                        seen.add(c)
                        self.rgrid.setdefault(c, []).append(j)

    def _cells(self, bb, pad):
        x0, y0, x1, y1 = bb
        C = self.CELL
        for cx in range(int((x0 - pad) // C), int((x1 + pad) // C) + 1):
            for cy in range(int((y0 - pad) // C), int((y1 + pad) // C) + 1):
                yield cx, cy

    def intrusion(self, pts, j):
        if j not in self._along:
            self._along[j] = samples(self.roads[j]["points"], 2.0)
        return road_intrusion(pts, self.roads[j], self._along[j])

    def roads_near(self, pts):
        seen = []
        for c in self._cells(bbox(pts), 2.0):
            for j in self.rgrid.get(c, ()):
                if j not in seen:
                    seen.append(j)
        return seen

    def buildings_near(self, pts, skip=None):
        seen = []
        for c in self._cells(bbox(pts), 1.0):
            for i in self.bgrid.get(c, ()):
                if i != skip and i not in seen:
                    seen.append(i)
        return seen

    # --- problems ---------------------------------------------------------
    def building_problems(self, i):
        """Problems of one building: [{"kind", "building", "other", "depth", "at"}]."""
        b = self.buildings[i]
        out = []
        for j in self.roads_near(b["points"]):
            depth, x, y = self.intrusion(b["points"], j)
            if depth > MIN_OVERLAP:
                out.append({"kind": "road", "building": i, "other": j, "depth": depth, "at": (x, y)})
        for k in self.buildings_near(b["points"], skip=i):
            if k > i and buildings_overlap(b["points"], self.buildings[k]["points"]):
                out.append({"kind": "building", "building": i, "other": k, "depth": 0.0,
                            "at": centre(b["points"])})
        return out

    def all_problems(self):
        out = []
        for i, b in enumerate(self.buildings):
            if not b.get("_deleted"):
                out.extend(self.building_problems(i))
        out.sort(key=lambda p: (p["at"][0], p["at"][1]))
        return out


def push_clear(index, i, max_move=14.0):
    """Slide building `i` away from the roads it sits on (never into another building).

    Returns (moved metres, still_overlapping). The building is left where it was if no clean spot is found.
    """
    b = index.buildings[i]
    start = [tuple(p) for p in b["points"]]
    pts = [list(p) for p in start]
    moved = 0.0
    for _ in range(12):
        worst = None
        for j in index.roads_near(pts):
            depth, x, y = index.intrusion(pts, j)
            if depth > MIN_OVERLAP and (worst is None or depth > worst[0]):
                worst = (depth, x, y)
        if worst is None:
            break
        depth, x, y = worst
        cx, cy = centre(pts)
        dx, dy = cx - x, cy - y
        L = math.hypot(dx, dy)
        if L < 1e-6:
            dx, dy, L = 1.0, 0.0, 1.0
        step = min(depth + 0.6, 6.0)
        pts = [[p[0] + dx / L * step, p[1] + dy / L * step] for p in pts]
        moved += step
        if moved > max_move:
            break
    clash = any(buildings_overlap(pts, index.buildings[k]["points"]) for k in index.buildings_near(pts, skip=i))
    still = clash or any(index.intrusion(pts, j)[0] > MIN_OVERLAP for j in index.roads_near(pts))
    if moved > max_move or clash:
        return 0.0, True
    b["points"] = [[round(p[0], 2), round(p[1], 2)] for p in pts]
    return moved, still


# ------------------------------------------------------------------ fallbacks when a building cannot be pushed clear
def poly_area(pts):
    return abs(sum(pts[k][0] * pts[k - 1][1] - pts[k - 1][0] * pts[k][1] for k in range(len(pts)))) / 2.0


def _clip_halfplane(pts, ax, ay, nx, ny, off):
    """Sutherland-Hodgman: the part of polygon pts where (p - a) . n >= off."""
    out = []
    n = len(pts)
    for k in range(n):
        p, q = pts[k], pts[(k + 1) % n]
        dp = (p[0] - ax) * nx + (p[1] - ay) * ny - off
        dq = (q[0] - ax) * nx + (q[1] - ay) * ny - off
        if dp >= 0:
            out.append([p[0], p[1]])
        if (dp >= 0) != (dq >= 0):
            t = dp / (dp - dq)
            out.append([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t])
    return out


def trim_clear(index, i, margin=0.3, keep_share=0.35):
    """Cut building i back to the edge of the roads it pokes into (when it cannot be slid clear without hitting a
    neighbour). Only ever shrinks the building. Returns True if it is now clear and keeps at least `keep_share` of
    its floor area; otherwise leaves it unchanged and returns False."""
    b = index.buildings[i]
    pts = [list(p) for p in b["points"]]
    area0 = poly_area(pts)
    for _ in range(4):
        worst = None
        for j in index.roads_near(pts):
            depth, x, y = index.intrusion(pts, j)
            if depth > MIN_OVERLAP and (worst is None or depth > worst[0]):
                worst = (depth, x, y, j)
        if worst is None:
            break
        _d, x, y, j = worst
        road = index.roads[j]
        rp = road["points"]
        seg = min(zip(rp, rp[1:]), key=lambda s: seg_dist(x, y, s[0][0], s[0][1], s[1][0], s[1][1]))
        (ax, ay), (bx, by) = seg
        L = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = -(by - ay) / L, (bx - ax) / L
        side = sum((p[0] - ax) * nx + (p[1] - ay) * ny for p in pts)       # keep the side most of the building is on
        if side < 0:
            nx, ny = -nx, -ny
        pts = _clip_halfplane(pts, ax, ay, nx, ny, road.get("width", 6.0) / 2.0 + margin)
        if len(pts) < 3:
            return False
    if poly_area(pts) < keep_share * area0 or any(index.intrusion(pts, j)[0] > MIN_OVERLAP for j in index.roads_near(pts)):
        return False
    b["points"] = [[round(p[0], 2), round(p[1], 2)] for p in pts]
    return True


def cut_road_outside(points, polys, step=0.5, min_len=3.0):
    """A road (driveway) polyline with the parts inside any of the footprints `polys` removed: the longest piece left,
    or None if nothing of at least `min_len` metres remains (then the driveway should go)."""
    pieces, cur = [], []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        L = math.hypot(bx - ax, by - ay)
        n = max(1, int(L / step))
        for k in range(n + 1):
            t = k / n
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            if any(inside(x, y, P) and edge_dist(x, y, P) > 0.2 for P in polys):
                if len(cur) > 1:
                    pieces.append(cur)
                cur = []
            elif not cur or (x, y) != tuple(cur[-1]):
                cur.append([x, y])
    if len(cur) > 1:
        pieces.append(cur)
    if not pieces:
        return None
    best = max(pieces, key=lambda c: sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(c, c[1:])))
    if sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(best, best[1:])) < min_len:
        return None
    keep = [best[0]] + [p for k, p in enumerate(best[1:-1], 1)
                        if abs((p[0] - best[k - 1][0]) * (best[k + 1][1] - p[1]) - (p[1] - best[k - 1][1]) * (best[k + 1][0] - p[0])) > 1e-6] + [best[-1]]
    return [[round(p[0], 2), round(p[1], 2)] for p in keep]


def swallowed(small, big):
    """True if footprint `small` lies wholly inside `big` (a leftover duplicate)."""
    return poly_area(small) < poly_area(big) and all(inside(x, y, big) or edge_dist(x, y, big) < 0.3 for x, y in small)
