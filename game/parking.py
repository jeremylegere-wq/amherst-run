"""Open parking lots (data/parking.json, made by tools/fetch_parking.py from OpenStreetMap amenity=parking areas).

The NSRN road data draws a big lot's aisles as a tangle of driveway roads. At load time each lot becomes one open
paved area (game/world.py counts it as road for grip; game/render3d.py paints it with stall lines up close) and the
driveway roads are cut where they run through a lot: what is left outside (at least MIN_PIECE metres) stays, reaching
REACH metres into the lot so it still meets the pavement.
"""
import json
import math
import os

NAME = "parking.json"
STEP = 1.0                # metres between samples along a road when cutting it
REACH = 1.0               # a kept stub runs this far into the lot
MIN_PIECE = 4.0           # shorter leftovers are dropped
CUT_SERVICE = ("driveway", "parking_aisle")


def load_beside(map_path):
    path = os.path.join(os.path.dirname(os.path.abspath(map_path)), NAME)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("lots", [])
    except (OSError, ValueError):
        return []


def _inside(x, y, pts):
    hit, j = False, len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def _edge_dist(x, y, pts):
    best = 1e9
    for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


def bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def cut(points, lots):
    """The pieces of a road polyline that are not deep inside any lot (lists of points, each >= MIN_PIECE long)."""
    pieces, cur = [], []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / STEP))
        for k in range(n + 1):
            if k == 0 and cur:
                continue
            x, y = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
            deep = any(_inside(x, y, P) and _edge_dist(x, y, P) > REACH for P in lots)
            if deep:
                if len(cur) > 1:
                    pieces.append(cur)
                cur = []
            else:
                cur.append([round(x, 2), round(y, 2)])
    if len(cur) > 1:
        pieces.append(cur)
    out = []
    for p in pieces:
        if sum(math.dist(a, b) for a, b in zip(p, p[1:])) >= MIN_PIECE:
            out.append(_simplify(p))
    return out


def _simplify(pts, tol=0.3):
    """Drop sample points that lie on a straight line (cut() samples every metre)."""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        (ax, ay), (bx, by), (cx, cy) = out[-1], pts[i], pts[i + 1]
        if abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / max(1e-6, math.hypot(cx - ax, cy - ay)) > tol:
            out.append(pts[i])
    out.append(pts[-1])
    return out


def apply(data, lots):
    """Put the lots in data["lots"] and cut driveway roads through them. Returns a one-line report or ""."""
    if not lots:
        return ""
    data["lots"] = lots
    boxes = [bbox(lot["points"]) for lot in lots]
    polys = [lot["points"] for lot in lots]
    roads, removed, touched = [], 0.0, 0
    for r in data["roads"]:
        if r.get("service") not in CUT_SERVICE or r.get("name"):
            roads.append(r)
            continue
        x0, y0, x1, y1 = bbox(r["points"])
        near = [polys[i] for i, b in enumerate(boxes) if b[0] <= x1 and b[2] >= x0 and b[1] <= y1 and b[3] >= y0]
        if not near:
            roads.append(r)
            continue
        pieces = cut(r["points"], near)
        before = sum(math.dist(a, b) for a, b in zip(r["points"], r["points"][1:]))
        after = sum(math.dist(a, b) for p in pieces for a, b in zip(p, p[1:]))
        if before - after < 0.5:
            roads.append(r)
            continue
        touched += 1
        removed += before - after
        for p in pieces:
            roads.append(dict(r, points=p))
    data["roads"] = roads
    return "parking lots: %d open lots, %d driveway roads cut back (%.1f km of lot aisles removed)" % (
        len(lots), touched, removed / 1000.0)


def stall_lines(lot, spacing=2.8, row=16.0, half=5.0):
    """Painted stall lines for a lot: rows of back-to-back stalls along its longest side. [(x0, y0, x1, y1)]."""
    pts = lot["points"]
    best = max(zip(pts, pts[1:] + pts[:1]), key=lambda e: math.dist(e[0], e[1]))
    L = math.dist(*best)
    ux, uy = (best[1][0] - best[0][0]) / L, (best[1][1] - best[0][1]) / L
    vx, vy = -uy, ux
    us = [p[0] * ux + p[1] * uy for p in pts]
    vs = [p[0] * vx + p[1] * vy for p in pts]
    out = []
    v = min(vs) + 1.0 + half
    while v + half < max(vs) - 0.5:
        u = min(us) + 1.5
        while u < max(us) - 1.5:
            ax, ay = ux * u + vx * (v - half), uy * u + vy * (v - half)
            bx, by = ux * u + vx * (v + half), uy * u + vy * (v + half)
            if _inside(ax, ay, pts) and _inside(bx, by, pts):
                out.append((ax, ay, bx, by))
            u += spacing
        v += row
    return out
