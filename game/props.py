"""Street props: trees and lamp posts.

Props come from two places:
  * OpenStreetMap nodes (natural=tree, highway=street_lamp) that the converter keeps, and
  * procedural placement along every street: trees on the verge beyond the sidewalk,
    lamp posts at the sidewalk edge of main roads.
Everything is seeded, so the same map always gets the same props.

A prop is a dict: kind ("tree" or "lamp"), x, y, h (height m), r (canopy radius m),
cr (collision radius m), c (colour variant), and for lamps dx, dy (direction the lamp arm points).
"""
import math
import random

import numpy as np

from . import streetdetail
from .world import point_in_polygon

TREE_SPACING = 16.0       # average metres between trees along a street side
LAMP_SPACING = 34.0
MIN_GAP = 5.0             # no two props closer than this
TREE_CLEAR = 2.2          # trees stay this far from any road edge (clear of the 1.8 m sidewalk)
LAMP_CLEAR = 0.9
MAX_PROPS = 17500
WOODS_CELL_CAP = 8        # most streamed woods trees in one 40 m prop cell (~1 per 200 m2: a deep wood fills the
                          # 130 m draw radius with ~300 trees, about what the renderer can afford)
WOODS_CLEAR = 1.5         # woods trees keep this far from a road edge
LIDAR_CLEAR = 1.5           # metres from a road edge a real (LiDAR) tree may stand: street trees are close to the curb
LIDAR_MAX_H = 24.0          # metres: the tallest real tree drawn
LIDAR_HOUSE_GAP = 3.0       # metres a real tree keeps from a building (OSM outlines sit ~3 m off the LiDAR roofs)
MONUMENTS = {"cenotaph": (6.0, 1.4), "lighthouse": (10.6, 1.6)}   # kind -> (height, radius)
SCENERY = {"horse": (2.2, 1.2, 0.9), "gravestone": (0.9, 0.4, 0.3), "fence": (1.3, 0.0, 0.0),
           "dam": (7.0, 0.0, 0.0), "pole": (9.5, 0.2, 0.16), "tower": (24.0, 0.0, 1.2)}   # kind -> (h, r, cr)
FENCE_PIECE = 4.0          # metres: long fences are cut into pieces so each sorts where it really is
TREE_PROB = {"main": 0.6, "side": 0.7, "lane": 0.35}


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class _Spacing:
    """Grid that answers 'is there already a prop within MIN_GAP of here?'."""

    def __init__(self):
        self.cells = {}

    def free(self, x, y):
        cx, cy = int(x // MIN_GAP), int(y // MIN_GAP)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for px, py in self.cells.get((gx, gy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < MIN_GAP * MIN_GAP:
                        return False
        return True

    def add(self, x, y):
        self.cells.setdefault((int(x // MIN_GAP), int(y // MIN_GAP)), []).append((x, y))


def _site_ok(world, x, y, clear, radius, water=None, rails=None):
    """Can a prop of this footprint stand at (x, y)? `water` and `rails` narrow the lists searched (for a caller
    that already knows which ones are near)."""
    if not world.in_bounds(x, y, margin=-2.0):
        return False
    if world.road_clearance(x, y) < clear:
        return False
    for ox, oy in ((0, 0), (radius, 0), (-radius, 0), (0, radius), (0, -radius)):
        if world.in_building(x + ox, y + oy):
            return False
    return _clear_of(x, y, world.water if water is None else water, world.rails if rails is None else rails)


def _clear_of(x, y, water, rails):
    """True when (x, y) is not in any of the water polygons and more than 4 m from the rail lines."""
    for w in water:
        x0, y0, x1, y1 = w["bbox"]
        if x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2 and point_in_polygon(x, y, w["points"]):
            return False
    for r in rails:
        x0, y0, x1, y1 = r["bbox"]
        if x0 - 5 <= x <= x1 + 5 and y0 - 5 <= y <= y1 + 5:
            pts = r["points"]
            if any(_seg_dist(x, y, a[0], a[1], b[0], b[1]) < 4.0 for a, b in zip(pts, pts[1:])):
                return False
    return True


def _tree(rng, x, y):
    h = rng.uniform(4.5, 7.5)
    return {"kind": "tree", "x": round(x, 2), "y": round(y, 2), "h": round(h, 2),
            "r": round(rng.uniform(1.7, 2.7), 2), "cr": 0.4, "c": rng.randrange(3)}


def _lamp(x, y, dx, dy):
    return {"kind": "lamp", "x": round(x, 2), "y": round(y, 2), "h": 6.0, "r": 0.3, "cr": 0.18,
            "c": 0, "dx": dx, "dy": dy}


def _scenery(p):
    """Hand-placed horse, gravestone or fence: defaults filled in; a fence (x, y) -> (x2, y2) cut into pieces."""
    h, r, cr = SCENERY[p["kind"]]
    base = {"h": h, "r": r, "cr": cr, "c": 0}
    base.update({k: v for k, v in p.items() if not k.startswith("_")})
    if "bearing" in base:                                    # compass degrees the front faces -> map heading
        b = math.radians(base.pop("bearing"))
        base["heading"] = round(math.atan2(-math.cos(b), math.sin(b)), 4)
    if p["kind"] == "dam":                                  # solid along its crest (invisible car_block circles)
        fx, fy = math.cos(base.get("heading", 0.0)), math.sin(base.get("heading", 0.0))
        half = base.get("length", 50.0) / 2.0
        out = [base]
        b = -half
        while b <= half:
            out.append({"kind": "car_block", "x": base["x"] - fx * 0.8 - fy * b, "y": base["y"] - fy * 0.8 + fx * b,
                        "h": 0.0, "r": 0.0, "cr": 1.5})
            b += 2.5
        return out
    if p["kind"] != "fence":
        return [base]
    x0, y0, x1, y1 = float(p["x"]), float(p["y"]), float(p["x2"]), float(p["y2"])
    L = math.hypot(x1 - x0, y1 - y0)
    n = max(1, math.ceil(L / FENCE_PIECE))
    out = []
    for k in range(n):
        ax, ay = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
        bx, by = x0 + (x1 - x0) * (k + 1) / n, y0 + (y1 - y0) * (k + 1) / n
        out.append(dict(base, x=round((ax + bx) / 2, 2), y=round((ay + by) / 2, 2),
                        a=[round(ax, 2), round(ay, 2)], b=[round(bx, 2), round(by, 2)], last=k == n - 1))
    return out


def build_props(world, osm_props=(), seed=1, procedural=True):
    """Return the list of props for a world (OSM ones first, then procedural). Hand-placed and mapped scenery (poles,
    gravestones, fences, the dam...) is extra: it does not use up the MAX_PROPS budget the street trees fill."""
    rng = random.Random(seed * 7919 + 3)
    spacing = _Spacing()
    props = []
    fixed = []

    for p in osm_props:
        x, y = float(p["x"]), float(p["y"])
        kind = p.get("kind")
        if kind == "tree" and _site_ok(world, x, y, 0.4, 0.8) and spacing.free(x, y):
            t = _tree(rng, x, y)
            t.update({k: p[k] for k in ("h", "r", "c", "leaf") if k in p})  # a hand-placed tree keeps its size
            props.append(t)
        elif kind in SCENERY:                                                # hand-placed scenery (map_edits.json)
            fixed.extend(_scenery(p))
            continue
        elif kind == "lamp" and _site_ok(world, x, y, 0.2, 0.2) and spacing.free(x, y):
            props.append(_lamp(x, y, 0.0, 0.0))
        elif kind in streetdetail.FURNITURE_KINDS and "h" in p:             # signs, signals, hydrants... made from map marks
            props.append(dict(p))
        elif kind in MONUMENTS and _site_ok(world, x, y, 0.3, 1.2) and spacing.free(x, y):
            h, r = MONUMENTS[kind]
            m = {"kind": kind, "x": round(x, 2), "y": round(y, 2), "h": h, "r": r, "cr": r,
                 "c": 0, "label": p.get("label", "")}
            m.update({k: p[k] for k in ("site", "heading") if k in p})
            props.append(m)
        else:
            continue
        spacing.add(x, y)

    if not procedural:
        return props + fixed

    # hydrants, benches and bins first, so the trees (which fill the prop budget) leave room for them
    props.extend(streetdetail.furniture(world, rng, spacing.free,
                                        lambda x, y, clear, rad: _site_ok(world, x, y, clear, rad), spacing.add))

    real = getattr(world, "lidar_trees", None)
    for r in world.roads:
        if len(props) >= MAX_PROPS:
            break
        hw = r["width"] / 2.0
        prob = TREE_PROB.get(r["type"], 0.5)
        pts = r["points"]
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 1.0:
                continue
            dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, ny = -dy, dx
            # trees on both verges
            s = rng.uniform(0.0, TREE_SPACING)
            while s < L:
                for side in (-1.0, 1.0):
                    if rng.random() > prob:
                        continue
                    off = (hw + rng.uniform(2.8, 4.2)) * side
                    x, y = a[0] + dx * s + nx * off, a[1] + dy * s + ny * off
                    if real is not None and real.covered(x, y):
                        continue                             # the LiDAR survey's own trees stand here instead
                    if spacing.free(x, y) and _site_ok(world, x, y, TREE_CLEAR, 1.2):
                        props.append(_tree(rng, x, y))
                        spacing.add(x, y)
                s += TREE_SPACING * rng.uniform(0.75, 1.3)
            # lamp posts on one side of main roads, arm reaching over the road
            if r["type"] == "main":
                s = rng.uniform(0.0, LAMP_SPACING)
                while s < L:
                    off = hw + 1.2
                    x, y = a[0] + dx * s + nx * off, a[1] + dy * s + ny * off
                    if spacing.free(x, y) and _site_ok(world, x, y, LAMP_CLEAR, 0.3):
                        props.append(_lamp(x, y, -nx, -ny))
                        spacing.add(x, y)
                    s += LAMP_SPACING
    # the real woods (land cover) are not planted here: World streams them per cell (woods_cell below)
    return props[:MAX_PROPS] + fixed


def _near(items, x0, y0, x1, y1, pad):
    out = []
    for it in items:
        bx0, by0, bx1, by1 = it["bbox"]
        if bx1 + pad >= x0 and bx0 - pad <= x1 and by1 + pad >= y0 and by0 - pad <= y1:
            out.append(it)
    return out


def _tree_from_hash(h, x, y):
    """A woods tree whose looks come from its site hash (as _tree does from an rng, without seeding one)."""
    u = [((h >> s) & 0xFFFF) / 65536.0 for s in (0, 16, 32)]
    return {"kind": "tree", "x": round(x, 2), "y": round(y, 2), "h": round(4.5 + 3.0 * u[0], 2),
            "r": round(1.7 + 1.0 * u[1], 2), "cr": 0.4, "c": int(u[2] * 3)}


def woods_cell(world, index, cx, cy, size, existing, seed=1):
    """Trees for one prop-grid cell (cx, cy) of the world grid (`size` = game.world.CELL metres) from the woods
    index (game.landcover.WoodsIndex). `existing(x, y)` is true when a prop already stands within MIN_GAP (hand
    trees, street trees, lamps...). Applies the same checks as _site_ok, with the road and building tests done for
    the whole cell at once. Deterministic: the same cell always gets the same trees, whatever was made before it."""
    x0, y0 = cx * size, cy * size
    sites = index.sites(x0, y0, size, seed)
    return _plant(world, sites, cx, cy, size, existing, _tree_from_hash, WOODS_CLEAR, 1.2)


def lidar_cell(world, trees, cx, cy, size, existing):
    """Real trees (game.lidar_trees.LidarTrees) for prop cell (cx, cy): the survey's tree tops, tallest first, with
    the same checks as the woods (not on roads, buildings, water or rails, not crowding another prop)."""
    return _plant(world, trees.in_cell(cx, cy), cx, cy, size, existing, _tree_from_lidar, LIDAR_CLEAR, LIDAR_HOUSE_GAP)


def _tree_from_lidar(h, x, y):
    """A tree of the real height (capped), its crown growing with it; the colour comes from its position."""
    k = int(x * 7.0 + y * 13.0) & 0xFFFF
    hh = min(LIDAR_MAX_H, max(3.0, h))
    return {"kind": "tree", "x": round(x, 2), "y": round(y, 2), "h": round(hh, 2),
            "r": round(min(5.0, max(1.6, 0.8 + 0.22 * hh)), 2), "cr": 0.45, "c": k % 3}


def _plant(world, sites, cx, cy, size, existing, make, clear, gap):
    """Keep the sites [(x, y, data)] of prop cell (cx, cy) that are clear of roads (`clear` m), buildings, water, rails
    and other props, and make a tree of each with make(data, x, y)."""
    if not sites:
        return []
    x0, y0 = cx * size, cy * size
    x1, y1 = x0 + size, y0 + size
    px = np.array([s[0] for s in sites])
    py = np.array([s[1] for s in sites])
    bx0, by0, bx1, by1 = world.bounds
    ok = (px >= bx0 + 2.0) & (px <= bx1 - 2.0) & (py >= by0 + 2.0) & (py <= by1 - 2.0)
    segs = [sg for gx in (cx - 1, cx, cx + 1) for gy in (cy - 1, cy, cy + 1)
            for sg in world._road_grid.get((gx, gy), ())]             # what road_clearance looks at in this cell
    if segs:
        ax, ay, bx, by, w = (np.array(c) for c in zip(*segs))
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        L[L == 0] = 1e-12
        t = np.clip(((px[:, None] - ax) * dx + (py[:, None] - ay) * dy) / L, 0.0, 1.0)
        d = np.hypot(px[:, None] - (ax + t * dx), py[:, None] - (ay + t * dy)) - w / 2.0
        ok &= d.min(axis=1) >= clear
    if not ok.any():
        return []
    blds = set()
    for gx in (cx - 1, cx, cx + 1):
        for gy in (cy - 1, cy, cy + 1):
            blds.update(world._bld_grid.get((gx, gy), ()))
    boxes = [world.buildings[i]["bbox"] for i in blds]
    boxes = [b for b in boxes if b[2] >= x0 - gap and b[0] <= x1 + gap and b[3] >= y0 - gap and b[1] <= y1 + gap]
    water = _near(world.water, x0, y0, x1, y1, 2.0)
    if water:                                   # in the water? tested for the whole cell at once
        from .landcover import inside_edges, ring_edges
        cache = world.__dict__.setdefault("_water_edges", {})
        for wt in water:
            e = cache.get(id(wt))
            if e is None:
                e = cache[id(wt)] = ring_edges([wt["points"]])
            ok &= ~inside_edges(e, px, py, y0, y1, x0)
    rails = _near(world.rails, x0, y0, x1, y1, 5.0)
    out = []
    for (x, y, h), good in zip(sites, ok):
        if not good or existing(x, y):
            continue
        if boxes and any(b[0] - gap <= x <= b[2] + gap and b[1] - gap <= y <= b[3] + gap for b in boxes):
            if any(world.in_building(x + ox, y + oy) for ox, oy in ((0, 0), (gap, 0), (-gap, 0), (0, gap), (0, -gap),
                                                                     (gap * 0.7, gap * 0.7), (-gap * 0.7, gap * 0.7),
                                                                     (gap * 0.7, -gap * 0.7), (-gap * 0.7, -gap * 0.7))):
                continue
        if rails and not _clear_of(x, y, (), rails):
            continue
        out.append(make(h, x, y))
        if len(out) >= WOODS_CELL_CAP:
            break
    return out
