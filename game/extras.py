"""The extra OpenStreetMap layers (data/osm_extras.json, made by tools/fetch_osm_extras.py): land use areas, rivers and
streams, power lines and fences. Applied by World.load before the world is built:

  data["areas"]       [{"kind", "points"}]  flat ground colours (game/render3d.py AREA_COLOURS)
  data["waterways"]   [{"kind", "width", "points"}]  drawn as water ribbons under the roads
  data["props"]       + "pole" / "tower" props, each with the next pole along its line ("to") for the wires,
                      + fence pieces, + gravestones in the cemeteries
"""
import json
import math
import os
import random

NAME = "osm_extras.json"
FENCE_LOOK = {   # kind -> (height, colour, solid)
    "fence": (1.2, (150, 122, 92), False),
    "wall": (1.1, (146, 140, 130), True),
    "hedge": (1.6, (62, 112, 54), True),
    "guard_rail": (0.75, (196, 198, 204), False),
}
MARGIN = 200.0              # metres past the map bounds that extras are kept (long lines are clipped)
STONE_SPACING = 4.0         # metres between gravestones in a cemetery
MAX_STONES = 350            # per cemetery
STONE_COLOURS = ((128, 130, 136), (96, 98, 104), (150, 86, 80), (214, 214, 208), (70, 72, 80))


def load_beside(map_path):
    path = os.path.join(os.path.dirname(os.path.abspath(map_path)), NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _inside(x, y, pts):
    hit, j = False, len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def gravestones(area, seed):
    """Rows of gravestones filling a cemetery, facing one way, a few gaps; capped at MAX_STONES."""
    pts = area["points"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    rng = random.Random(seed)
    out = []
    y = min(ys) + 2.0
    while y < max(ys) - 1.0 and len(out) < MAX_STONES:
        x = min(xs) + 2.0
        while x < max(xs) - 1.0 and len(out) < MAX_STONES:
            if rng.random() < 0.8 and _inside(x, y, pts):
                out.append({"kind": "gravestone", "x": round(x + rng.uniform(-0.3, 0.3), 2), "y": round(y, 2),
                            "heading": -math.pi / 2, "h": round(rng.uniform(0.55, 1.0), 2),
                            "w": round(rng.uniform(0.5, 0.85), 2), "colour": list(rng.choice(STONE_COLOURS))})
            x += STONE_SPACING * 0.7
        y += STONE_SPACING
    return out


def apply(data, doc):
    """Add the extra layers to the map data in place. Returns a one-line report ("" without a file)."""
    if not doc:
        return ""
    x0, y0, x1, y1 = data.get("meta", {}).get("bounds", (-1e9, -1e9, 1e9, 1e9))
    m = MARGIN

    def on_map(p):
        return x0 - m <= p[0] <= x1 + m and y0 - m <= p[1] <= y1 + m
    data["areas"] = [a for a in doc.get("areas", []) if any(on_map(p) for p in a["points"])]
    waterways = []
    for w in doc.get("waterways", []):                      # long rivers: keep the runs of points on the map
        run = []
        for p in w["points"] + [None]:
            if p is not None and on_map(p):
                run.append(p)
            else:
                if len(run) > 1:
                    waterways.append(dict(w, points=run))
                run = []
    data["waterways"] = waterways
    props = data.setdefault("props", [])
    poles = 0
    for line in doc.get("power", []):
        ps = line["poles"]
        for k, (x, y, tower) in enumerate(ps):
            nxt = ps[k + 1] if k + 1 < len(ps) else None
            if not on_map((x, y)):
                continue
            if nxt is not None and math.hypot(nxt[0] - x, nxt[1] - y) < 2.0:
                continue                                             # a doubled node, not a pole
            p = {"kind": "tower" if tower else "pole", "x": x, "y": y}
            if nxt is not None:
                p["to"] = [nxt[0], nxt[1]]
            props.append(p)
            poles += 1
    for x, y, tower in doc.get("lone_poles", []):
        if on_map((x, y)):
            props.append({"kind": "tower" if tower else "pole", "x": x, "y": y})
            poles += 1
    fences = 0
    for f in doc.get("fences", []):
        h, colour, solid = FENCE_LOOK.get(f["kind"], FENCE_LOOK["fence"])
        for a, b in zip(f["points"], f["points"][1:]):
            props.append({"kind": "fence", "x": a[0], "y": a[1], "x2": b[0], "y2": b[1], "h": h,
                          "colour": list(colour), "solid": solid})
            fences += 1
    stones = 0
    for i, area in enumerate(data["areas"]):
        if area["kind"] == "cemetery":
            g = gravestones(area, i)
            props.extend(g)
            stones += len(g)
    return "OSM extras: %d areas, %d waterways, %d power poles and towers, %d fence pieces, %d gravestones" % (
        len(data["areas"]), len(data["waterways"]), poles, fences, stones)
