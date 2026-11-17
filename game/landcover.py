"""Real woods: scatter trees inside the land cover polygons from data/landcover.json (see tools/fetch_landcover.py)."""
import json
import math
import os
from collections import defaultdict

import numpy as np

from .world import point_in_polygon

LANDCOVER_NAME = "landcover.json"
CELL = 8.0            # metres between tree sites (each jittered), roughly one tree per 64 m2
MAX_WOOD_TREES = 6000
INDEX_CELL = 320.0    # coarse grid of the woods polygons: a prop cell only tests the woods overlapping its square
MIN_GAP = 5.0         # no two woods trees closer than this (the same rule as game.props.MIN_GAP)


def load_beside(map_path):
    """List of woods (each with "rings" and a "bbox") next to the map, or []."""
    path = os.path.join(os.path.dirname(os.path.abspath(map_path)), LANDCOVER_NAME)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        woods = json.load(f).get("woods", [])
    for w in woods:
        xs = [p[0] for p in w["rings"][0]]
        ys = [p[1] for p in w["rings"][0]]
        w["bbox"] = (min(xs), min(ys), max(xs), max(ys))
    return woods


def inside(w, x, y):
    x0, y0, x1, y1 = w["bbox"]
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    if not point_in_polygon(x, y, w["rings"][0]):
        return False
    return not any(point_in_polygon(x, y, hole) for hole in w["rings"][1:])


def sites(woods, rng, limit=MAX_WOOD_TREES, centre=None):
    """Jittered grid points inside the woods. With a `centre`, the woods nearest to it are planted first, so the
    tree budget goes to the land around town rather than to distant forest nobody drives to."""
    out = []
    if centre is not None:
        cx, cy = centre
        woods = sorted(woods, key=lambda w: math.hypot((w["bbox"][0] + w["bbox"][2]) / 2 - cx,
                                                       (w["bbox"][1] + w["bbox"][3]) / 2 - cy))
    for w in woods:
        x0, y0, x1, y1 = w["bbox"]
        y = y0
        while y < y1:
            x = x0
            while x < x1:
                px, py = x + rng.uniform(0.0, CELL), y + rng.uniform(0.0, CELL)
                if inside(w, px, py):
                    out.append((px, py))
                    if len(out) >= limit:
                        return out
                x += CELL
            y += CELL
    return out


# --- streamed woods -------------------------------------------------------------------------------------------
# The woods cover far more ground than any up-front prop budget, so World makes their trees one prop-grid cell at a
# time, the first time something asks for props there (World.props_near). Every candidate site comes from a hash of
# its place on a global CELL-metre lattice, so a cell gets the same trees whatever order the cells are made in.

_MASK = 0xFFFFFFFFFFFFFFFF


def _mix(z):
    """splitmix64 finaliser on a Python int."""
    z = (z + 0x9E3779B97F4A7C15) & _MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
    return z ^ (z >> 31)


_U = 1.0 / (1 << 53)


def site(i, j, seed=1, salt=None):
    """The candidate tree site of lattice square (i, j): (x, y, priority, hash)."""
    h1 = _mix(((i & 0xFFFFFFFF) << 32 | (j & 0xFFFFFFFF)) ^ (_mix(seed) if salt is None else salt))
    h2 = _mix(h1)
    h3 = _mix(h2)
    return (i + (h1 >> 11) * _U) * CELL, (j + (h2 >> 11) * _U) * CELL, (h3 >> 11) * _U, h3


def thinned(i0, j0, n, seed=1):
    """Lattice sites in the n x n block at (i0, j0) that survive the spacing rule: a site is dropped when a
    neighbouring site with a lower priority stands within MIN_GAP (whether or not that one is kept). The rule only
    looks at the sites themselves, so it gives the same answer for a site whichever block it is computed in, and no
    two survivors are ever closer than MIN_GAP. Returns a list of (x, y, priority, hash)."""
    m = n + 2
    salt = _mix(seed)
    grid = [site(i, j, seed, salt) for j in range(j0 - 1, j0 + n + 1) for i in range(i0 - 1, i0 + n + 1)]
    g2 = MIN_GAP * MIN_GAP
    out = []
    for j in range(1, n + 1):
        for i in range(1, n + 1):
            x, y, p, h = grid[j * m + i]
            for k in (j * m + i - m - 1, j * m + i - m, j * m + i - m + 1, j * m + i - 1, j * m + i + 1,
                      j * m + i + m - 1, j * m + i + m, j * m + i + m + 1):
                q = grid[k]
                if q[2] < p and (q[0] - x) ** 2 + (q[1] - y) ** 2 < g2:
                    break
            else:
                out.append((x, y, p, h))
    return out


def ring_edges(rings):
    """Every edge of a polygon's rings (outer and holes) as numpy arrays, for inside_edges."""
    ax, ay, bx, by = [], [], [], []
    for ring in rings:
        pts = np.asarray(ring, dtype=np.float64)
        nxt = np.roll(pts, -1, axis=0)
        ax.append(pts[:, 0]); ay.append(pts[:, 1]); bx.append(nxt[:, 0]); by.append(nxt[:, 1])
    ax, ay, bx, by = (np.concatenate(a) for a in (ax, ay, bx, by))
    return ax, ay, bx, by, np.minimum(ay, by), np.maximum(ay, by), np.maximum(ax, bx)


def inside_edges(edges, px, py, y0, y1, x0):
    """Even-odd point-in-polygon for many points at once (the same rule as world.point_in_polygon; holes count
    as outside). All points must lie within y0..y1 and right of x0, so only the edges a ray to +x from that strip
    can cross are tested."""
    ax, ay, bx, by, lo, hi, mx = edges
    sel = (hi > y0) & (lo <= y1) & (mx >= x0)
    if not sel.any():
        return np.zeros(len(px), dtype=bool)
    ax, ay, bx, by = ax[sel], ay[sel], bx[sel], by[sel]
    Y = py[:, None]
    crosses = (ay > Y) != (by > Y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xc = (bx - ax) * (Y - ay) / (by - ay) + ax
    return ((crosses & (px[:, None] < xc)).sum(axis=1) & 1).astype(bool)


class WoodsIndex:
    """The woods polygons on a coarse INDEX_CELL grid, with every ring's edges as numpy arrays for fast
    point-in-woods tests of a whole cell's sites at once."""

    def __init__(self, woods):
        self.woods = woods
        self.grid = defaultdict(list)
        self.edges = []
        for k, w in enumerate(woods):
            x0, y0, x1, y1 = w["bbox"]
            for gx in range(int(x0 // INDEX_CELL), int(x1 // INDEX_CELL) + 1):
                for gy in range(int(y0 // INDEX_CELL), int(y1 // INDEX_CELL) + 1):
                    self.grid[(gx, gy)].append(k)
            self.edges.append(ring_edges(w["rings"]))

    def candidates(self, x0, y0, x1, y1):
        """Indices of woods whose bbox overlaps the rectangle."""
        out = []
        for k in self.grid.get((int(x0 // INDEX_CELL), int(y0 // INDEX_CELL)), ()):
            bx0, by0, bx1, by1 = self.woods[k]["bbox"]
            if bx1 >= x0 and bx0 <= x1 and by1 >= y0 and by0 <= y1:
                out.append(k)
        if int(x0 // INDEX_CELL) != int(x1 // INDEX_CELL) or int(y0 // INDEX_CELL) != int(y1 // INDEX_CELL):
            seen = set(out)
            for gx in range(int(x0 // INDEX_CELL), int(x1 // INDEX_CELL) + 1):
                for gy in range(int(y0 // INDEX_CELL), int(y1 // INDEX_CELL) + 1):
                    for k in self.grid.get((gx, gy), ()):
                        if k not in seen:
                            seen.add(k)
                            bx0, by0, bx1, by1 = self.woods[k]["bbox"]
                            if bx1 >= x0 and bx0 <= x1 and by1 >= y0 and by0 <= y1:
                                out.append(k)
        return out

    def inside(self, k, px, py, y0, y1, x0):
        """Boolean array: which of the points (px, py), all within y0..y1 and right of x0, are inside wood k."""
        return inside_edges(self.edges[k], px, py, y0, y1, x0)

    def sites(self, x0, y0, size, seed=1):
        """Woods tree sites in the square cell (x0, y0)-(x0+size, y0+size) (x0, y0 multiples of CELL):
        list of (x, y, hash) in priority order, best first."""
        ks = self.candidates(x0, y0, x0 + size, y0 + size)
        if not ks:
            return []
        n = int(round(size / CELL))
        cand = thinned(int(round(x0 / CELL)), int(round(y0 / CELL)), n, seed)
        if not cand:
            return []
        px = np.array([c[0] for c in cand])
        py = np.array([c[1] for c in cand])
        mask = np.zeros(len(cand), dtype=bool)
        for k in ks:
            todo = ~mask
            if not todo.any():
                break
            mask[todo] |= self.inside(k, px[todo], py[todo], y0, y0 + size, x0)
        kept = sorted((c for c, m in zip(cand, mask) if m), key=lambda c: c[2])
        return [(c[0], c[1], c[3]) for c in kept]
