#!/usr/bin/env python3
"""Generate a synthetic test town (no OSM data needed) in the same JSON format.

Usage:
    python tools/make_sample_map.py data/sample_map.json
"""
import json
import math
import random
import sys

ATTRIBUTION = "Synthetic test map (original)"
BLOCK = 90          # metres between streets
EXTENT = 5          # streets from -EXTENT..EXTENT blocks => ~900m square


def point_seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _rect(x0, y0, x1, y1):
    return [[round(x0, 1), round(y0, 1)], [round(x1, 1), round(y0, 1)],
            [round(x1, 1), round(y1, 1)], [round(x0, 1), round(y1, 1)]]


def _clear(buildings, x0, y0, x1, y1):
    """Drop buildings whose centre lies inside the rectangle."""
    out = []
    for b in buildings:
        cx = sum(p[0] for p in b["points"]) / len(b["points"])
        cy = sum(p[1] for p in b["points"]) / len(b["points"])
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            out.append(b)
    return out


def add_demo_downtown(data):
    """Give the test town a small downtown like Amherst's, using the same landmark code as the real map:
    a square with a cenotaph, a court house with a clock tower, a church, a post office, a bank,
    a sandstone/brick district, wind turbines on the skyline and a lighthouse by the west edge."""
    import landmarks
    B = BLOCK
    bl = data["buildings"]
    for box in ((-B, -B, 0, 0), (0, -B, B, 0), (-2 * B, -B, -B, 0), (0, 0, B, B), (-3 * B, 0, -3 * B + 30, 32)):
        bl = _clear(bl, *box)
    bl.append({"points": _rect(0.33 * B, -0.5 * B, 0.67 * B, -0.18 * B), "tags": {"name": "County Court House"}})
    bl.append({"points": _rect(-1.66 * B, -0.66 * B, -1.44 * B, -0.2 * B), "height": 9.0,
               "tags": {"name": "First Church", "amenity": "place_of_worship"}})
    bl.append({"points": _rect(0.25 * B, 0.18 * B, 0.75 * B, 0.5 * B), "height": 11.0,
               "tags": {"name": "Post Office", "amenity": "post_office"}})
    bank = min(bl, key=lambda b: math.hypot(sum(p[0] for p in b["points"]) / 4 + 0.2 * B,
                                            sum(p[1] for p in b["points"]) / 4 - 0.25 * B))
    bank["tags"] = {"name": "Red Stone Bank", "amenity": "bank"}
    data["buildings"] = bl
    data["parks"] = [{"name": "Victoria Square", "points": _rect(-B + 10, -B + 10, -10, -10)}]
    spec = {
        "district": {"near_xy": [-0.3 * B, 0.0], "radius": 2.3 * B, "materials": {"sandstone": 0.55, "brick": 0.45}},
        "landmarks": [
            {"id": "courthouse", "kind": "courthouse", "label": "Court House", "names": ["court house"],
             "near_xy": [0.5 * B, -0.33 * B], "search": 120, "material": "sandstone", "height": 12.5,
             "tower": True, "role": "courthouse"},
            {"id": "post_office", "kind": "civic", "label": "Post Office", "tags": {"amenity": "post_office"},
             "near_xy": [0.5 * B, 0.33 * B], "search": 120, "material": "sandstone", "role": "deliveries"},
            {"id": "victoria_square", "kind": "square", "label": "Victoria Square", "names": ["victoria square"],
             "near_xy": [-0.5 * B, -0.5 * B], "search": 200, "trees": 8, "monument": "War Memorial"},
            {"id": "church", "kind": "church", "tags": {"amenity": "place_of_worship"},
             "near_xy": [-1.5 * B, -0.4 * B], "search": 200, "all": True, "fallback_nearest": False},
            {"id": "bank", "kind": "civic", "tags": {"amenity": "bank"}, "near_xy": [-0.2 * B, 0.25 * B],
             "search": 150, "all": True, "fallback_nearest": False, "material": "sandstone", "role": "getaway"},
            {"id": "wind_farm_east", "kind": "wind_farm", "at_xy": [16 * B, 0.0], "count": 6, "spacing": 330},
            {"id": "wind_farm_west", "kind": "wind_farm", "at_xy": [-18 * B, 0.0], "count": 8, "spacing": 330},
            {"id": "lighthouse", "kind": "lighthouse", "at_xy": [-3 * B + 14, 16.0], "label": "Welcome Centre lighthouse"},
        ],
    }
    landmarks.apply_landmarks(data, spec)
    return data


def build(seed=7, extent=EXTENT, demo=True):
    rng = random.Random(seed)
    lines = [i * BLOCK for i in range(-(extent // 2) - 1, extent // 2 + 2)]
    lo, hi = lines[0], lines[-1]

    roads = []
    for v in lines:
        main = (v == 0)
        kind, width = ("main", 11) if main else ("side", 8)
        roads.append({"type": kind, "width": width, "name": f"Main St" if main else f"Ave {v}",
                      "points": [[v, lo], [v, hi]]})
        roads.append({"type": kind, "width": width, "name": f"Main St" if main else f"Street {v}",
                      "points": [[lo, v], [hi, v]]})

    rail = [[lo, -BLOCK * 2 - 40], [hi, BLOCK + 40]]
    pond_c, pond_r = (BLOCK * 2 + BLOCK / 2, -BLOCK * 2 + BLOCK / 2), 30
    pond = [[round(pond_c[0] + pond_r * math.cos(a / 12 * 2 * math.pi), 1),
             round(pond_c[1] + pond_r * math.sin(a / 12 * 2 * math.pi), 1)] for a in range(12)]

    buildings = []
    for i in range(len(lines) - 1):
        for j in range(len(lines) - 1):
            x0, x1 = lines[i] + 10, lines[i + 1] - 10
            y0, y1 = lines[j] + 10, lines[j + 1] - 10
            # split block into a 2x2 grid of lots; each gets one building most of the time
            for lx in range(2):
                for ly in range(2):
                    if rng.random() < 0.2:
                        continue
                    cx0 = x0 + (x1 - x0) * lx / 2 + 3
                    cx1 = x0 + (x1 - x0) * (lx + 1) / 2 - 3
                    cy0 = y0 + (y1 - y0) * ly / 2 + 3
                    cy1 = y0 + (y1 - y0) * (ly + 1) / 2 - 3
                    w, h = (cx1 - cx0) * rng.uniform(0.6, 1.0), (cy1 - cy0) * rng.uniform(0.6, 1.0)
                    bx, by = cx0 + rng.uniform(0, cx1 - cx0 - w), cy0 + rng.uniform(0, cy1 - cy0 - h)
                    mx, my = bx + w / 2, by + h / 2
                    if point_seg_dist(mx, my, rail[0][0], rail[0][1], rail[1][0], rail[1][1]) < 14:
                        continue
                    if math.hypot(mx - pond_c[0], my - pond_c[1]) < pond_r + 22:
                        continue
                    buildings.append({"points": [[round(bx, 1), round(by, 1)],
                                                 [round(bx + w, 1), round(by, 1)],
                                                 [round(bx + w, 1), round(by + h, 1)],
                                                 [round(bx, 1), round(by + h, 1)]]})

    data = {
        "meta": {"name": "Sample Town", "bounds": [lo, lo, hi, hi],
                 "attribution": ATTRIBUTION, "spawn": [-BLOCK * 2, 0, 0.0]},
        "roads": roads, "buildings": buildings, "rails": [{"points": rail}],
        "water": [{"points": pond}],
    }
    return add_demo_downtown(data) if demo else data


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "data/sample_map.json"
    data = build()
    with open(out, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"roads={len(data['roads'])} buildings={len(data['buildings'])} -> {out}")
