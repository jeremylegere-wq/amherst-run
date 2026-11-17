"""Amherst house types: decide what kind of building a footprint is, so the renderer can give it the right details.

Amherst's homes are mostly a handful of types. From what the map knows about a building (footprint size and shape,
measured LiDAR height and roof pitch, zoning district, OSM tags) each residential building gets one:

  garage     small outbuilding: a wide garage door, no windows
  minihome   long narrow single-storey home (the mini-home parks): one row of windows, skirting
  bungalow   single storey, low roof: one row of windows, a door
  cape       storey-and-a-half with a steep roof (like the start house): one row of windows + a window in each gable
  two_storey two full storeys (Victorian / foursquare): two rows of windows, gable windows, often a front veranda
  apartment  big and tall: rows of windows (the plain ribbons look right on these, so the renderer keeps them)

Commercial, civic, industrial, landmark and hand-built buildings get None and keep their existing look.
The numbers are deliberately simple; tune them by looking at the town. Porches are not in any data: a stable
per-building coin flip gives about half the two-storey houses a veranda, as Amherst's older streets have.
"""
import math

KINDS = ("garage", "minihome", "bungalow", "cape", "two_storey", "apartment")
RESIDENTIAL_ZONES = ("R", "T")
HOUSE_TAGS = ("house", "detached", "residential", "semidetached_house", "terrace", "bungalow", "garage", "garages",
              "shed", "apartments")
OTHER_TAGS = ("commercial", "retail", "industrial", "warehouse", "church", "school", "office", "hospital", "public",
              "civic", "roof", "barn", "farm_auxiliary", "service", "hotel", "supermarket", "manufacture")
BUNGALOW_WALL = 4.0      # measured wall height (m) up to which a shallow-roofed house is a bungalow
TWO_STOREY_WALL = 6.0    # above this it has two full storeys; in between it is a storey-and-a-half (cape)
STEEP = 0.45             # measured roof rise/run counted as steep (LiDAR under-reads pitch: true capes are ~1.0)
PORCH_SHARE = {"two_storey": 0.55, "cape": 0.3, "bungalow": 0.2}


def _footprint(pts):
    """(area, long side, short side) of a footprint; long/short from the oriented bounding box of its longest edge."""
    n = len(pts)
    area = abs(sum(pts[k][0] * pts[k - 1][1] - pts[k - 1][0] * pts[k][1] for k in range(n))) / 2.0
    best = max(range(n), key=lambda k: math.hypot(pts[(k + 1) % n][0] - pts[k][0], pts[(k + 1) % n][1] - pts[k][1]))
    a, b = pts[best], pts[(best + 1) % n]
    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    us = [p[0] * ux + p[1] * uy for p in pts]
    vs = [-p[0] * uy + p[1] * ux for p in pts]
    d1, d2 = max(us) - min(us), max(vs) - min(vs)
    return area, max(d1, d2), min(d1, d2)


def _coin(i, salt):
    """Stable pseudo-random number in [0, 1) for building i (same every run)."""
    return ((i * 2654435761 + salt * 40503) % 4294967296) / 4294967296.0


def classify(b, i=0):
    """{"kind": ..., "storeys": n, "porch": bool} for a residential building, or None to leave it alone.
    A hand-set "arch" on the building (map_edits.json) wins: a kind name, optionally with "+porch"."""
    hand = b.get("arch")
    if hand:
        kind = hand.split("+")[0]
        if kind not in KINDS:
            return None
        storeys = 2 if kind == "two_storey" else (max(2, int(float(b.get("height") or 6) / 2.9)) if kind == "apartment" else 1)
        return {"kind": kind, "storeys": storeys, "porch": "+porch" in hand}
    if b.get("custom") or b.get("landmark") or b.get("role") or b.get("label"):
        return None
    tags = b.get("tags", {})
    tag = tags.get("building", "")
    if tag in OTHER_TAGS or tags.get("amenity") or tags.get("shop"):
        return None
    zone = b.get("zone")
    residential = zone in RESIDENTIAL_ZONES or tag in HOUSE_TAGS or b.get("material") == "clapboard"
    if not residential or b.get("material") in ("sandstone", "corrugated", "granite"):
        return None
    pts = b["points"]
    area, long_side, short_side = _footprint(pts)
    h = float(b.get("height") or 0.0)
    rh = float(b.get("roof_height") or 0.0) if b.get("roof") else 0.0
    if tag in ("garage", "garages", "shed") or area < 45.0:
        return {"kind": "garage", "storeys": 1, "porch": False}
    if area > 300.0 and h >= 6.5 or tag == "apartments":
        return {"kind": "apartment", "storeys": max(2, int(h / 2.9)), "porch": False}
    if zone == "T" or (long_side / max(short_side, 0.1) >= 2.6 and area <= 130.0 and h <= 4.5):
        return {"kind": "minihome", "storeys": 1, "porch": False}
    half = short_side / 2.0 if b.get("roof") and not b.get("ridge_across") else long_side / 2.0
    pitch = rh / max(half, 0.5)                    # rise over run as measured: LiDAR reads roofs flatter than they are
    if h > TWO_STOREY_WALL:
        kind, storeys = "two_storey", 2
    elif h > BUNGALOW_WALL or pitch >= STEEP:
        kind, storeys = "cape", 1
    else:
        kind, storeys = "bungalow", 1
    return {"kind": kind, "storeys": storeys, "porch": _coin(i, 7) < PORCH_SHARE.get(kind, 0.0)}


def front_wall(walls, near_road, reach=30.0, step=3.0):
    """Index of the wall that faces the street: the one whose outward line meets a road soonest (None if no road
    within reach). walls: (x0, y0, x1, y1, nx, ny, ...) with outward normals; near_road(x, y) -> bool."""
    best, best_d = None, reach + 1.0
    for k, w in enumerate(walls):
        x0, y0, x1, y1, nx, ny = w[:6]
        if math.hypot(x1 - x0, y1 - y0) < 2.5:
            continue
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        d = step
        while d < best_d:
            if near_road(mx + nx * d, my + ny * d):
                best, best_d = k, d
                break
            d += step
    return best
