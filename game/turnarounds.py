"""Turnarounds where roads just stop: the edges of the map, and real dead ends.

  * a divided highway (two one-way carriageways ending near each other): a one-way U-turn loop that carries on past
    the end of the outgoing carriageway and swings back into the incoming one, so traffic and you can head back;
  * a two-way street or road: a cul-de-sac bulb, a paved circle past its end with a loop road round it (so the
    town's traffic can turn too).

Added at load (World.load) before the roads are graded and the road graph is built, so both see them. A bulb is
left out where it would land on a building or across another road.
"""
import math

TOUCH = 4.0               # metres: a road end this close to another road joins it (not a dead end)
PAIR = 70.0               # metres: carriageway ends this close make one highway end
BULB_R = {"side": 11.0, "main": 15.0}
UTURN_OUT = 25.0
STUB = 60.0               # metres: a carriageway piece shorter than this at a highway's end joins its U-turn          # metres the U-turn runs on past the highway's end before swinging round


def _seg_dist(x, y, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
    return math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)


class _Index:
    def __init__(self, roads, cell=60.0):
        self.cell, self.grid = cell, {}
        for r in roads:
            for a, b in zip(r["points"], r["points"][1:]):
                for gx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
                    for gy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                        self.grid.setdefault((gx, gy), []).append((r, a, b))

    def near(self, x, y, reach, skip=None):
        """Roads (other than `skip`) with a segment within `reach` of (x, y)."""
        out = []
        c = self.cell
        for gx in range(int((x - reach) // c), int((x + reach) // c) + 1):
            for gy in range(int((y - reach) // c), int((y + reach) // c) + 1):
                for r, a, b in self.grid.get((gx, gy), ()):
                    if r is not skip and r not in out and _seg_dist(x, y, a, b) < reach:
                        out.append(r)
        return out


def dead_ends(roads):
    """[(road, end index 0 or -1)] of non-service roads whose end touches no other road."""
    idx = _Index(roads)
    out = []
    for r in roads:
        if r.get("service") or r.get("lift") or len(r["points"]) < 2:
            continue
        for i in (0, -1):
            x, y = r["points"][i]
            if not idx.near(x, y, TOUCH, skip=r):
                out.append((r, i))
    return out


def _length(r):
    return sum(math.dist(a, b) for a, b in zip(r["points"], r["points"][1:]))


def _direction(r, i):
    """Unit vector pointing out of the road at end i."""
    pts = r["points"]
    a, b = (pts[1], pts[0]) if i == 0 else (pts[-2], pts[-1])
    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return (b[0] - a[0]) / L, (b[1] - a[1]) / L


def _circle(cx, cy, r, n=14, start=0.0):
    return [[round(cx + r * math.cos(start + 2 * math.pi * k / n), 2), round(cy + r * math.sin(start + 2 * math.pi * k / n), 2)]
            for k in range(n + 1)]


def _buildings(data):
    """clash(cx, cy, reach): True if a building outline comes within `reach` of (cx, cy) or covers it. (World's own
    building grid is not built yet at this point of the load.)"""
    cell, grid = 40.0, {}
    for b in data.get("buildings", []):
        P = b["points"]
        xs, ys = [p[0] for p in P], [p[1] for p in P]
        box = (min(xs), min(ys), max(xs), max(ys))
        for gx in range(int(box[0] // cell), int(box[2] // cell) + 1):
            for gy in range(int(box[1] // cell), int(box[3] // cell) + 1):
                grid.setdefault((gx, gy), []).append((box, P))

    def clash(cx, cy, reach):
        seen = set()
        for gx in range(int((cx - reach) // cell), int((cx + reach) // cell) + 1):
            for gy in range(int((cy - reach) // cell), int((cy + reach) // cell) + 1):
                for (x0, y0, x1, y1), P in grid.get((gx, gy), ()):
                    if id(P) in seen or x1 < cx - reach or x0 > cx + reach or y1 < cy - reach or y0 > cy + reach:
                        continue
                    seen.add(id(P))
                    edges = list(zip(P, P[1:] + P[:1]))
                    if any(_seg_dist(cx, cy, e0, e1) < reach for e0, e1 in edges):
                        return True
                    inside = False
                    for (ax, ay), (bx, by) in edges:
                        if (ay > cy) != (by > cy) and cx < ax + (cy - ay) * (bx - ax) / (by - ay):
                            inside = not inside
                    if inside:
                        return True
        return False
    return clash


def uturn(a, b, f, out=UTURN_OUT):
    """Points of a U-turn from `a` (the outgoing carriageway's end) to `b` (the incoming one's start), running `out`
    metres on in direction f, then a half circle across to b's side and back."""
    fx, fy = f
    r = max(math.dist(a, b) / 2.0, 10.0)                   # never tighter than 10 m
    ux, uy = (b[0] - a[0]) / (math.dist(a, b) or 1.0), (b[1] - a[1]) / (math.dist(a, b) or 1.0)
    mx, my = (a[0] + b[0]) / 2 + fx * out, (a[1] + b[1]) / 2 + fy * out
    pts = [list(a), [a[0] + fx * out * 0.5, a[1] + fy * out * 0.5]]
    for k in range(13):                                      # p(t) = m - u r cos t + f r sin t: a's side, far, b's side
        t = math.pi * k / 12
        pts.append([mx - ux * r * math.cos(t) + fx * r * math.sin(t), my - uy * r * math.cos(t) + fy * r * math.sin(t)])
    pts += [[b[0] + fx * out * 0.5, b[1] + fy * out * 0.5], list(b)]
    return [[round(x, 2), round(y, 2)] for x, y in pts]


def _trim(r, i, d):
    """Cut `d` metres off end i of road r (in place). False if the road is too short."""
    pts = r["points"] if i == -1 else r["points"][::-1]
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    if total < d + 15.0:
        return False
    while d > 0 and len(pts) > 1:
        L = math.dist(pts[-2], pts[-1])
        if L > d:
            t = (L - d) / L
            pts[-1] = [round(pts[-2][0] + (pts[-1][0] - pts[-2][0]) * t, 2), round(pts[-2][1] + (pts[-1][1] - pts[-2][1]) * t, 2)]
            break
        pts.pop()
        d -= L
    r["points"] = pts if i == -1 else pts[::-1]
    return True


def _outside(cx, cy, reach, bounds):
    """How far a circle sticks out of the map bounds (0 if it fits)."""
    x0, y0, x1, y1 = bounds
    return max(0.0, x0 - (cx - reach), (cx + reach) - x1, y0 - (cy - reach), (cy + reach) - y1)


def add(data):
    """Add U-turns and cul-de-sacs to data["roads"] (and paved bulbs to data["lots"]). Returns a report line."""
    roads = data["roads"]
    ends = dead_ends(roads)
    idx = _Index(roads)
    clash = _buildings(data)
    new_roads, bulbs, used, gone = [], [], set(), set()
    bounds = (data.get("meta") or {}).get("bounds")
    # divided highways: an outgoing carriageway's end (index -1, one-way) near an incoming one's start (index 0)
    ins = [r for r, i in ends if r.get("oneway") and i == 0]
    for r in [r for r, i in ends if r.get("oneway") and i == -1]:
        a = r["points"][-1]
        cand = [o for o in ins if o is not r and id(o) not in used and math.dist(a, o["points"][0]) <= PAIR]
        if not cand:
            continue
        o = min(cand, key=lambda o: math.dist(a, o["points"][0]))
        pts = uturn(a, o["points"][0], _direction(r, -1))
        # short stubs of carriageway at the very end become part of the U-turn, so it grades as one smooth road
        if _length(r) < STUB:
            pts = [list(p) for p in r["points"][:-1]] + pts
            gone.add(id(r))
        if _length(o) < STUB:
            pts = pts + [list(p) for p in o["points"][1:]]
            gone.add(id(o))
        new_roads.append({"type": r["type"], "width": r.get("width", 8.0), "name": r.get("name", ""), "oneway": 1,
                          "speed": min(r.get("speed", 50), 50), "points": pts, "turnaround": "uturn"})
        used.update((id(r), id(o)))
    # two-way roads: a cul-de-sac bulb past the end
    for r, i in ends:
        if r.get("oneway") or r.get("type") not in BULB_R or id(r) in used:
            continue
        x, y = r["points"][i]
        fx, fy = _direction(r, i)
        R = BULB_R[r["type"]]
        cx, cy = x + fx * R, y + fy * R
        out = _outside(cx, cy, R + 6.0, bounds) if bounds else 0.0
        if out > 0.0:                                         # at the map edge: pull the road's end back to fit
            if not _trim(r, i, out / max(abs(fx), abs(fy), 0.3) + 1.0):
                continue
            x, y = r["points"][i]
            fx, fy = _direction(r, i)
            cx, cy = x + fx * R, y + fy * R
            if _outside(cx, cy, R + 5.0, bounds) > 0.0:
                continue
        if clash(cx, cy, R + 5.0):
            continue                                          # no room: a building is there
        if idx.near(cx, cy, R + 2.0, skip=r):
            continue                                          # would cut across another road
        new_roads.append({"type": r["type"], "width": min(r.get("width", 7.0), 7.0), "name": r.get("name", ""),
                          "speed": 20, "points": _circle(cx, cy, R, 14, math.atan2(-fy, -fx)), "turnaround": "bulb"})
        bulbs.append({"points": [[round(cx + (R + 3.0) * math.cos(t), 1), round(cy + (R + 3.0) * math.sin(t), 1)]
                                 for t in (2 * math.pi * k / 16 for k in range(16))],
                      "area": round(math.pi * (R + 3.0) ** 2), "bulb": True})
    roads[:] = [r for r in roads if id(r) not in gone] + new_roads
    data.setdefault("lots", []).extend(bulbs)
    return "turnarounds: %d highway U-turns, %d cul-de-sacs (%d dead ends found)" % (
        sum(1 for r in new_roads if r["turnaround"] == "uturn"), len(bulbs), len(ends))
