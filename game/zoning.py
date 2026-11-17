"""Zone-based building looks: buildings in the same Amherst zoning district share a consistent character.

data/zoning.json (made by tools/zoning_from_pdf.py from the town's zoning map) is a grid of one-letter zone codes.
`apply(data, zoning)` gives every plain OSM building (no material, height, landmark or role already set) a look from
its zone: clapboard houses with shingle roofs in General Residential, corrugated boxes in Highway Commercial and
Industrial, brick in Downtown, and so on. Landmarks, real heights and anything you built yourself are left alone.
The look is picked per building from a fixed hash, so it is the same on every run.
"""
import json
import math
import os

ZONING_NAME = "zoning.json"

# palettes (RGB), kept small so a street reads as one family of looks
SIDING = [(238, 232, 214), (214, 226, 236), (226, 206, 160), (186, 204, 176), (210, 168, 150), (232, 232, 236),
          (170, 188, 204)]
SHINGLE = [(66, 62, 64), (88, 70, 62), (100, 56, 52), (58, 66, 74)]
MINI = [(240, 238, 230), (214, 208, 190), (176, 196, 210), (200, 190, 176)]
BRICK = [(176, 98, 78), (160, 84, 70), (188, 120, 96), (150, 90, 80)]
SANDSTONE = [(190, 108, 78), (176, 104, 82), (202, 128, 96)]
SHEET = [(150, 156, 164), (176, 170, 156), (138, 148, 160), (164, 120, 110)]
BIZ = [(196, 198, 202), (206, 196, 176), (170, 180, 192)]
MALL = (174, 166, 152)

BIG_BOX_AREA = 250.0        # m2: above this a commercial building is a box store, below it a shop
RURAL = "R"                 # zone used outside the zoning map (the rural loop around town is mostly homes)
MIN_AREA = 22.0             # sheds and booths are left as they are


def _area(pts):
    s = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def _centroid(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _h(i, salt):
    """Stable pseudo-random number in [0, 1) for building i."""
    v = (i * 2654435761 + salt * 40503) & 0xFFFFFFFF
    v ^= v >> 15
    v = (v * 2246822519) & 0xFFFFFFFF
    v ^= v >> 13
    return (v & 0xFFFF) / 65536.0


def _pick(seq, i, salt):
    return seq[int(_h(i, salt) * len(seq)) % len(seq)]


class Zoning:
    def __init__(self, doc):
        self.cell = float(doc["cell"])
        self.x0, self.y0 = float(doc["x0"]), float(doc["y0"])
        self.rows = doc["rows"]
        self.names = doc.get("zones", {})

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls(json.load(f))

    def covers(self, x, y):
        """True inside the zoning map's grid."""
        r = (y - self.y0) / self.cell
        return 0 <= r < len(self.rows) and 0 <= (x - self.x0) / self.cell < len(self.rows[int(r)])

    def _at(self, x, y):
        c = int(math.floor((x - self.x0) / self.cell))
        r = int(math.floor((y - self.y0) / self.cell))
        if 0 <= r < len(self.rows) and 0 <= c < len(self.rows[r]):
            return self.rows[r][c]
        return "-"

    def zone_at(self, x, y):
        """Zone code at game position (x, y), or '-' when it is not zoned. A cell on a road line looks one cell around."""
        z = self._at(x, y)
        if z != "-":
            return z
        if not self.covers(x, y):
            return RURAL                                   # past the town's zoning map: the rural roads are homes
        seen = {}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                v = self._at(x + dx * self.cell, y + dy * self.cell)
                if v != "-":
                    seen[v] = seen.get(v, 0) + 1
        return max(seen, key=seen.get) if len(seen) and sum(seen.values()) >= 5 else "-"


def look(zone, i, area, four):
    """Fields to set on a plain building in `zone`; {} to leave it alone. `four` = footprint has 4 corners (roofs)."""
    if area < MIN_AREA:
        return {}
    if zone == "R":                                        # General Residential: clapboard homes, shingle roofs
        if area > 400.0:
            return {"material": "brick", "colour": _pick(BRICK, i, 1), "height": 9.0 + _h(i, 2) * 2.5}
        tall = area > 70.0
        d = {"material": "clapboard", "colour": _pick(SIDING, i, 3), "height": (6.2 if tall else 4.6) + _h(i, 4) * 0.8}
        if four and area < 260.0:
            d.update(roof="gable", roof_height=2.2 + _h(i, 5) * 0.8, roof_colour=_pick(SHINGLE, i, 6))
        return d
    if zone == "T":                                        # Mini Home Residential: low vinyl-sided homes
        return {"material": "clapboard", "colour": _pick(MINI, i, 3), "height": 3.3 + _h(i, 4) * 0.4}
    if zone == "D":                                        # Downtown: brick and sandstone blocks
        mat = "sandstone" if _h(i, 7) < 0.45 else "brick"
        return {"material": mat, "colour": _pick(SANDSTONE if mat == "sandstone" else BRICK, i, 8),
                "height": 8.5 + _h(i, 9) * 3.5}
    if zone == "U":                                        # Mixed Use: two or three storeys of brick or siding
        if _h(i, 7) < 0.55:
            return {"material": "brick", "colour": _pick(BRICK, i, 8), "height": 7.0 + _h(i, 9) * 2.5}
        return {"material": "clapboard", "colour": _pick(SIDING, i, 3), "height": 6.5 + _h(i, 9) * 2.5}
    if zone == "N":                                        # Neighbourhood Commercial: corner shops
        return {"material": "brick", "colour": _pick(BRICK, i, 8), "height": 4.8 + _h(i, 9) * 1.0}
    if zone == "H":                                        # Highway Commercial: box stores and strip shops
        if area > BIG_BOX_AREA:
            return {"material": "corrugated", "colour": _pick(SHEET, i, 10), "height": 6.0 + _h(i, 11) * 1.5}
        return {"material": "brick", "colour": _pick(BRICK, i, 8), "height": 4.8 + _h(i, 9) * 1.2}
    if zone == "M":                                        # Industrial: tall sheet-metal sheds
        d = {"material": "corrugated", "colour": _pick(SHEET, i, 10), "height": 7.5 + _h(i, 11) * 2.5}
        if four and area > 300.0:
            d.update(roof="gable", roof_height=1.4, roof_colour=_pick(SHEET, i, 12))
        return d
    if zone == "B":                                        # Business Park: pale low offices and units
        return {"material": "corrugated", "colour": _pick(BIZ, i, 10), "height": 6.5 + _h(i, 11) * 2.0}
    if zone == "I":                                        # Institutional: schools, halls, care homes in brick
        d = {"material": "brick", "colour": _pick(BRICK, i, 8), "height": 7.5 + _h(i, 9) * 3.0}
        if four and area < 900.0:
            d.update(roof="hip", roof_height=2.4)
        return d
    if zone == "C":                                        # Comprehensive Development: the mall, its units, and homes
        if area < 300.0:
            return look("R", i, area, four)
        return {"material": "corrugated", "colour": MALL if area > 1500.0 else _pick(SHEET, i, 10),
                "height": 6.0 if area > 1500.0 else 6.0 + _h(i, 11) * 1.5}
    return {}                                              # Open space, flood plain, unzoned


MEASURED = ("height", "roof", "roof_height", "ridge_across")      # set from LiDAR on "lidar" buildings (game/lidar.py)


def plain(b):
    """True for an ordinary OSM building: nothing about its look has been set by data, a landmark or the player.
    A LiDAR-measured height and roof do not count: the zone still gives the building its colours and materials."""
    measured = MEASURED if b.get("lidar") else ()
    return not any(k in b and k not in measured
                   for k in ("material", "height", "landmark", "role", "label", "roof", "colour", "custom"))


def apply(data, zoning):
    """Give plain buildings in data["buildings"] their zone's look. Returns {zone code: buildings changed}."""
    counts = {}
    for i, b in enumerate(data["buildings"]):
        tags = b.get("tags", {})
        if not plain(b) or ((tags.get("height") or tags.get("building:levels")) and not b.get("lidar")):
            continue                                      # real data about the building wins over the zone
        pts = b["points"]
        cx, cy = _centroid(pts)
        z = zoning.zone_at(cx, cy)
        fields = look(z, i, _area(pts), len(pts) == 4)
        if fields:
            for k, v in fields.items():
                if b.get("lidar") and k in MEASURED:
                    continue                              # measured beats the zone's guess
                b[k] = list(v) if isinstance(v, tuple) else v
            b["zone"] = z
            counts[z] = counts.get(z, 0) + 1
    return counts


def load_beside(map_path):
    """The Zoning next to a map file (data/zoning.json), or None."""
    path = os.path.join(os.path.dirname(os.path.abspath(map_path)), ZONING_NAME)
    return Zoning.load(path) if os.path.exists(path) else None
