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

from . import streetdetail
from .world import point_in_polygon

TREE_SPACING = 16.0       # average metres between trees along a street side
LAMP_SPACING = 34.0
MIN_GAP = 5.0             # no two props closer than this
TREE_CLEAR = 2.2          # trees stay this far from any road edge (clear of the 1.8 m sidewalk)
LAMP_CLEAR = 0.9
MAX_PROPS = 17500
MONUMENTS = {"cenotaph": (6.0, 1.4), "lighthouse": (10.6, 1.6)}   # kind -> (height, radius)
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


def _site_ok(world, x, y, clear, radius):
    if not world.in_bounds(x, y, margin=-2.0):
        return False
    if world.road_clearance(x, y) < clear:
        return False
    for ox, oy in ((0, 0), (radius, 0), (-radius, 0), (0, radius), (0, -radius)):
        if world.in_building(x + ox, y + oy):
            return False
    for w in world.water:
        x0, y0, x1, y1 = w["bbox"]
        if x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2 and point_in_polygon(x, y, w["points"]):
            return False
    for r in world.rails:
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


def build_props(world, osm_props=(), seed=1, procedural=True):
    """Return the list of props for a world (OSM ones first, then procedural)."""
    rng = random.Random(seed * 7919 + 3)
    spacing = _Spacing()
    props = []

    for p in osm_props:
        x, y = float(p["x"]), float(p["y"])
        kind = p.get("kind")
        if kind == "tree" and _site_ok(world, x, y, 0.4, 0.8) and spacing.free(x, y):
            props.append(_tree(rng, x, y))
        elif kind == "lamp" and _site_ok(world, x, y, 0.2, 0.2) and spacing.free(x, y):
            props.append(_lamp(x, y, 0.0, 0.0))
        elif kind in streetdetail.FURNITURE_KINDS and "h" in p:             # signs, signals, hydrants... made from map marks
            props.append(dict(p))
        elif kind in MONUMENTS and _site_ok(world, x, y, 0.3, 1.2) and spacing.free(x, y):
            h, r = MONUMENTS[kind]
            props.append({"kind": kind, "x": round(x, 2), "y": round(y, 2), "h": h, "r": r, "cr": r,
                          "c": 0, "label": p.get("label", "")})
        else:
            continue
        spacing.add(x, y)

    if not procedural:
        return props

    # hydrants, benches and bins first, so the trees (which fill the prop budget) leave room for them
    props.extend(streetdetail.furniture(world, rng, spacing.free,
                                        lambda x, y, clear, rad: _site_ok(world, x, y, clear, rad), spacing.add))

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
    # real woods from the land cover data: trees fill the treed areas, after the street trees
    if getattr(world, "woods", None):
        from . import landcover
        for x, y in landcover.sites(world.woods, rng, centre=world.spawn()[:2]):
            if len(props) >= MAX_PROPS:
                break
            if spacing.free(x, y) and _site_ok(world, x, y, 1.5, 1.2):
                props.append(_tree(rng, x, y))
                spacing.add(x, y)
    return props[:MAX_PROPS]
