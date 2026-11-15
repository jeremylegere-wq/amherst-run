"""Real woods: scatter trees inside the land cover polygons from data/landcover.json (see tools/fetch_landcover.py)."""
import json
import math
import os

from .world import point_in_polygon

LANDCOVER_NAME = "landcover.json"
CELL = 8.0            # metres between tree sites (each jittered), roughly one tree per 64 m2
MAX_WOOD_TREES = 6000


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
