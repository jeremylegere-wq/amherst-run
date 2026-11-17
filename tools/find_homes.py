#!/usr/bin/env python3
"""Find the real house at civic addresses that OpenStreetMap has no building for, from the LiDAR roof surface.

Used by tools/extend_map.py for the rural areas around town, where OSM maps few buildings but every home has a civic
point (data/addresses.json). Around each point the 1 m LiDAR height above ground (DSM - DTM, NRCan HRDEM, the same
tiles as tools/fetch_heights.py) is checked for roof: cells 2.2-12 m up whose surface is locally planar (tree crowns
are rough). Touching roof cells make a blob; the nearest blob of house size is the home, other blobs belonging to the
same address become sheds, garages and barns. Each blob becomes a rectangle along its own long axis.

    python tools/find_homes.py --box 2500 -8000 13000 6000      # report what would be found (map metres)
"""
import argparse
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cog  # noqa: E402
import fetch_heights as FH  # noqa: E402

SEARCH = 48.0           # metres around a civic point
STEP = 1.0              # LiDAR is 1 m
ROOF_MIN, ROOF_MAX = 2.2, 12.0
FLAT_TOL = 0.35         # metres: largest second difference a roof cell may have (a ridge breaks it; closing heals it)
HOME_AREA = (45.0, 700.0)
SHED_AREA = 14.0
OUTBUILDING_AREA = 20.0  # m2: smallest shed, garage or barn kept (a home can be from HOME_AREA[0])
SHED_TOP, HOME_TOP, BARN_AREA = 5.0, 9.0, 60.0   # median roof height limits (m); barns are big outbuildings
TREE_EDGE_HOME, TREE_EDGE_SHED = 0.35, 0.12   # most share of taller ground around a blob (stands_clear)
MIN_FILL = 0.55         # blob area / its rectangle: lower is a tree clump, not a building
EMPTY_RADIUS = 30.0     # an address with a map building this close already has its home


def roof_mask(h):
    """Cells that look like roof: high enough, not too high, and locally planar."""
    h0 = np.nan_to_num(h, nan=0.0)
    m = np.zeros(h.shape, bool)
    dxx = np.abs(h0[1:-1, 2:] - 2 * h0[1:-1, 1:-1] + h0[1:-1, :-2])
    dyy = np.abs(h0[2:, 1:-1] - 2 * h0[1:-1, 1:-1] + h0[:-2, 1:-1])
    m[1:-1, 1:-1] = (dxx < FLAT_TOL) & (dyy < FLAT_TOL)
    high = (h0 > ROOF_MIN) & (h0 < ROOF_MAX)
    m = close(m & high)
    return m | (_shift_or(m) & high)                     # the eave cells (next to the drop) fail the planar test


def _shift_or(m):
    out = m.copy()
    out[1:, :] |= m[:-1, :]
    out[:-1, :] |= m[1:, :]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def close(m):
    """Binary closing (grow one cell, shrink one cell): joins the two halves of a roof split along its ridge."""
    grown = _shift_or(m)
    return ~_shift_or(~grown)


def blobs(m):
    """Lists of (row, col) for each 4-connected group of True cells."""
    seen = np.zeros(m.shape, bool)
    out = []
    rows, cols = m.shape
    for r0, c0 in zip(*np.nonzero(m)):
        if seen[r0, c0]:
            continue
        stack, cells = [(r0, c0)], []
        seen[r0, c0] = True
        while stack:
            r, c = stack.pop()
            cells.append((r, c))
            for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= rr < rows and 0 <= cc < cols and m[rr, cc] and not seen[rr, cc]:
                    seen[rr, cc] = True
                    stack.append((rr, cc))
        out.append(cells)
    return out


def rectangle(xs, ys):
    """(centre, long-axis angle, length, width, fill) of the rectangle around points along their main axis."""
    cx, cy = xs.mean(), ys.mean()
    if len(xs) < 3:
        return None
    w, v = np.linalg.eigh(np.cov(np.vstack([xs - cx, ys - cy])))
    ang = math.atan2(v[1, 1], v[0, 1])
    ca, sa = math.cos(ang), math.sin(ang)
    u = (xs - cx) * ca + (ys - cy) * sa
    t = -(xs - cx) * sa + (ys - cy) * ca
    u0, u1 = np.percentile(u, 2), np.percentile(u, 98)
    t0, t1 = np.percentile(t, 2), np.percentile(t, 98)
    length, width = u1 - u0 + STEP, t1 - t0 + STEP
    mu, mt = (u0 + u1) / 2, (t0 + t1) / 2
    centre = (cx + mu * ca - mt * sa, cy + mu * sa + mt * ca)
    return centre, ang, length, width, len(xs) * STEP * STEP / max(1e-6, length * width)


def corners(centre, ang, length, width):
    ca, sa = math.cos(ang), math.sin(ang)
    out = []
    for du, dt in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        u, t = du * length / 2, dt * width / 2
        out.append([round(centre[0] + u * ca - t * sa, 1), round(centre[1] + u * sa + t * ca, 1)])
    return out


def window(x, y, dsm, dtm, lat0, lon0, r=SEARCH):
    gx, gy = np.meshgrid(np.arange(x - r, x + r, STEP), np.arange(y - r, y + r, STEP))
    X, Y = FH.to_3979(gx.ravel(), gy.ravel(), lat0, lon0)
    hag = (dsm.sample(X, Y) - dtm.sample(X, Y)).reshape(gx.shape)
    return gx, gy, hag


class _Grid:
    """Points or polygons bucketed by 50 m cells, for 'what is near here' questions."""

    def __init__(self, cell=50.0):
        self.cell, self.cells = cell, {}

    def add(self, x, y, item):
        self.cells.setdefault((int(x // self.cell), int(y // self.cell)), []).append(item)

    def near(self, x, y):
        i, j = int(x // self.cell), int(y // self.cell)
        return [it for di in (-1, 0, 1) for dj in (-1, 0, 1) for it in self.cells.get((i + di, j + dj), ())]


def stands_clear(mask_cells, hag, shape):
    """Share of the ground 1-2 m around a blob that is taller than the blob's roof: high for a patch of tree crown
    (it sits against taller canopy), low for a building (yard or lawn around it)."""
    m = np.zeros(shape, bool)
    rr, cc = np.array(mask_cells).T
    m[rr, cc] = True
    ring = _shift_or(_shift_or(m)) & ~m
    top = np.nanmax(hag[rr, cc])
    around = np.nan_to_num(hag[ring], nan=0.0)
    return float(np.mean(around > top + 0.5)) if around.size else 1.0


def find(addresses, lat0, lon0, dsm, dtm, taken=(), everyone=None, log=print):
    """Buildings for the civic points `addresses` ([x, y, number, street]). `taken` = points of footprints already on
    the map (a blob over one is skipped); `everyone` = all civic points (a roof nearer another one is theirs).
    Returns building dicts."""
    owners = _Grid(100.0)
    for a in everyone or addresses:
        owners.add(a[0], a[1], a)
    used = _Grid()
    for p in taken:
        used.add(p[0][0], p[0][1], p)                    # near() looks one 50 m cell around: footprints are smaller
    found, homes = [], 0
    for k, (ax, ay, num, street) in enumerate(addresses):
        gx, gy, hag = window(ax, ay, dsm, dtm, lat0, lon0)
        if not np.isfinite(hag).any():
            continue
        best, sheds = None, []
        for cells in blobs(roof_mask(hag)):
            area = len(cells) * STEP * STEP
            if area < SHED_AREA:
                continue
            rr, cc = np.array(cells).T
            rect = rectangle(gx[rr, cc], gy[rr, cc])
            if rect is None or rect[4] < MIN_FILL:
                continue
            centre = rect[0]
            box = corners(*rect[:4])
            if any(_overlaps(box, p) for p in used.near(*centre)):
                continue
            nearest = min(owners.near(*centre) or [[ax, ay, num, street]],
                          key=lambda a: (a[0] - centre[0]) ** 2 + (a[1] - centre[1]) ** 2)
            if nearest[2:] != [num, street]:
                continue                                 # this roof belongs to the neighbours
            home = HOME_AREA[0] <= area <= HOME_AREA[1]
            mid = float(np.nanmedian(hag[rr, cc]))
            if mid > (HOME_TOP if home or area >= BARN_AREA else SHED_TOP):
                continue                                 # too tall for its size: a hedgerow or tree clump
            if stands_clear(cells, hag, hag.shape) > (TREE_EDGE_HOME if home else TREE_EDGE_SHED):
                continue                                 # a flat-topped patch of tree crown
            d = math.dist(centre, (ax, ay))
            if home and (best is None or d < best[0]):
                if best:
                    sheds.append(best[1])
                best = (d, rect)
            elif area >= OUTBUILDING_AREA and area <= HOME_AREA[1] * 1.5:
                sheds.append(rect)
        for rect, home in ([(best[1], True)] if best else []) + [(s, False) for s in sheds]:
            centre, ang, length, width, _fill = rect
            box = corners(centre, ang, length, width)
            if any(_overlaps(box, p) for p in used.near(*centre)):
                continue                                 # touches the home just added (an attached garage)
            b = {"points": box,
                 "tags": {"building": "house" if home else "shed", "source": "lidar"}}
            found.append(b)
            used.add(b["points"][0][0], b["points"][0][1], b["points"])
            homes += home
        if (k + 1) % 100 == 0:
            log("  looked at %d / %d civic points: %d homes" % (k + 1, len(addresses), homes))
    log("LiDAR homes: %d homes and %d outbuildings at %d civic points" % (homes, len(found) - homes, len(addresses)))
    return found


def _overlaps(a, b):
    """True when two footprints overlap (a corner or the middle of one inside the other, or edges crossing)."""
    mid = lambda p: (sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p))   # noqa: E731
    if any(_inside(q, b) for q in a + [mid(a)]) or any(_inside(q, a) for q in b + [mid(b)]):
        return True
    for p0, p1 in zip(a, a[1:] + a[:1]):
        for q0, q1 in zip(b, b[1:] + b[:1]):
            if _cross(p0, p1, q0, q1):
                return True
    return False


def _cross(p0, p1, q0, q1):
    d = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])   # noqa: E731
    return d(p0, p1, q0) * d(p0, p1, q1) < 0 and d(q0, q1, p0) * d(q0, q1, p1) < 0


def _inside(pt, poly):
    x, y = pt
    hit = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def empty_addresses(data, addresses, box):
    """Civic points inside box (x0, y0, x1, y1) with no map building within EMPTY_RADIUS."""
    cell = EMPTY_RADIUS
    grid = {}
    for b in data["buildings"]:
        pts = b["points"]
        c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        grid.setdefault((int(c[0] // cell), int(c[1] // cell)), []).append(c)
    out = []
    for a in addresses:
        if not (box[0] <= a[0] <= box[2] and box[1] <= a[1] <= box[3]):
            continue
        i, j = int(a[0] // cell), int(a[1] // cell)
        near = [c for di in (-1, 0, 1) for dj in (-1, 0, 1) for c in grid.get((i + di, j + dj), ())]
        if all(math.dist(c, a[:2]) > EMPTY_RADIUS for c in near):
            out.append(a)
    return out


def open_grids(cache=os.path.join(ROOT, "data", ".lidar_cache")):
    return (cog.COG(FH.BASE % "dsm", cache_dir=os.path.join(cache, "dsm"), name="dsm"),
            cog.COG(FH.BASE % "dtm", cache_dir=os.path.join(cache, "dtm"), name="dtm"))


def homes_for(data, box, log=print):
    """Add LiDAR-found homes for the empty civic points in box to data["buildings"]. Returns how many were added."""
    path = os.path.join(ROOT, "data", "addresses.json")
    if not os.path.exists(path):
        log("no data/addresses.json: no homes added")
        return 0
    with open(path, encoding="utf-8") as f:
        addresses = json.load(f)["points"]
    todo = empty_addresses(data, addresses, box)
    dsm, dtm = open_grids()
    m = data["meta"]
    squares = [[[a[0] - SEARCH, a[1] - SEARCH], [a[0] + SEARCH, a[1] + SEARCH]] for a in todo]
    tiles = FH.needed_tiles(squares, dsm, m["origin_lat"], m["origin_lon"], margin=2)
    log("%d civic points without a building need %d LiDAR tiles from each model" % (len(todo), len(tiles)))
    FH.prefetch(dsm, tiles, 8, log)
    FH.prefetch(dtm, tiles, 8, log)
    new = find(todo, m["origin_lat"], m["origin_lon"], dsm, dtm, taken=[b["points"] for b in data["buildings"]],
               everyone=addresses, log=log)
    data["buildings"].extend(new)
    return len(new)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--box", nargs=4, type=float, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--out", help="write the map with the homes added here (default: only report)")
    args = ap.parse_args(argv)
    with open(args.map) as f:
        data = json.load(f)
    n = homes_for(data, args.box)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print("wrote %s (+%d buildings)" % (args.out, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
