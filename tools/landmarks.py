"""Real-world landmarks: find them in the converted map and decorate it.

A landmark spec file (see data/landmarks_amherst.json) lists:
  * "district": a centre and radius; buildings inside get sandstone/brick materials.
  * "landmarks": entries that either
      - match a BUILDING by OSM name and/or tags near a point (kind courthouse, church, civic,
        heritage_house, armoury, visitor_centre), falling back to the nearest building to the point;
      - match a PARK by name (kind square): lawn + cenotaph + a ring of trees, optional spawn point;
      - place a feature at a point (kind wind_farm, lighthouse).
Points are given as "near": [lat, lon] for real maps, or "near_xy": [x, y] for the sample town.

apply_landmarks() changes the map data in place and returns a human-readable report, so it is easy
to see what matched and fix the spec file if something landed on the wrong building.
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SPEC = os.path.join(ROOT, "data", "landmarks_amherst.json")

BUILDING_KINDS = ("courthouse", "church", "civic", "heritage_house", "armoury", "visitor_centre")
DEFAULT_LABELS = {"church": "Church", "civic": "Civic Building", "courthouse": "Court House",
                  "heritage_house": "Heritage House", "armoury": "Armoury", "visitor_centre": "Visitor Centre"}
FALLBACK_RADIUS = 45.0      # how close the nearest building must be when nothing matches by name


def load_spec(path=DEFAULT_SPEC):
    with open(path) as f:
        return json.load(f)


def _centroid(pts):
    n = len(pts)
    return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n


def _area(pts):
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))) / 2


def _inside(x, y, pts):
    inside, j = False, len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point(entry, key, to_xy):
    """Resolve entry[key] ([lat, lon]) or entry[key + '_xy'] ([x, y]) to local metres."""
    if key + "_xy" in entry:
        return tuple(entry[key + "_xy"])
    if key in entry and to_xy is not None:
        return to_xy(*entry[key])
    return None


def _matches(tags, entry):
    names = [n.lower() for n in entry.get("names", [])]
    want = entry.get("tags", {})
    name = tags.get("name", "").lower()
    by_name = bool(names) and any(n in name for n in names)
    by_tags = bool(want) and all(tags.get(k) == v for k, v in want.items())
    return by_name or by_tags


def _stable_hash(i):
    return (i * 2654435761) % 4294967296 / 4294967296.0


def apply_landmarks(data, spec, to_xy=None, area=None):
    """Decorate the map data in place. Returns a list of report lines.

    area: (x0, y0, x1, y1) of the downloaded box in local metres. A landmark whose point lies outside it is
    reported instead of guessed, because its real building is not in the data.
    """
    report = []

    def outside(pt):
        return area is not None and pt is not None and not (area[0] <= pt[0] <= area[2] and area[1] <= pt[1] <= area[3])

    buildings = data.get("buildings", [])
    parks = data.setdefault("parks", [])
    placed = data.setdefault("landmarks", [])
    props = data.setdefault("props", [])
    cents = [_centroid(b["points"]) for b in buildings]

    # 0. banks, post offices etc. are often mapped as a point inside a building: give that building the tags
    attached = 0
    for poi in data.get("pois", []):
        for b in buildings:
            pts = b["points"]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if min(xs) <= poi["x"] <= max(xs) and min(ys) <= poi["y"] <= max(ys) and _inside(poi["x"], poi["y"], pts):
                tags = b.setdefault("tags", {})
                for k, v in poi["tags"].items():
                    tags.setdefault(k, v)
                attached += 1
                break
    if data.get("pois"):
        report.append(f"points of interest: {attached}/{len(data['pois'])} matched to the building they sit in")

    # 1. downtown district materials
    d = spec.get("district")
    if d:
        c = _point(d, "near", to_xy)
        mats = d.get("materials", {"sandstone": 0.55, "brick": 0.45})
        names, weights = list(mats), list(mats.values())
        total = sum(weights)
        n = 0
        for i, (bx, by) in enumerate(cents):
            if c and math.hypot(bx - c[0], by - c[1]) <= d.get("radius", 350):
                r, acc = _stable_hash(i) * total, 0.0
                for name, w in zip(names, weights):
                    acc += w
                    if r <= acc:
                        buildings[i]["material"] = name
                        break
                n += 1
        report.append(f"district: {n} buildings given {'/'.join(names)} materials")

    # 2. landmarks
    for entry in spec.get("landmarks", []):
        kind, lid = entry["kind"], entry.get("id", entry["kind"])
        near = _point(entry, "near", to_xy)
        search = entry.get("search", 300.0)

        if kind in BUILDING_KINDS and outside(near) and not entry.get("all") and entry.get("search", 300) <= 600:
            report.append(f"{lid}: OUTSIDE the downloaded area - fetch an area that includes {entry.get('near')}")
            continue
        if kind == "square" and outside(near):
            if not any(_matches(p, entry) for p in parks):
                report.append(f"{lid}: OUTSIDE the downloaded area - fetch an area that includes {entry.get('near')}")
                continue

        if kind in BUILDING_KINDS and entry.get("only_if_no_role") and entry.get("role") \
                and any(b.get("role") == entry["role"] for b in buildings):
            report.append(f"{lid}: skipped, a building already has role {entry['role']!r}")
            continue
        if kind in BUILDING_KINDS:
            cands = []
            for i, b in enumerate(buildings):
                if near and math.hypot(cents[i][0] - near[0], cents[i][1] - near[1]) > search:
                    continue
                if _matches(b.get("tags", {}), entry):
                    cands.append((math.hypot(cents[i][0] - near[0], cents[i][1] - near[1]) if near else 0.0, i))
            how = "name/tags"
            if not cands and near and entry.get("fallback_nearest", True):
                best = min(((math.hypot(cx - near[0], cy - near[1]), i) for i, (cx, cy) in enumerate(cents)),
                           default=None)
                if best and best[0] <= FALLBACK_RADIUS:
                    cands, how = [best], "nearest building to the given point"
            if not cands:
                report.append(f"{lid}: NOT FOUND (edit names/near in the landmark file)")
                continue
            cands.sort()
            chosen = cands if entry.get("all") else cands[:1]
            for dist, i in chosen:
                b = buildings[i]
                b["landmark"] = kind
                b["label"] = entry.get("label") or b.get("tags", {}).get("name") or DEFAULT_LABELS.get(kind, lid)
                if entry.get("material"):
                    b["material"] = entry["material"]
                if entry.get("height"):
                    b["height"] = entry["height"]
                if entry.get("colour"):
                    b["colour"] = list(entry["colour"])
                if entry.get("role"):
                    b["role"] = entry["role"]
                if kind == "courthouse":
                    b["tower"] = bool(entry.get("tower", True))
                if kind == "visitor_centre":
                    _place_beside(b, placed, "lighthouse", entry.get("label", "Lighthouse"))
            names = ", ".join(repr(buildings[i].get("tags", {}).get("name", "unnamed")) for _d, i in chosen[:4])
            more = f" (+{len(chosen) - 4} more)" if len(chosen) > 4 else ""
            report.append(f"{lid}: {len(chosen)} building(s) by {how}, {chosen[0][0]:.0f} m from point: {names}{more}")

        elif kind == "square":
            best = None
            for p in parks:
                cx, cy = _centroid(p["points"])
                dist = math.hypot(cx - near[0], cy - near[1]) if near else 0.0
                if dist <= search and _matches(p, entry) and (best is None or dist < best[0]):
                    best = (dist, p)
            if best is None:
                report.append(f"{lid}: NOT FOUND (no park named {entry.get('names')} near the point)")
                continue
            park = best[1]
            park["landmark"] = "square"
            park["label"] = entry.get("label", park.get("name", lid))
            cx, cy = _centroid(park["points"])
            mem = [m for m in data.get("memorials", []) if _inside(m["x"], m["y"], park["points"])]
            mx, my = (mem[0]["x"], mem[0]["y"]) if mem else (cx, cy)
            placed.append({"kind": "cenotaph", "x": round(mx, 1), "y": round(my, 1), "label": entry.get("monument", "Cenotaph")})
            # a ring of trees inside the square
            rr = math.sqrt(_area(park["points"])) * 0.33
            for k in range(entry.get("trees", 8)):
                a = k * 2 * math.pi / entry.get("trees", 8) + 0.3
                tx, ty = cx + rr * math.cos(a), cy + rr * math.sin(a)
                if _inside(tx, ty, park["points"]):
                    props.append({"kind": "tree", "x": round(tx, 1), "y": round(ty, 1)})
            if entry.get("spawn"):
                sp = _spawn_near(data.get("roads", []), cx, cy)
                if sp:
                    data["meta"]["spawn"] = sp
            report.append(f"{lid}: park {park.get('name', '')!r} {best[0]:.0f} m from point; "
                          f"cenotaph {'at the mapped memorial' if mem else 'at the centre'}"
                          f"{'; spawn set here' if entry.get('spawn') else ''}")

        elif kind == "wind_farm":
            at = _point(entry, "at", to_xy)
            n, sp = entry.get("count", 10), entry.get("spacing", 330.0)
            h, blade = entry.get("hub_height", 80.0), entry.get("blade", 48.0)
            for k in range(n):       # two staggered rows running north-south
                row, idx = k % 2, k // 2
                x = at[0] + (row - 0.5) * sp * 0.7
                y = at[1] + (idx - (n - 1) / 4) * sp
                placed.append({"kind": "turbine", "x": round(x, 1), "y": round(y, 1), "h": h, "blade": blade,
                               "phase": round(k * 1.37, 2)})
            report.append(f"{lid}: {n} turbines placed")

        elif kind == "lighthouse":
            at = _point(entry, "at", to_xy)
            placed.append({"kind": "lighthouse", "x": round(at[0], 1), "y": round(at[1], 1),
                           "label": entry.get("label", "Lighthouse")})
            report.append(f"{lid}: lighthouse placed")
        else:
            report.append(f"{lid}: unknown kind {kind!r} skipped")

    # no square to start at: start on the nearest proper road to the town centre instead of the highway
    if "spawn" not in data["meta"] and d:
        c = _point(d, "near", to_xy)
        roads = [r for r in data.get("roads", []) if not r.get("oneway")]
        sp = _spawn_near(roads, c[0], c[1]) if c else None
        if sp:
            data["meta"]["spawn"] = sp
            report.append("spawn: on the nearest two-way road to the town centre")

    data["meta"]["landmark_report"] = report
    return report


def _place_beside(b, placed, kind, label):
    """Put a feature 9 m out from the middle of the building's longest wall."""
    pts = b["points"]
    cx, cy = _centroid(pts)
    best = None
    for a, c in zip(pts, pts[1:] + pts[:1]):
        L = math.hypot(c[0] - a[0], c[1] - a[1])
        if best is None or L > best[0]:
            best = (L, a, c)
    L, a, c = best
    mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
    nx, ny = mx - cx, my - cy
    d = math.hypot(nx, ny) or 1.0
    placed.append({"kind": kind, "x": round(mx + nx / d * 9.0, 1), "y": round(my + ny / d * 9.0, 1), "label": label})


def _spawn_near(roads, x, y):
    """Nearest point on a main/side road to (x, y), with the road's heading."""
    best = None
    for r in roads:
        if r.get("type") == "lane":
            continue
        pts = r["points"]
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
            px, py = a[0] + t * dx, a[1] + t * dy
            d = math.hypot(px - x, py - y)
            if best is None or d < best[0]:
                best = (d, px, py, math.atan2(dy, dx))
    return [round(best[1], 1), round(best[2], 1), round(best[3], 4)] if best else None
