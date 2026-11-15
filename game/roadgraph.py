"""Road graph for AI driving (traffic and police).

The map only stores road polylines, so junctions are found from geometry:
  * where two roads cross, both are split at the crossing point;
  * a road that ends within SNAP metres of another road (a T-junction) is joined to it;
  * a bridge or tunnel does not connect to roads it crosses;
  * long stretches are cut into pieces of at most MAX_EDGE metres.
Edges are directed (a two-way road gives two edges), and cars keep to the RIGHT of
their direction of travel (Nova Scotia). Heading 0 is east, y grows south, so the right-hand
side of a direction (dx, dy) is (-dy, dx).
"""
import heapq
import math
from collections import defaultdict

CELL = 40.0
NODE_CELL = 2.0
SNAP = 3.0
MERGE = 1.0
MIN_EDGE = 0.5
MAX_EDGE = 50.0
BEHIND_PENALTY = 50.0      # re-planning prefers a node up to this much further away if it is ahead (> MAX_EDGE)
NO_AI_SERVICE = ("driveway", "parking_aisle", "drive-through", "track", "private")
CRUISE = {"main": 16.0, "side": 11.0, "lane": 6.5}   # m/s


class Edge:
    __slots__ = ("a", "b", "ax", "ay", "bx", "by", "length", "dx", "dy", "rtype", "width", "cruise", "lane", "kmh", "name")

    def __init__(self, a, b, pa, pb, rtype, width, kmh=None, name=""):
        self.a, self.b = a, b
        self.ax, self.ay = pa
        self.bx, self.by = pb
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        self.length = math.hypot(dx, dy)
        self.dx, self.dy = dx / self.length, dy / self.length
        self.rtype, self.width = rtype, width
        self.kmh = kmh if kmh else round(CRUISE.get(rtype, 8.0) * 3.6 / 10.0) * 10   # posted limit, km/h
        self.cruise = self.kmh / 3.6                  # legal speed in m/s: traffic drives at this (times its own pace)
        self.name = name
        self.lane = min(width * 0.25, 2.6)       # distance of the driving lane from the road centre


def _cells(x0, y0, x1, y1):
    for cx in range(int(x0 // CELL), int(x1 // CELL) + 1):
        for cy in range(int(y0 // CELL), int(y1 // CELL) + 1):
            yield cx, cy


def _seg_intersect(a, b):
    """Intersection of segments a and b, each (x0, y0, x1, y1). Returns (t_a, t_b) or None."""
    ax, ay, bx, by = a
    cx, cy, dx, dy = b
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    den = rx * sy - ry * sx
    if abs(den) < 1e-9:
        return None                              # parallel
    qx, qy = cx - ax, cy - ay
    t = (qx * sy - qy * sx) / den
    u = (qx * ry - qy * rx) / den
    eps = 1e-6
    if -eps <= t <= 1 + eps and -eps <= u <= 1 + eps:
        return t, u
    return None


def _project(px, py, ax, ay, bx, by):
    """Closest point on a segment. Returns (t, distance, x, y)."""
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    qx, qy = ax + t * dx, ay + t * dy
    return t, math.hypot(px - qx, py - qy), qx, qy


def _elevated(road):
    return bool(road.get("bridge") or road.get("tunnel"))


def _subdivide(chain):
    out = [chain[0]]
    for (x0, y0), (x1, y1) in zip(chain, chain[1:]):
        pieces = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / MAX_EDGE))
        for k in range(1, pieces):
            t = k / pieces
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        out.append((x1, y1))
    return out


class RoadGraph:
    def __init__(self, roads):
        self.nodes = []          # (x, y)
        self._levels = []        # 0 = ground, 1 = interior of a bridge/tunnel
        self.out = []            # node id -> outgoing edge ids
        self.edges = []          # Edge
        self._node_grid = defaultdict(list)
        self._edge_keys = set()
        self._build(roads)
        self._edge_grid = defaultdict(list)
        self._coarse = defaultdict(list)
        for i, e in enumerate(self.edges):
            self._edge_grid[(int((e.ax + e.bx) / 2 // CELL), int((e.ay + e.by) / 2 // CELL))].append(i)
        for n, (x, y) in enumerate(self.nodes):
            self._coarse[(int(x // CELL), int(y // CELL))].append(n)

    # ------------------------------------------------------------------ build
    def _node_at(self, x, y, level=0, merge_any=False):
        """Find or create the node at a point. Bridge/tunnel interiors (level 1) only merge with
        each other, so a bridge never connects to the road under it; its ends (merge_any) join anything."""
        cx, cy = int(x // NODE_CELL), int(y // NODE_CELL)
        best = None
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for n in self._node_grid.get((gx, gy), ()):
                    nx, ny = self.nodes[n]
                    d = math.hypot(nx - x, ny - y)
                    if d <= MERGE and (merge_any or self._levels[n] == level) and (best is None or d < best[0]):
                        best = (d, n)
        if best:
            return best[1]
        n = len(self.nodes)
        self.nodes.append((x, y))
        self._levels.append(level)
        self.out.append([])
        self._node_grid[(cx, cy)].append(n)
        return n

    def _add_edge(self, na, nb, rtype, width, kmh=None, name=""):
        if (na, nb) in self._edge_keys:
            return
        pa, pb = self.nodes[na], self.nodes[nb]
        if math.hypot(pb[0] - pa[0], pb[1] - pa[1]) < MIN_EDGE:
            return
        self._edge_keys.add((na, nb))
        self.out[na].append(len(self.edges))
        self.edges.append(Edge(na, nb, pa, pb, rtype, width, kmh, name))

    def _build(self, roads):
        segs = []                                # (road index, ax, ay, bx, by)
        road_segs = {}
        for ri, r in enumerate(roads):
            if r.get("service") in NO_AI_SERVICE:
                continue
            pts = r["points"]
            ids = []
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                if abs(bx - ax) + abs(by - ay) < 0.01:
                    continue
                ids.append(len(segs))
                segs.append((ri, ax, ay, bx, by))
            if ids:
                road_segs[ri] = ids

        grid = defaultdict(list)
        for si, (_ri, ax, ay, bx, by) in enumerate(segs):
            for c in _cells(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)):
                grid[c].append(si)

        splits = defaultdict(list)
        seen = set()
        for ids in grid.values():
            for i in range(len(ids)):
                si = ids[i]
                for j in range(i + 1, len(ids)):
                    sj = ids[j]
                    if (si, sj) in seen:
                        continue
                    seen.add((si, sj))
                    ri, rj = segs[si][0], segs[sj][0]
                    if ri == rj or _elevated(roads[ri]) != _elevated(roads[rj]):
                        continue
                    hit = _seg_intersect(segs[si][1:], segs[sj][1:])
                    if hit:
                        splits[si].append(hit[0])
                        splits[sj].append(hit[1])

        # T-junctions: join a road's end to the nearest other road within SNAP metres
        snaps = {}
        for ri, ids in road_segs.items():
            first, last = segs[ids[0]], segs[ids[-1]]
            for end, (px, py) in ((0, (first[1], first[2])), (1, (last[3], last[4]))):
                best = None
                cx, cy = int(px // CELL), int(py // CELL)
                for gx in (cx - 1, cx, cx + 1):
                    for gy in (cy - 1, cy, cy + 1):
                        for sj in grid.get((gx, gy), ()):
                            rj = segs[sj][0]
                            if rj == ri or _elevated(roads[ri]) != _elevated(roads[rj]):
                                continue
                            t, d, qx, qy = _project(px, py, *segs[sj][1:])
                            if d <= SNAP and (best is None or d < best[0]):
                                best = (d, sj, t, qx, qy)
                if best:
                    splits[best[1]].append(best[2])
                    snaps[(ri, end)] = (best[3], best[4])

        for ri, ids in road_segs.items():
            r = roads[ri]
            chain = []
            for k, si in enumerate(ids):
                _r, ax, ay, bx, by = segs[si]
                ts = sorted({round(t, 6) for t in splits.get(si, ()) if 1e-6 < t < 1 - 1e-6})
                pts = [(ax, ay)] + [(ax + (bx - ax) * t, ay + (by - ay) * t) for t in ts] + [(bx, by)]
                chain.extend(pts[1:] if chain else pts)
            if (ri, 0) in snaps:
                chain[0] = snaps[(ri, 0)]
            if (ri, 1) in snaps:
                chain[-1] = snaps[(ri, 1)]
            chain = _subdivide(chain)
            elev, last = _elevated(r), len(chain) - 1
            ids_n = [self._node_at(x, y, 1 if elev and 0 < k < last else 0, merge_any=elev and k in (0, last))
                     for k, (x, y) in enumerate(chain)]
            oneway = r.get("oneway", 0)
            rtype, width = r.get("type", "side"), r.get("width", 8)
            kmh, rname = r.get("speed"), r.get("name", "")
            for na, nb in zip(ids_n, ids_n[1:]):
                if na == nb:
                    continue
                if oneway >= 0:
                    self._add_edge(na, nb, rtype, width, kmh, rname)
                if oneway <= 0:
                    self._add_edge(nb, na, rtype, width, kmh, rname)

    # ---------------------------------------------------------------- queries
    def lane_point(self, eid, s):
        """(x, y, heading) of the driving lane at distance s along an edge."""
        e = self.edges[eid]
        return (e.ax - e.dy * e.lane + e.dx * s, e.ay + e.dx * e.lane + e.dy * s, math.atan2(e.dy, e.dx))

    def edges_near(self, x, y, r):
        """Edge ids whose midpoint is within r (+30 m slack) of a point."""
        reach = r + 30.0
        out = []
        for cx in range(int((x - reach) // CELL), int((x + reach) // CELL) + 1):
            for cy in range(int((y - reach) // CELL), int((y + reach) // CELL) + 1):
                for eid in self._edge_grid.get((cx, cy), ()):
                    e = self.edges[eid]
                    mx, my = (e.ax + e.bx) / 2 - x, (e.ay + e.by) / 2 - y
                    if mx * mx + my * my <= reach * reach:
                        out.append(eid)
        return out

    def random_spawn(self, x, y, rmin, rmax, rng, weights=None, tries=12):
        """A random (edge id, distance along edge) between rmin and rmax metres from (x, y)."""
        cands = self.edges_near(x, y, rmax)
        if not cands:
            return None
        w = [weights.get(self.edges[i].rtype, 1.0) + 0.001 for i in cands] if weights else None
        for _ in range(tries):
            eid = rng.choices(cands, w)[0] if w else rng.choice(cands)
            e = self.edges[eid]
            s = rng.uniform(0.1, 0.9) * e.length
            d = math.hypot(e.ax + e.dx * s - x, e.ay + e.dy * s - y)
            if rmin <= d <= rmax:
                return eid, s
        return None

    def nearest_node(self, x, y, max_r=80.0, heading=None):
        """Nearest node within max_r. With a heading, nodes behind the car count BEHIND_PENALTY further away, so a car that just passed a node does not turn back for it."""
        best, best_score = None, 1e18
        k = int(max_r // CELL) + 1
        cx, cy = int(x // CELL), int(y // CELL)
        fx = fy = 0.0
        if heading is not None:
            fx, fy = math.cos(heading), math.sin(heading)
        for gx in range(cx - k, cx + k + 1):
            for gy in range(cy - k, cy + k + 1):
                for n in self._coarse.get((gx, gy), ()):
                    nx, ny = self.nodes[n]
                    dx, dy = nx - x, ny - y
                    d = math.hypot(dx, dy)
                    if d > max_r:
                        continue
                    score = d + (BEHIND_PENALTY if heading is not None and dx * fx + dy * fy < 0 else 0.0)
                    if score < best_score:
                        best, best_score = n, score
        return best

    def choose_next(self, eid, rng):
        """Pick the edge to take after eid: favours going straight, avoids U-turns unless at a dead end."""
        e = self.edges[eid]
        cands = self.out[e.b]
        fwd = [c for c in cands if self.edges[c].b != e.a] or list(cands)
        if not fwd:
            return None
        weights = []
        for c in fwd:
            n = self.edges[c]
            w = 0.5 + 1.5 * max(0.0, e.dx * n.dx + e.dy * n.dy)
            if n.rtype == "lane":
                w *= 0.4
            weights.append(w)
        return rng.choices(fwd, weights)[0]

    def shortest_path(self, src, dst, max_expand=6000):
        """A* over the road graph. Returns a list of node ids from src to dst, or None."""
        if src == dst:
            return [src]
        dxy = self.nodes[dst]

        def h(n):
            x, y = self.nodes[n]
            return math.hypot(x - dxy[0], y - dxy[1])

        best = {src: 0.0}
        came = {}
        heap = [(h(src), 0.0, src)]
        expanded = 0
        while heap and expanded < max_expand:
            _f, g, n = heapq.heappop(heap)
            if g > best.get(n, 1e18):
                continue
            if n == dst:
                path = [n]
                while n in came:
                    n = came[n]
                    path.append(n)
                return path[::-1]
            expanded += 1
            for eid in self.out[n]:
                e = self.edges[eid]
                ng = g + e.length * (1.3 if e.rtype == "lane" else 1.0)
                if ng < best.get(e.b, 1e18):
                    best[e.b] = ng
                    came[e.b] = n
                    heapq.heappush(heap, (ng + h(e.b), ng, e.b))
        return None
