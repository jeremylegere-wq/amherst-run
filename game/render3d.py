"""Flat-shaded 3D renderer, pure pygame + Python, with two visual styles.

Approach: real 3D maths (camera basis, perspective projection, near-plane clipping)
but only flat polygons, painted back to front with pygame.draw.polygon onto the
320x224 surface.

Styles (Renderer3D(world, style=...)):
  "retro"  - chunky flat-shaded look: 4 light levels, heavy banded fog, muted palette.
  "street" - cel-shaded street look: two-tone shading, dark ink outlines on buildings
             and cars, ribbon windows, wide light sidewalks, see-through cast shadows,
             cartoon clouds, saturated palette, light haze instead of fog.

Weather / time of day (Renderer3D(world, style, weather=...), game --weather): "clear" (default), "overcast"
(maritime grey), "fog" (coastal fog), "golden" (golden hour, long shadows), "snow" (winter, falling snow). Each is
a set of style overrides in WEATHER, applied on top of either style; colours are graded once in col() (cached).

World axes: x = east, y = south, z = up (metres). Yaw 0 looks east and increasing
yaw turns right (towards south), matching Car.heading.
"""
import math
import random
from collections import defaultdict

import numpy as np
import pygame

from . import config as C
from . import streetdetail as SD
from . import archetypes
from . import murals
from .builder import face_normal, roof_faces
from .car import MODELS, PLAYER_PALETTE, Car
from .world import CELL

HALF_W_DRAW = 1.45         # train body half width
W, H = C.INTERNAL_W, C.INTERNAL_H   # 320x180 (16:9)
HW, HH = W / 2.0, H / 2.0

NEAR = 0.6
FOV_DEG = 72.0            # horizontal field of view (retro style)
DRAW_DIST = 200.0         # nothing beyond this is drawn
FOG_START = 35.0
FOG_BANDS = 6
FOG_STEP = (DRAW_DIST - FOG_START) / (FOG_BANDS - 1)
WALL_PIECE = 12.0         # long building walls are sorted in pieces this long
ORDER_NEAR = 10.0         # cars/props this close to a wall plane get their draw order checked against it
ORDER_CELL = 16.0         # grid used to find those walls
SPAN_PIECE = 10.0         # overpass decks are cut into pieces this long
PIECE_LEN = 20.0          # roads/rails are cut into pieces so fog and culling work per piece

FOG_RGB = (178, 202, 228)
SKY_TOP = (40, 96, 200)
SKY_BANDS = 6
HILL_FAR = (136, 166, 198)
HILL_NEAR = (98, 140, 134)
SHADE_LEVELS = (0.58, 0.74, 0.88, 1.0)

_LIGHT = (-0.45, 0.40, 0.80)
_LL = math.sqrt(sum(v * v for v in _LIGHT))
LIGHT = tuple(v / _LL for v in _LIGHT)
# where a shadow falls, per metre of height (away from the sun, along the ground)
SHADOW_DIR = (-LIGHT[0] / LIGHT[2] * 0.8, -LIGHT[1] / LIGHT[2] * 0.8)

BUILDING_COLOURS = [(176, 84, 68), (214, 192, 140), (146, 150, 164),
                    (92, 124, 172), (196, 120, 56), (120, 150, 104)]
CAR_BODY = (244, 220, 60)
CAR_LOWER = (30, 30, 40)
CAR_GLASS = (70, 100, 170)
CAR_TAIL = (232, 40, 40)
SHADOW_RGB = (24, 36, 28)

ROAD_BASE = {"lane": C.PALETTE["road_lane"], "side": C.PALETTE["road_side"], "main": C.PALETTE["road_main"]}
ROAD_ORDER = ("lane", "side", "main")

STYLES = {
    "retro": {
        "fov": FOV_DEG, "sky_top": SKY_TOP, "sky_bottom": FOG_RGB, "sky_bands": SKY_BANDS,
        "fog": FOG_RGB, "fog_scale": 1.0, "hill_far": HILL_FAR, "hill_near": HILL_NEAR,
        "shade": SHADE_LEVELS, "buildings": BUILDING_COLOURS,
        "grass": C.PALETTE["grass"], "water": C.PALETTE["water"],
        "rail_bed": C.PALETTE["rail_bed"], "rail": C.PALETTE["rail"],
        "road": ROAD_BASE, "kerb": C.PALETTE["road_edge"], "kerb_w": 0.35, "line": C.PALETTE["road_line"],
        "line_yellow": (214, 176, 44), "gravel": (150, 132, 104),
        "sidewalk": (C.PALETTE["road_edge"], C.PALETTE["road_edge"], (150, 96, 80)),     # edge, concrete, brick
        "sidewalk_w": (0.35, 0.9, 1.2),
        "car_shadow": SHADOW_RGB, "ink": None, "ink_until_fog": 0, "windows": None,
        "house": {"foundation": (112, 110, 104), "trim": (196, 192, 180), "glass": (62, 78, 110),
                  "doors": [(110, 46, 40), (52, 64, 92), (70, 88, 66)], "garage_door": (176, 172, 160),
                  "porch": (150, 128, 96), "porch_roof": (92, 90, 96),
                  "signs": [(60, 70, 64), (90, 50, 44), (50, 60, 84), (120, 104, 70)]},
        "clouds": 0, "cast_shadows": None,
        "trunk": (96, 72, 52), "lamp": (70, 72, 84), "lamp_head": (220, 214, 170),
        "tree_cols": [((90, 130, 70), (64, 100, 56)), ((104, 140, 80), (72, 108, 60)), ((80, 120, 74), (58, 92, 58))],
        "graffiti": False, "cartoon_cars": False,
        "materials": {"sandstone": [(150, 82, 64), (140, 76, 60)], "brick": [(128, 66, 56), (118, 60, 52)],
                      "clapboard": [(196, 190, 176)], "granite": [(150, 150, 156)],
                      "corrugated": [(150, 146, 136)]},
        "cornice": (190, 176, 150), "park": (70, 124, 62), "path": (150, 146, 136), "slate": (70, 74, 90),
        "clock": (230, 226, 210), "bronze": (70, 90, 80), "granite": (150, 150, 156), "turbine": (226, 228, 232),
    },
    "street": {
        "fov": 80.0, "sky_top": (16, 58, 196), "sky_bottom": (104, 184, 248), "sky_bands": 32,
        "fog": (160, 206, 244), "fog_scale": 0.55, "hill_far": (126, 176, 226), "hill_near": (66, 154, 126),
        "shade": (0.64, 0.64, 1.0, 1.0),                       # two tones: shadow side / lit side
        "buildings": [(238, 232, 216), (246, 198, 60), (228, 102, 78), (92, 164, 226),
                      (150, 208, 116), (196, 200, 214), (244, 148, 56), (214, 128, 184)],
        "grass": (80, 178, 70), "water": (36, 118, 224),
        "rail_bed": (120, 96, 80), "rail": (236, 236, 240),
        "road": {"lane": (156, 150, 142), "side": (124, 124, 132), "main": (108, 108, 118)},
        "kerb": (206, 202, 194), "kerb_w": 1.8, "line": (250, 250, 250),
        "line_yellow": (244, 204, 40), "gravel": (186, 164, 126),
        "sidewalk": ((170, 162, 148), (206, 202, 194), (190, 112, 92)),     # shoulder, concrete, red brick
        "sidewalk_w": (0.7, 1.8, 2.6),
        "car_shadow": None, "ink": (22, 18, 40), "ink_until_fog": 4, "windows": (40, 60, 118),
        "house": {"foundation": (150, 146, 140), "trim": (250, 250, 244), "glass": (52, 84, 150),
                  "doors": [(196, 44, 48), (36, 70, 150), (40, 120, 84), (250, 250, 244)],
                  "garage_door": (236, 234, 226), "porch": (204, 168, 118), "porch_roof": (72, 76, 92),
                  "signs": [(30, 96, 72), (150, 36, 44), (32, 60, 130), (214, 170, 52), (24, 24, 30)]},
        "clouds": 9, "cast_shadows": (24, 22, 72, 120),     # RGBA, drawn see-through
        "trunk": (124, 80, 46), "lamp": (64, 66, 96), "lamp_head": (255, 246, 190),
        "tree_cols": [((98, 206, 72), (44, 138, 66)), ((150, 216, 58), (72, 150, 52)), ((72, 192, 112), (34, 124, 88))],
        "graffiti": True, "cartoon_cars": True,
        "materials": {"sandstone": [(206, 104, 70), (190, 92, 64), (214, 120, 80)],
                      "brick": [(176, 72, 56), (158, 62, 52)],
                      "clapboard": [(240, 236, 224), (220, 232, 240)], "granite": [(186, 186, 194)],
                      "corrugated": [(196, 190, 176), (170, 176, 188)]},
        "cornice": (242, 224, 186), "park": (118, 206, 92), "path": (214, 206, 186), "slate": (64, 70, 104),
        "clock": (252, 250, 236), "bronze": (64, 104, 90), "granite": (186, 186, 196), "turbine": (250, 250, 252),
    },
}


# Weather presets: style keys to override, plus "grade" = ((r, g, b) multipliers, desaturation 0..1) applied to every
# shaded colour, "snowfall" = flakes on screen, "hide_horizon" = no hills/turbines (thick fog), "shadow_dir" = shadow
# offset per metre of height (golden hour: low sun in the west, long shadows to the east).
WEATHER = {
    "clear": {},
    "overcast": {
        "sky_top": (108, 122, 140), "sky_bottom": (178, 186, 196), "sky_bands": 12, "fog": (172, 180, 190),
        "fog_scale": 0.85, "hill_far": (140, 150, 162), "hill_near": (92, 116, 108), "clouds": 0,
        "cast_shadows": None, "car_shadow": (70, 78, 80), "grade": ((0.92, 0.94, 0.98), 0.30),
    },
    "fog": {
        "sky_top": (186, 194, 202), "sky_bottom": (208, 214, 220), "sky_bands": 6, "fog": (206, 212, 218),
        "fog_scale": 1.7, "hill_far": (206, 212, 218), "hill_near": (206, 212, 218), "clouds": 0,
        "cast_shadows": None, "car_shadow": (110, 118, 120), "grade": ((0.96, 0.98, 1.0), 0.40), "hide_horizon": True,
    },
    "golden": {
        "sky_top": (58, 70, 160), "sky_bottom": (252, 186, 120), "sky_bands": 32, "fog": (246, 196, 150),
        "fog_scale": 0.6, "hill_far": (190, 140, 150), "hill_near": (104, 116, 84),
        "cast_shadows": (70, 30, 60, 90), "shadow_dir": (1.15, -0.2), "grade": ((1.10, 0.95, 0.78), 0.0),
    },
    "snow": {
        "sky_top": (140, 156, 182), "sky_bottom": (212, 220, 232), "sky_bands": 16, "fog": (216, 222, 232),
        "fog_scale": 0.95, "hill_far": (196, 206, 222), "hill_near": (222, 228, 236), "clouds": 0,
        "grass": (232, 238, 246), "park": (226, 234, 242), "slate": (232, 236, 244), "gravel": (214, 210, 204),
        "tree_cols": [((226, 236, 240), (92, 132, 112)), ((236, 242, 246), (70, 112, 96)),
                      ((214, 228, 232), (104, 120, 92))],
        "cast_shadows": None, "car_shadow": (150, 160, 176), "grade": ((0.96, 0.98, 1.04), 0.15), "snowfall": 160,
    },
}


def make_style(style, weather="clear"):
    """The style dict for a style name with a weather preset laid over it."""
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}; choose from {sorted(STYLES)}")
    if weather not in WEATHER:
        raise ValueError(f"unknown weather {weather!r}; choose from {sorted(WEATHER)}")
    st = dict(STYLES[style])
    st.update(WEATHER[weather])
    return st


def grade_rgb(rgb, grade):
    """Apply a weather colour grade ((r, g, b) multipliers, desaturation) to one colour."""
    if not grade:
        return rgb
    (mr, mg, mb), desat = grade
    r, g, b = rgb[0] * mr, rgb[1] * mg, rgb[2] * mb
    if desat:
        lum = 0.3 * r + 0.59 * g + 0.11 * b
        r, g, b = r + (lum - r) * desat, g + (lum - g) * desat, b + (lum - b) * desat
    return (int(max(0, min(255, r))), int(max(0, min(255, g))), int(max(0, min(255, b))))


OCC_COLS = 32             # hills hide what is behind them: a horizon line per screen column (10 px wide at 320)...
OCC_START, OCC_STEP = 6.0, 5.0   # ...from land sampled every 5 m outwards
OCC_SLACK = 0.3           # metres: land must rise this much above an object's line of sight to hide it
OCC_MARGIN = 3.0          # land at least this much nearer than an object can hide it (so a wall sunk into a slope is cut)
SHOP_DETAIL = 70.0        # metres: shop fronts and upper-storey windows on downtown blocks inside this
SHOP_ZONES = ("D", "U", "N")
HOUSE_DETAIL = 45.0       # metres: doors, windows, foundations and porches on houses (game/archetypes.py) inside this
PROP_DIST = 130.0         # trees and lamps further than this are not drawn
MURAL_DIST = 160.0        # wall murals (game/murals.py) are painted on within this distance
STALL_DIST = 45.0         # parking stall lines are painted within this distance
DETAIL_DIST = 95.0        # signs, hydrants, benches and the like
DETAIL_KINDS = frozenset(SD.FURNITURE_KINDS)
PAINT_DIST = 95.0         # road paint further than this is skipped (it is a pixel by then)
OCT8 = [k * math.pi / 4 for k in range(8)]
BLOB12 = [((k + 0.5) * math.pi / 6, 1.0 if k % 2 == 0 else 0.88) for k in range(12)]   # bumpy canopy outline
TAG_COLS = [(255, 64, 160), (60, 220, 255), (255, 226, 40), (120, 250, 90), (255, 128, 30),
            (176, 96, 255), (250, 250, 250)]


def _blob(cu, cv, a, b, tilt, rng, n):
    """A chunky rounded-rectangle 'bubble letter' outline in wall coordinates (u along, v up)."""
    ct, sn = math.cos(tilt), math.sin(tilt)
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        c, s = math.cos(t), math.sin(t)
        j = rng.uniform(0.9, 1.08)
        x = a * math.copysign(abs(c) ** 0.55, c) * j
        y = b * math.copysign(abs(s) ** 0.55, s) * j
        pts.append((cu + x * ct - y * sn, cv + x * sn + y * ct))
    return pts


HOUSE_TAGS = ("house", "detached", "semidetached_house", "residential", "bungalow", "terrace", "farm", "cabin")
SMALL_TAGS = ("garage", "garages", "shed", "carport", "hut", "roof", "kiosk")
BIG_LOW_TAGS = ("commercial", "retail", "supermarket", "industrial", "warehouse", "school", "office",
                "public", "civic", "hospital", "sports_hall")


def default_height(b, i, area):
    """Height in metres when OSM has none: from the building type, then the footprint.

    Amherst is mostly one- and two-storey houses with a 2-3 storey sandstone downtown, so only
    apartments get tall. A stable per-building jitter keeps streets from looking stamped out.
    """
    kind = b.get("tags", {}).get("building", "")
    j = ((i * 7919) % 11) / 10.0
    if b.get("landmark") == "heritage_house":
        return 8.5
    if b.get("material") in ("sandstone", "brick"):
        return 8.5 + j * 4.0
    if kind in SMALL_TAGS:
        return 3.0 + j * 0.6
    if kind in HOUSE_TAGS:
        return 5.5 + j * 2.5
    if kind in ("apartments", "dormitory", "hotel"):
        return 10.0 + j * 5.0
    if kind in ("church", "chapel", "cathedral"):
        return 10.0 + j * 2.0
    if kind in BIG_LOW_TAGS:
        return 6.5 + j * 3.0
    if area < 40:
        return 3.2 + j * 0.6
    if area < 220:
        return 5.5 + j * 2.5          # a house
    if area < 900:
        return 7.0 + j * 3.0
    return 7.5 + j * 2.5              # big footprints are shops and plants: wide but low


def graffiti_ok(b, area):
    """Tags go on downtown and commercial walls, not on family homes or landmarks (heritage and civic buildings)."""
    kind = b.get("tags", {}).get("building", "")
    if b.get("landmark"):
        return False
    if b.get("arch") or b.get("material") == "clapboard":
        return False                                       # hand-modelled homes and wooden siding: no tags
    if b.get("material"):
        return True
    if kind in HOUSE_TAGS or kind in SMALL_TAGS:
        return False
    return area >= 220


def shade_index(nx, ny, nz):
    """Quantised light level (0..3) for a surface normal."""
    d = nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]
    return max(0, min(3, int((0.45 + 0.45 * d) * 4)))


def _clip_near(cam):
    """Sutherland-Hodgman clip of a camera-space polygon against z >= NEAR."""
    out = []
    n = len(cam)
    for i in range(n):
        a, b = cam[i], cam[(i + 1) % n]
        a_in, b_in = a[2] >= NEAR, b[2] >= NEAR
        if a_in:
            out.append(a)
        if a_in != b_in:
            t = (NEAR - a[2]) / (b[2] - a[2])
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, NEAR))
    return out


def _chimney(pts, h, rh, at, size=0.75, above=1.1, across=False):
    """(4 corners, z bottom, z top) of a chimney on the ridge of a 4-cornered gable/hip roof.
    `at` is the place along the ridge, -1..1 of its half length (0 = middle)."""
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    e1 = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    e2 = (pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    e, hl = (e1, l1 / 2.0) if (l1 >= l2) != bool(across) else (e2, l2 / 2.0)   # the ridge: long side unless across
    L = max(1e-6, math.hypot(*e))
    ux, uy = e[0] / L, e[1] / L
    vx, vy = -uy, ux
    px, py = cx + ux * hl * at * 0.8, cy + uy * hl * at * 0.8
    s = size / 2.0
    corners = [(px + ux * a + vx * b, py + uy * a + vy * b) for a, b in ((-s, -s), (s, -s), (s, s), (-s, s))]
    return corners, h + rh - 0.4, h + rh + above


def _lerp_rgb(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _hull(points):
    """Convex hull (monotone chain), counter-clockwise, no repeated end point."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class _Frame:
    """A position + heading, so boxes for monuments and towers can reuse the car box code."""
    __slots__ = ("x", "y", "forward", "right")

    def __init__(self, x, y, heading=0.0):
        c, s = math.cos(heading), math.sin(heading)
        self.x, self.y = x, y
        self.forward, self.right = (c, s), (-s, c)


class ChaseCamera:
    """Third-person camera behind the car. Yaw lags the car a little so turns feel weighty."""

    def __init__(self, car, world=None):
        self.world = world
        self.yaw = car.heading
        self.x = self.y = 0.0
        self.z = 3.2
        self.pitch = 0.1
        self.update(car, 0.0, snap=True)

    def update(self, car, dt, snap=False):
        diff = (car.heading - self.yaw + math.pi) % (2 * math.pi) - math.pi
        k = 1.0 if snap else 1.0 - math.exp(-5.0 * dt)
        self.yaw += diff * k

        sp = min(car.speed, 35.0) / 35.0
        dist = 8.0 + 3.0 * sp          # pulls back at speed
        height = 3.2 + 0.8 * sp
        cs, sn = math.cos(self.yaw), math.sin(self.yaw)
        d = dist
        for f in (1.0, 0.75, 0.55, 0.4):  # shrink the follow distance if the camera would sit inside a building
            d = dist * f
            x, y = car.x - cs * d, car.y - sn * d
            if self.world is None or not self.world.in_building(x, y):
                break
        self.x, self.y, self.z = x, y, height + getattr(car, "z", 0.0)   # rides up overpasses with the car
        if self.world is not None and hasattr(self.world, "ground"):
            self.z = max(self.z, self.world.ground(x, y) + 1.5)       # never dips under a hill behind the car
        self.pitch = math.atan2(height - 1.0, d + 6.0)  # look at a point just ahead of the car


class Renderer3D:
    def __init__(self, world, style="retro", weather="clear"):
        self.world = world
        self.style = style
        self.weather = weather
        self.st = make_style(style, weather)
        self.focal = HW / math.tan(math.radians(self.st["fov"] / 2))
        self.polys = 0
        self.n_buildings = 0
        self.time = 0.0
        self._cols = {}
        self._layer = None
        self.terrain = getattr(world, "terrain", None)     # None = flat world
        self.gbase = 0.0                                   # ground height under the camera (set per frame)
        self._occ = None                                   # per-frame hill horizon (see _compute_horizon)
        self._occ_first = 0
        t = self.terrain
        self._tgrid = np.array(t.h, dtype=np.float32).reshape(t.ny, t.nx) if t is not None else None
        self._bground = {}                                 # building index -> (foundation z, skirt depth)
        self._prep_paint()
        self._prep_roads()
        self._prep_spans()
        self._prep_rails()
        self._prep_buildings()
        self._prep_graffiti()
        self._prep_clouds()
        self.water = [w for w in world.water]

    # ---------------------------------------------------------------- prep
    def _g(self, x, y):
        """Natural ground height at (x, y); 0 on a flat map."""
        t = self.terrain
        return t.height(x, y) if t is not None else 0.0

    def _building_ground(self, idx):
        """(foundation height, slope drop): a building sits on its HIGHEST corner and its walls reach down to the land, so on
        a slope the downhill side gets a taller wall (a walk-out basement) instead of the uphill side being buried."""
        v = self._bground.get(idx)
        if v is None:
            if self.terrain is None:
                v = (0.0, 0.0)
            else:
                b = self.buildings[idx]
                hs = [self._g(p[0], p[1]) for p in b[5]] + [self._g(b[0], b[1])]
                v = (max(hs), max(hs) - min(hs) + 0.3)
            self._bground[idx] = v
        return v

    def _split(self, pts):
        """Cut a polyline into pieces of <= PIECE_LEN. Yields (x0, y0, x1, y1, dx, dy)."""
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 0.01:
                continue
            n = max(1, math.ceil(L / PIECE_LEN))
            dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            for i in range(n):
                t0, t1 = i / n, (i + 1) / n
                yield (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0,
                       a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1, dx, dy)

    def _prep_roads(self):
        self.road_grid = defaultdict(list)
        k = 0
        downtown = SD.Downtown(self.world.buildings)
        for r in self.world.roads:
            if r.get("lift"):
                continue                        # an overpass deck: drawn as a raised span (_prep_spans)
            mk = SD.marking(r)
            gravel = 1 if r.get("surface") == "gravel" else 0
            for x0, y0, x1, y1, dx, dy in self._split(r["points"]):
                k += 1
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                sw = SD.sidewalk(r, downtown.near(mx, my))
                piece = (x0, y0, x1, y1, dx, dy, r["width"] / 2.0, r["type"], k % 2,
                         self._g(x0, y0), self._g(x1, y1), mk, sw, gravel, mx, my)
                self.road_grid[(int(mx // CELL), int(my // CELL))].append(piece)

    def _prep_paint(self):
        """Crosswalks and stop bars from the map's marks: (points with heights, colour key, mx, my) per cell."""
        self.paint_grid = defaultdict(list)
        for pt in getattr(self.world, "paint", ()):
            pts = [(x, y, self._g(x, y) + 0.035) for x, y in pt["pts"]]
            self.paint_grid[(int(pt["mx"] // CELL), int(pt["my"] // CELL))].append((pts, pt["colour"], pt["mx"], pt["my"]))

    def _prep_spans(self):
        """Overpass decks and ramps cut into short pieces: (x0, y0, h0, x1, y1, h1, dx, dy, half width, mx, my)."""
        self.span_pieces = []
        for sp in getattr(self.world, "spans", ()):
            hw = sp["width"] / 2.0
            pts, hs = sp["points"], sp["h"]
            for i in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[i], pts[i + 1]
                L = math.hypot(bx - ax, by - ay)
                if L < 0.01:
                    continue
                n = max(1, math.ceil(L / SPAN_PIECE))
                dx, dy = (bx - ax) / L, (by - ay) / L
                for j in range(n):
                    t0, t1 = j / n, (j + 1) / n
                    x0, y0, x1, y1 = ax + (bx - ax) * t0, ay + (by - ay) * t0, ax + (bx - ax) * t1, ay + (by - ay) * t1
                    h0 = hs[i] + (hs[i + 1] - hs[i]) * t0
                    h1 = hs[i] + (hs[i + 1] - hs[i]) * t1
                    self.span_pieces.append((x0, y0, h0, x1, y1, h1, dx, dy, hw, (x0 + x1) / 2, (y0 + y1) / 2, sp["lift"]))

    def _prep_rails(self):
        self.rail_grid = defaultdict(list)
        for r in self.world.rails:
            for x0, y0, x1, y1, dx, dy in self._split(r["points"]):
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                self.rail_grid[(int(mx // CELL), int(my // CELL))].append(
                    (x0, y0, x1, y1, dx, dy, self._g(x0, y0), self._g(x1, y1), mx, my))

    def _prep_buildings(self):
        """Per building: (cx, cy, height, colour index, walls, footprint, radius)."""
        self.buildings = {}
        self.extras = {}            # building index -> material / landmark details
        self._parked_cars = None    # hand-placed parked cars as Car objects (see parked_cars)
        self._stalls = None         # painted stall lines per parking lot, made on first draw
        self._houses = {}           # building index -> house details (game/archetypes.py), worked out when first close
        self._shops = {}            # building index -> walls with a shop front (set), worked out when first close
        for i, b in enumerate(self.world.buildings):
            self._prep_building(i, b)

    def refresh_building(self, i):
        """Rebuild one building's drawing data after the world changed it (build mode)."""
        self.buildings.pop(i, None)
        self._bground.pop(i, None)
        self.extras.pop(i, None)
        self._houses.pop(i, None)
        self._houses.pop(("dormer", i), None)
        self._shops.pop(i, None)
        self.graffiti.pop(i, None)
        self._prep_building(i, self.world.buildings[i])

    def _prep_building(self, i, b):
        n_cols = len(self.st["buildings"])
        pts = [tuple(p) for p in b["points"]]
        n = len(pts)
        area = sum(pts[j][0] * pts[(j + 1) % n][1] - pts[(j + 1) % n][0] * pts[j][1] for j in range(n)) / 2
        if abs(area) < 1.0:
            return
        walls = []
        for j in range(n):
            x0, y0 = pts[j]
            x1, y1 = pts[(j + 1) % n]
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy)
            if L < 0.05:
                continue
            # outward normal depends on the polygon winding
            nx, ny = (dy / L, -dx / L) if area > 0 else (-dy / L, dx / L)
            walls.append((x0, y0, x1, y1, nx, ny, shade_index(nx, ny, 0.0)))
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        rad = max(math.hypot(p[0] - cx, p[1] - cy) for p in pts)
        height = b.get("height") or default_height(b, i, abs(area))
        mats = self.st["materials"].get(b.get("material"))
        base = mats[i % len(mats)] if mats else self.st["buildings"][(i * 31) % n_cols]
        if b.get("colour"):
            base = tuple(b["colour"])
        self.buildings[i] = (cx, cy, height, base, walls, pts, rad)
        roof = b.get("roof")
        if b.get("material") or b.get("landmark") or roof:
            longest = max(walls, key=lambda w: math.hypot(w[2] - w[0], w[3] - w[1]))
            ex = {"material": b.get("material"), "landmark": b.get("landmark"),
                  "tower": b.get("tower", False), "steeple": b.get("steeple", "spire"),
                  "storeys": b.get("storeys"), "shopfront": b.get("shopfront"), "zone": b.get("zone"),
                  "plinth": b.get("plinth"), "plinth_h": b.get("plinth_h"), "dormers": int(b.get("dormers") or 0),
                  "front": b.get("front"), "door": b.get("door"), "door_at": b.get("door_at"),
                  "sidelights": b.get("sidelights"), "shutters": b.get("shutters"),
                  "front_windows": b.get("front_windows"), "plaque": b.get("plaque"), "window_h": b.get("window_h"),
                  "mural": b.get("mural"),
                  "axis": math.atan2(longest[3] - longest[1], longest[2] - longest[0]),
                  "roof": None}
            faces = roof_faces(pts, height, roof, b.get("roof_height", 0.0), b.get("ridge_across", False)) if roof else []
            if faces:
                pivot = (cx, cy, height)
                ex["roof"] = [(f, face_normal(f, pivot)) for f in faces]
                ex["roof_colour"] = tuple(b.get("roof_colour") or self.st["slate"])
                ex["roof_top"] = roof == "mansard"
                if b.get("chimney") is not None and roof in ("gable", "hip"):
                    ex["chimney"] = _chimney(pts, height, b.get("roof_height", 0.0), float(b["chimney"]),
                                             across=b.get("ridge_across", False))
            self.extras[i] = ex

    def _prep_graffiti(self):
        """Original procedural tags: about 30% of longer walls get one, chosen by a fixed seed."""
        self.graffiti = {}
        if not self.st["graffiti"]:
            return
        for i, b in self.buildings.items():
            h, walls, pts = b[2], b[4], b[5]
            area = abs(sum(pts[k][0] * pts[(k + 1) % len(pts)][1] - pts[(k + 1) % len(pts)][0] * pts[k][1]
                           for k in range(len(pts)))) / 2
            if h < 3.0 or not graffiti_ok(self.world.buildings[i], area):
                continue
            house = archetypes.classify(self.world.buildings[i], i)
            if house and house["kind"] != "apartment":
                continue                                        # nobody tags the side of a family home
            for wi, (x0, y0, x1, y1, _nx, _ny, _sh) in enumerate(walls):
                L = math.hypot(x1 - x0, y1 - y0)
                if L < 5.0:
                    continue
                rng = random.Random(i * 7919 + wi * 104729 + 17)
                if rng.random() > 0.3:
                    continue
                self.graffiti.setdefault(i, {})[wi] = self._make_tag(rng, L, h)

    @staticmethod
    def _make_tag(rng, L, h):
        """Back plate in one colour, 3-5 tilted bubble letters in another. Returns [(colour, uv points)]."""
        w = min(L - 1.6, rng.uniform(3.2, 6.5))
        u0 = rng.uniform(0.8, L - 0.8 - w)
        hh = min(w * rng.uniform(0.3, 0.42), h - 1.2)
        z0 = rng.uniform(0.45, 0.85)
        fill, back = rng.sample(TAG_COLS, 2)
        tilt = rng.uniform(-0.12, 0.12)
        cu, cv = u0 + w / 2, z0 + hh / 2
        shapes = [(back, _blob(cu, cv, w * 0.56, hh * 0.8, tilt, rng, 14))]
        n = rng.randint(3, 5)
        for k in range(n):
            lu = u0 + (k + 0.5) * w / n
            lv = cv + rng.uniform(-0.12, 0.12) * hh
            shapes.append((fill, _blob(lu, lv, w / n * 0.62, hh * 0.5 * rng.uniform(0.85, 1.15),
                                       tilt + rng.uniform(-0.25, 0.25), rng, 10)))
        return shapes

    def _prep_clouds(self):
        """Cartoon clouds: clusters of ellipses fixed to world directions (they never get closer)."""
        self.clouds = []
        n = self.st["clouds"]
        rng = random.Random(11)
        for k in range(n):
            az = k * 2 * math.pi / n + rng.uniform(-0.25, 0.25)
            elev = rng.uniform(26, 74)
            size = rng.uniform(0.7, 1.35)
            blobs = [(rng.uniform(-30, 30) * size, rng.uniform(-6, 3) * size,
                      rng.uniform(13, 24) * size, rng.uniform(7, 12) * size) for _ in range(rng.randint(4, 6))]
            self.clouds.append((az, elev, blobs))

    def set_weather(self, weather):
        """Switch the weather preset in place (F4). Only the clouds and the default roof colour are baked when the
        renderer is built, so just those are refreshed; the colour cache is cleared."""
        if weather == self.weather:
            return
        self.st = make_style(self.style, weather)
        self.weather = weather
        self._cols = {}
        self._prep_clouds()
        for i, ex in self.extras.items():
            if ex.get("roof") and not self.world.buildings[i].get("roof_colour"):
                ex["roof_colour"] = tuple(self.st["slate"])

    # -------------------------------------------------------------- helpers
    def col(self, base, shade, fog):
        """Flat colour for a base colour at a light level and fog band (cached)."""
        key = (base, shade, fog)
        c = self._cols.get(key)
        if c is None:
            m = self.st["shade"][shade]
            t = 0.0 if fog == 0 else (0.18 + 0.74 * (fog - 1) / (FOG_BANDS - 2)) * self.st["fog_scale"]
            t = min(1.0, t)
            lit = grade_rgb(tuple(min(255, v * m) for v in base), self.st.get("grade"))
            c = tuple(int(v * (1 - t) + f * t) for v, f in zip(lit, self.st["fog"]))
            self._cols[key] = c
        return c

    def ink(self, fog):
        """Outline colour for a fog band, or None when this style has no outlines there."""
        if self.st["ink"] is None or fog >= self.st["ink_until_fog"]:
            return None
        return self.col(self.st["ink"], 3, fog)

    @staticmethod
    def fog_band(depth):
        if depth < FOG_START:
            return 0
        b = int((depth - FOG_START) / FOG_STEP) + 1
        return b if b < FOG_BANDS else FOG_BANDS - 1

    def set_viewport(self, w, h):
        """Render into a w x h picture (split screen). The sizes are module globals, so call it before every render."""
        global W, H, HW, HH
        if (w, h) != (W, H):
            self._layer = None                                  # the shadow layer is sized to the picture
        W, H, HW, HH = w, h, w / 2.0, h / 2.0
        self.focal = HW / math.tan(math.radians(self.st["fov"] / 2))

    def _set_camera(self, cam):
        self.cx, self.cy, self.cz = cam.x, cam.y, cam.z
        self.yaw, self.pitch = cam.yaw, cam.pitch
        cy_, sy_ = math.cos(cam.yaw), math.sin(cam.yaw)
        cp, sp = math.cos(cam.pitch), math.sin(cam.pitch)
        self.cp, self.sp = cp, sp
        self.fx, self.fy, self.fz = cy_ * cp, sy_ * cp, -sp   # forward
        self.rx, self.ry = -sy_, cy_                          # right (horizontal)
        self.ux, self.uy, self.uz = sp * cy_, sp * sy_, cp    # up
        self.fhx, self.fhy = cy_, sy_                         # horizontal forward

    def project(self, x, y, z):
        """Project one world point. Returns (sx, sy, depth) or None if behind the camera."""
        dx, dy, dz = x - self.cx, y - self.cy, z - self.cz
        zc = dx * self.fx + dy * self.fy + dz * self.fz
        if zc < NEAR:
            return None
        xc = dx * self.rx + dy * self.ry
        yc = dx * self.ux + dy * self.uy + dz * self.uz
        return HW + self.focal * xc / zc, HH - self.focal * yc / zc, zc

    def project_poly(self, pts):
        """Project a world-space polygon. Returns (screen_points, avg_depth) or None."""
        cx, cy, cz = self.cx, self.cy, self.cz
        rx, ry = self.rx, self.ry
        ux, uy, uz = self.ux, self.uy, self.uz
        fx, fy, fz = self.fx, self.fy, self.fz
        cam = []
        zmin, zmax = 1e9, -1e9
        for x, y, z in pts:
            dx, dy, dz = x - cx, y - cy, z - cz
            zc = dx * fx + dy * fy + dz * fz
            cam.append((dx * rx + dy * ry, dx * ux + dy * uy + dz * uz, zc))
            if zc < zmin:
                zmin = zc
            if zc > zmax:
                zmax = zc
        if zmax < NEAR:
            return None
        if zmin < NEAR:
            cam = _clip_near(cam)
            if len(cam) < 3:
                return None
        focal = self.focal
        out = []
        dsum = 0.0
        for x, y, z in cam:
            out.append((HW + focal * x / z, HH - focal * y / z))
            dsum += z
        return out, dsum / len(cam)

    def _emit(self, surf, scr, rgb, ink=None):
        xs = [p[0] for p in scr]
        ys = [p[1] for p in scr]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        if maxx < 0 or minx > W or maxy < 0 or miny > H:
            return
        if maxx - minx < 1 and maxy - miny < 1:
            return
        pygame.draw.polygon(surf, rgb, scr)
        if ink is not None:
            pygame.draw.polygon(surf, ink, scr, 1)
        self.polys += 1

    def _poly(self, surf, pts, rgb, ink=None):
        pr = self.project_poly(pts)
        if pr:
            self._emit(surf, pr[0], rgb, ink)

    def _poly_fog(self, surf, pts, base, shade):
        """Flat polygon whose fog band comes from its own depth. Returns depth (or None)."""
        pr = self.project_poly(pts)
        if not pr:
            return None
        self._emit(surf, pr[0], self.col(base, shade, self.fog_band(pr[1])))
        return pr[1]

    def _ground_row(self, depth):
        """Screen row of the ground plane at a given camera-space depth."""
        cz = self.cz - self.gbase
        d = (depth - cz * self.sp) / self.cp
        yc = d * self.sp - cz * self.cp
        return HH - self.focal * yc / depth

    # ---------------------------------------------------------------- frame
    def render(self, surf, car, cam, others=(), t=0.0, markers=(), trains=(), extras=()):
        """extras: battle-mode things (game/battle.py extras(): balloons, item boxes, pucks, seekers, slicks)."""
        self._set_camera(cam)
        self.time = t
        self.polys = 0
        self.n_buildings = 0
        h0 = int(HH - self.focal * math.tan(self.pitch))  # horizon row
        h0 = max(0, min(H, h0))
        cars = [car] + self._visible_cars(list(others) + self.parked_cars())
        self._draw_sky(surf, h0)
        self._draw_clouds(surf, h0)
        if not self.st.get("hide_horizon"):
            self._draw_hills(surf, h0)
            self._draw_horizon(surf)
        self.gbase = self._g(self.cx, self.cy)
        self._draw_ground(surf, h0)
        self._draw_terrain(surf)
        self._compute_horizon()
        self._draw_flat(surf)
        grounded = [c for c in cars if getattr(c, "z", 0.0) - self._g(c.x, c.y) < 0.5]     # no ground shadow under a car up on a deck
        if self.st["cast_shadows"]:
            self._draw_shadow_layer(surf, grounded)
        else:
            for c in grounded:
                self._draw_shadow(surf, c)
        self._draw_objects(surf, car, cars, markers, trains, extras)
        if self.st.get("snowfall"):
            self._draw_snowfall(surf)

    def _draw_snowfall(self, surf):
        """Falling snow: fixed pseudo-random flakes in screen space that drift with time and slide as you turn."""
        n = self.st["snowfall"]
        t = self.time
        pan = self.yaw * self.focal                       # turning sweeps the flakes sideways
        white, grey = (250, 252, 255), (206, 214, 228)
        for i in range(n):
            seed = (i * 2654435761) & 0xFFFFFFFF
            fall = 18.0 + (seed & 31)                      # pixels per second, near flakes fall faster
            x = ((seed >> 5) % 997) * 0.37 + 6.0 * math.sin(t * 0.9 + i) - pan * (0.6 + (i & 3) * 0.2)
            y = ((seed >> 15) % 600) + t * fall
            px, py = int(x) % (W + 4) - 2, int(y) % (H + 4) - 2
            big = (seed >> 27) & 3 == 0
            surf.fill(white if big else grey, (px, py, 2 if big else 1, 2 if big else 1))

    def parked_cars(self):
        """Car objects for the world's hand-placed parked cars (built once)."""
        if self._parked_cars is None:
            self._parked_cars = []
            for p in getattr(self.world, "parked", ()):
                c = Car(p["x"], p["y"], p["heading"], model=p.get("model") if p.get("model") in MODELS else "sedan")
                body = tuple(p.get("colour") or (90, 94, 102))
                c.palette = {"body": body, "lower": (30, 30, 40), "glass": (52, 62, 84), "tail": (200, 40, 40),
                             "roof": tuple(p.get("roof_colour") or body), "lightbar": False}
                c.kind = "parked"
                c.z = self.world.ground(c.x, c.y) if hasattr(self.world, "ground") else 0.0
                self._parked_cars.append(c)
        return self._parked_cars

    def _visible_cars(self, others):
        out = []
        for o in others:
            dx, dy = o.x - self.cx, o.y - self.cy
            if math.hypot(dx, dy) > DRAW_DIST or dx * self.fhx + dy * self.fhy < -6.0:
                continue
            out.append(o)
        return out

    def _draw_sky(self, surf, h0):
        st = self.st
        surf.fill(st["sky_bottom"])
        if h0 <= 0:
            return
        n = st["sky_bands"]
        for i in range(n):
            colour = _lerp_rgb(st["sky_top"], st["sky_bottom"], i / (n - 1))
            y0 = int(h0 * i / n)
            y1 = int(h0 * (i + 1) / n) + 1
            surf.fill(colour, (0, y0, W, y1 - y0))

    def _draw_clouds(self, surf, h0):
        if not self.clouds or h0 <= 0:
            return
        shade = _lerp_rgb((255, 255, 255), self.st["sky_top"], 0.22)
        for az, elev, blobs in self.clouds:
            rel = (az - self.yaw + math.pi) % (2 * math.pi) - math.pi
            if abs(rel) > 1.2:
                continue
            sx = HW + self.focal * math.tan(rel)
            sy = h0 - elev
            if sx < -100 or sx > W + 100:
                continue
            for dx, dy, rx, ry in blobs:     # blue-grey underside first, white on top
                pygame.draw.ellipse(surf, shade, (sx + dx - rx, sy + dy - ry + 3, 2 * rx, 2 * ry))
            for dx, dy, rx, ry in blobs:
                pygame.draw.ellipse(surf, (255, 255, 255), (sx + dx - rx, sy + dy - ry, 2 * rx, 2 * ry))

    def _draw_hills(self, surf, h0):
        """Two parallax ridge lines fixed to world azimuth, so they slide as you steer."""
        for colour, base, amp, f1, f2, ph in ((self.st["hill_far"], 7, 13, 2.0, 5.0, 0.7),
                                              (self.st["hill_near"], 2, 9, 3.0, 8.0, 2.1)):
            pts = [(0, h0 + 2)]
            for sx in range(0, W + 1, 8):
                ang = self.yaw + math.atan((sx - HW) / self.focal)
                hgt = base + amp * (0.5 + 0.5 * math.sin(ang * f1 + ph)) + 0.4 * amp * math.sin(ang * f2 + ph * 2)
                pts.append((sx, h0 - max(0.0, hgt)))
            pts.append((W, h0 + 2))
            pygame.draw.polygon(surf, colour, pts)

    def _draw_horizon(self, surf):
        """Wind turbines on the skyline, at their real bearing and distance, blades turning.

        Far ones are drawn up to 2.6x larger than life so they read at 320x224 (forced perspective);
        the ground drawn afterwards hides their bases behind the land.
        """
        st = self.st
        for t in getattr(self.world, "horizon", ()):
            d = math.hypot(t["x"] - self.cx, t["y"] - self.cy)
            if d < 60.0 or d > 9000.0:
                continue
            sc = 1.0 + 1.6 * max(0.0, min(1.0, (d - 400.0) / 1600.0))
            tg = self._g(t["x"], t["y"])
            base = self.project(t["x"], t["y"], tg)
            hub = self.project(t["x"], t["y"], tg + t["h"] * sc)
            if base is None or hub is None or hub[0] < -60 or hub[0] > W + 60:
                continue
            colour = _lerp_rgb(st["turbine"], st["fog"], min(0.6, d / 9000.0 * 0.9))
            width = 2 if d < 1200 else 1
            pygame.draw.line(surf, colour, base[:2], hub[:2], width)
            bl = self.focal * t["blade"] * sc / hub[2]
            ang = t.get("phase", 0.0) + self.time * 2.2
            for k in range(3):
                a = ang + k * 2 * math.pi / 3
                pygame.draw.line(surf, colour, hub[:2], (hub[0] + bl * math.cos(a), hub[1] + bl * math.sin(a)), width)
            pygame.draw.circle(surf, colour, (int(hub[0]), int(hub[1])), max(1, width))

    def _draw_ground(self, surf, h0):
        if h0 >= H:
            return
        grass = self.st["grass"]
        surf.fill(self.col(grass, 3, FOG_BANDS - 1), (0, h0, W, H - h0))
        for k in range(FOG_BANDS - 2, -1, -1):
            top = int(self._ground_row(FOG_START + k * FOG_STEP))
            top = max(h0, top)
            if top < H:
                surf.fill(self.col(grass, 3, k), (0, top, W, H - top))

    def _draw_terrain(self, surf):
        """The land itself as a mesh of grid cells, far to near, shaded by slope. Only drawn when the map has heights."""
        t = self.terrain
        if t is None:
            return
        step = t.step
        r = DRAW_DIST + step
        cx, cy = self.cx, self.cy
        i0, i1 = int((cx - r - t.x0) // step), int((cx + r - t.x0) // step) + 1
        j0, j1 = int((cy - r - t.y0) // step), int((cy + r - t.y0) // step) + 1
        i0, j0 = max(i0, -1), max(j0, -1)
        i1, j1 = min(i1, t.nx), min(j1, t.ny)
        flat_idx = shade_index(0.0, 0.0, 1.0)
        grass = self.st["grass"]
        cells = []
        for j in range(j0, j1):
            for i in range(i0, i1):
                mx, my = t.x0 + (i + 0.5) * step, t.y0 + (j + 0.5) * step
                dx, dy = mx - cx, my - cy
                d2 = dx * dx + dy * dy
                if d2 > r * r:
                    continue
                fwd = dx * self.fhx + dy * self.fhy
                if fwd < -step or abs(dx * self.rx + dy * self.ry) > fwd * 0.95 + step * 1.5:
                    continue
                cells.append((d2, i, j, mx, my))
        cells.sort(reverse=True)
        for _d2, i, j, mx, my in cells:
            x0, y0 = t.x0 + i * step, t.y0 + j * step
            x1, y1 = x0 + step, y0 + step
            a, b, c, d = t.node(i, j), t.node(i + 1, j), t.node(i, j + 1), t.node(i + 1, j + 1)  # corners are nodes
            pts = [(x0, y0, a), (x1, y0, b), (x1, y1, d), (x0, y1, c)]
            idx = shade_index(*t.cell_normal(a, b, c, d))
            sh = max(0, min(3, 3 + idx - flat_idx))
            if (i + j) & 1 and sh > 1:
                sh -= 1                                         # faint chequer so a gentle slope still reads as 3D
            self._poly_fog(surf, pts, grass, sh)

    def _visible_pieces(self, grid, extra=PIECE_LEN):
        """Yield pieces from a spatial grid that are in range and roughly in front of the camera."""
        cx, cy = self.cx, self.cy
        r = DRAW_DIST + extra
        r2 = r * r
        fhx, fhy, rx, ry = self.fhx, self.fhy, self.rx, self.ry
        for gx in range(int((cx - r) // CELL), int((cx + r) // CELL) + 1):
            for gy in range(int((cy - r) // CELL), int((cy + r) // CELL) + 1):
                for pc in grid.get((gx, gy), ()):
                    mx, my = pc[-2], pc[-1]
                    dx, dy = mx - cx, my - cy
                    fwd = dx * fhx + dy * fhy
                    if fwd < -extra or dx * dx + dy * dy > r2:
                        continue
                    if abs(dx * rx + dy * ry) > fwd * 0.95 + 30.0:
                        continue
                    yield pc

    @staticmethod
    def _quad(x0, y0, x1, y1, dx, dy, hw, z, ext=0.3, g0=0.0, g1=0.0):
        """Flat strip from (x0,y0) to (x1,y1); g0/g1 lift each end to the ground height under it."""
        nx, ny = -dy * hw, dx * hw
        ax, ay = x0 - dx * ext, y0 - dy * ext
        bx, by = x1 + dx * ext, y1 + dy * ext
        za, zb = z + g0, z + g1
        return [(ax + nx, ay + ny, za), (bx + nx, by + ny, zb), (bx - nx, by - ny, zb), (ax - nx, ay - ny, za)]

    def _compute_horizon(self):
        """Hills hide what is behind them (no depth buffer here: the land is painted first, so without this buildings
        and roads beyond a crest show through it). For each of OCC_COLS screen columns, march outwards over the land
        and keep, for every distance, the highest screen row the nearer land already reaches. Objects further away are
        then clipped at that row (_occ_row). One vectorised pass per frame; nothing when the world is flat."""
        if self._tgrid is None:
            self._occ = None
            return
        t, g = self.terrain, self._tgrid
        k = int((DRAW_DIST - OCC_START) / OCC_STEP) + 1
        sx = (np.arange(OCC_COLS) + 0.5) * (W / OCC_COLS)
        ang = self.yaw + np.arctan((sx - HW) / self.focal)
        d = OCC_START + OCC_STEP * np.arange(k)
        px = self.cx + np.cos(ang)[:, None] * d[None, :]
        py = self.cy + np.sin(ang)[:, None] * d[None, :]
        fx = np.clip((px - t.x0) / t.step, 0, t.nx - 1.001)
        fy = np.clip((py - t.y0) / t.step, 0, t.ny - 1.001)
        i, j = fx.astype(np.int32), fy.astype(np.int32)
        tx, ty = fx - i, fy - j
        top = g[j, i] + (g[j, i + 1] - g[j, i]) * tx
        z = top + (g[j + 1, i] + (g[j + 1, i + 1] - g[j + 1, i]) * tx - top) * ty
        dx, dy, dz = px - self.cx, py - self.cy, z - OCC_SLACK - self.cz       # small bumps do not hide things
        zc = dx * self.fx + dy * self.fy + dz * self.fz
        yc = dx * self.ux + dy * self.uy + dz * self.uz
        rows = np.where(zc > NEAR, HH - self.focal * yc / np.maximum(zc, NEAR), float(H))
        occ = np.minimum.accumulate(rows, axis=1)
        # the first distance step at which land is hidden behind nearer land, in any column: nothing nearer than that
        # can be behind a hill, so most objects skip the lookup (on flat or falling ground, all of them)
        hidden = rows[:, 1:] > occ[:, :-1] + 1.0
        first = np.where(hidden.any(axis=1), hidden.argmax(axis=1) + 1, k)
        self._occ_first = int(first.min())
        self._occ = occ.tolist()                                              # plain lists: fast single lookups

    def _occ_row(self, x, y, z, dist):
        """Screen row above which an object at (x, y, z) (absolute height) can be seen: H when no hill is in front of
        it. `dist` is the distance to the object's NEAREST point (its near end), so the land under the object itself
        never cuts it. Uses the column it projects into and its neighbours (the most generous of the three)."""
        occ = self._occ
        if occ is None:
            return H
        k = int((dist - OCC_START - OCC_MARGIN) / OCC_STEP)
        if k < self._occ_first:
            return H                                    # nearer than any crest
        p = self.project(x, y, z)
        if p is None:
            return H
        c = min(OCC_COLS - 1, max(0, int(p[0] * OCC_COLS / W)))
        k = min(k, len(occ[0]) - 1)
        row = max(occ[c - 1][k] if c else occ[c][k], occ[c][k], occ[c + 1][k] if c < OCC_COLS - 1 else occ[c][k])
        return row if row < p[1] - 1.0 else H          # only a hill that rises above the object's foot hides anything

    def _draw_flat(self, surf):
        st = self.st
        # parks: lawn, and crossing paths in a town square
        for pk in getattr(self.world, "parks", ()):
            x0, y0, x1, y1 = pk["bbox"]
            if x1 < self.cx - DRAW_DIST or x0 > self.cx + DRAW_DIST or y1 < self.cy - DRAW_DIST or y0 > self.cy + DRAW_DIST:
                continue
            self._poly_fog(surf, [(p[0], p[1], 0.005 + self._g(p[0], p[1])) for p in pk["points"]], st["park"], 3)
            if pk.get("landmark") == "square":
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                for a, b in (((x0 + 2, my), (x1 - 2, my)), ((mx, y0 + 2), (mx, y1 - 2))):
                    L = math.hypot(b[0] - a[0], b[1] - a[1])
                    dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                    self._poly_fog(surf, self._quad(a[0], a[1], b[0], b[1], dx, dy, 1.3, 0.008, ext=0.0,
                                                    g0=self._g(a[0], a[1]), g1=self._g(b[0], b[1])), st["path"], 3)
        # open parking lots (game/parking.py): asphalt, with painted stall lines up close
        lots = getattr(self.world, "lots", ())
        if lots:
            if self._stalls is None:
                self._stalls = {}                                   # lot index -> stall lines, made when first near
            road = st["road"]
            base = road["side"] if isinstance(road, dict) else road
            asphalt = _lerp_rgb(base, (150, 150, 156), 0.25)
            paint = (236, 236, 228)
            for li, lot in enumerate(lots):
                x0, y0, x1, y1 = lot["bbox"]
                if x1 < self.cx - DRAW_DIST or x0 > self.cx + DRAW_DIST or y1 < self.cy - DRAW_DIST or y0 > self.cy + DRAW_DIST:
                    continue
                self._poly_fog(surf, [(p[0], p[1], 0.012 + self._g(p[0], p[1])) for p in lot["points"]], asphalt, 3)
                if x1 < self.cx - STALL_DIST or x0 > self.cx + STALL_DIST or y1 < self.cy - STALL_DIST or y0 > self.cy + STALL_DIST:
                    continue
                if li not in self._stalls:
                    from .parking import stall_lines
                    self._stalls[li] = stall_lines(lot)
                for ax, ay, bx, by in self._stalls[li]:
                    if abs((ax + bx) / 2 - self.cx) > STALL_DIST or abs((ay + by) / 2 - self.cy) > STALL_DIST:
                        continue
                    a = self.project(ax, ay, 0.02 + self._g(ax, ay))
                    b = self.project(bx, by, 0.02 + self._g(bx, by))
                    if a and b:
                        pygame.draw.line(surf, self.col(paint, 3, self.fog_band(math.hypot(ax - self.cx, ay - self.cy))),
                                         (a[0], a[1]), (b[0], b[1]))
        # water
        for w in self.water:
            x0, y0, x1, y1 = w["bbox"]
            if x1 < self.cx - DRAW_DIST or x0 > self.cx + DRAW_DIST or y1 < self.cy - DRAW_DIST or y0 > self.cy + DRAW_DIST:
                continue
            wz = min(self._g(p[0], p[1]) for p in w["points"]) if self.terrain is not None else 0.0   # water is level
            self._poly_fog(surf, [(p[0], p[1], 0.01 + wz) for p in w["points"]], st["water"], 3)

        # rails
        for pc in self._visible_pieces(self.rail_grid):
            x0, y0, x1, y1, dx, dy, g0, g1, mx, my = pc
            d = self._poly_fog(surf, self._quad(x0, y0, x1, y1, dx, dy, 1.6, 0.02, g0=g0, g1=g1), st["rail_bed"], 2)
            if d is not None and d < 70:
                for off in (-0.72, 0.72):
                    ox, oy = -dy * off, dx * off
                    self._poly_fog(surf, self._quad(x0 + ox, y0 + oy, x1 + ox, y1 + oy, dx, dy, 0.1, 0.04,
                                                    g0=g0, g1=g1), st["rail"], 3)

        # roads, lowest class first; kerbs/sidewalks then fills so junctions merge cleanly
        buckets = {k: [] for k in ROAD_ORDER}
        behind = []                                            # pieces partly behind a hill: drawn clipped, last
        for pc in self._visible_pieces(self.road_grid):
            if self._occ is not None:
                mx, my = pc[14], pc[15]
                near = min(math.hypot(pc[0] - self.cx, pc[1] - self.cy), math.hypot(pc[2] - self.cx, pc[3] - self.cy))
                row = self._occ_row(mx, my, (pc[9] + pc[10]) / 2.0, near - pc[6])
                if row <= 0:
                    continue                                   # wholly behind a hill
                if row < H:
                    behind.append((row, pc))
                    continue
            buckets[pc[7]].append(pc)
        for cls in ROAD_ORDER:
            self._draw_road_pieces(surf, cls, buckets[cls])
        for row, pc in behind:
            surf.set_clip(pygame.Rect(0, 0, W, int(row) + 1))
            self._draw_road_pieces(surf, pc[7], [pc])
            surf.set_clip(None)
        # crosswalks and stop bars from the map's marks
        for pts, colour, _mx, _my in self._visible_pieces(self.paint_grid, 8.0):
            self._poly_fog(surf, pts, st["line"] if colour == "white" else st["line_yellow"], 3)

    def _draw_road_pieces(self, surf, cls, pieces):
        """Kerbs/sidewalks, then the surface, then paint, for road pieces of one class."""
        st = self.st
        sw_col, sw_w = st["sidewalk"], st["sidewalk_w"]
        for x0, y0, x1, y1, dx, dy, hw, _c, par, g0, g1, mk, sw, gv, mx, my in pieces:
            edge = st["gravel"] if gv and sw == 0 else sw_col[sw]
            self._poly_fog(surf, self._quad(x0, y0, x1, y1, dx, dy, hw + sw_w[sw], 0.01, g0=g0, g1=g1), edge, 3)
        base = st["road"][cls]
        for x0, y0, x1, y1, dx, dy, hw, _c, par, g0, g1, mk, sw, gv, mx, my in pieces:
            self._poly_fog(surf, self._quad(x0, y0, x1, y1, dx, dy, hw, 0.02, g0=g0, g1=g1),
                           st["gravel"] if gv else base, 3 if par else 2)
        for x0, y0, x1, y1, dx, dy, hw, _c, par, g0, g1, mk, sw, gv, mx, my in pieces:
            if mk:
                ddx, ddy = mx - self.cx, my - self.cy
                if ddx * ddx + ddy * ddy < PAINT_DIST * PAINT_DIST:
                    self._draw_marking(surf, mk, x0, y0, x1, y1, dx, dy, hw, g0, g1, mx, my)

    def _draw_marking(self, surf, mk, x0, y0, x1, y1, dx, dy, hw, g0, g1, mx, my):
        """Paint on one road piece: solid lines are full length, dashes are 3 m long, two per 20 m piece."""
        st = self.st
        white, yellow = st["line"], st["line_yellow"]
        gm = (g0 + g1) / 2.0

        def solid(off, width, col):
            ox, oy = -dy * off, dx * off
            self._poly_fog(surf, self._quad(x0 + ox, y0 + oy, x1 + ox, y1 + oy, dx, dy, width, 0.03, ext=0.0,
                                            g0=g0, g1=g1), col, 3)

        def dashes(off, width, col):
            ox, oy = -dy * off, dx * off
            for d in (-5.0, 5.0):
                cx, cy = mx + dx * d + ox, my + dy * d + oy
                self._poly_fog(surf, self._quad(cx - dx * 1.5, cy - dy * 1.5, cx + dx * 1.5, cy + dy * 1.5, dx, dy,
                                                width, 0.03, ext=0.0, g0=gm, g1=gm), col, 3)

        # offsets are to the RIGHT of the direction of travel along the piece
        if mk == SD.DOUBLE_YELLOW:
            solid(-0.2, 0.08, yellow)
            solid(0.2, 0.08, yellow)
        elif mk == SD.DASH_YELLOW:
            dashes(0.0, 0.1, yellow)
        elif mk == SD.DASH_WHITE:
            dashes(-hw / 3.0, 0.1, white)
            dashes(hw / 3.0, 0.1, white)
        elif mk == SD.HIGHWAY:
            solid(hw - 0.5, 0.1, white)
            solid(-hw + 0.5, 0.1, white)
            if hw >= 3.7:
                dashes(0.0, 0.1, white)
        elif mk == SD.EDGES:
            solid(hw - 0.5, 0.1, white)
            solid(-hw + 0.5, 0.1, yellow)

    @staticmethod
    def _car_footprint(car, shift=(0.0, 0.0)):
        fx, fy = car.forward
        rx, ry = car.right
        z = getattr(car, "z", 0.0) + 0.04
        return [(car.x + fx * a + rx * b + shift[0], car.y + fy * a + ry * b + shift[1], z)
                for a, b in ((2.4, -1.15), (2.4, 1.15), (-2.4, 1.15), (-2.4, -1.15))]

    def _draw_shadow(self, surf, car):
        self._poly(surf, self._car_footprint(car), self.st["car_shadow"])

    def _draw_shadow_layer(self, surf, cars):
        """Hard, see-through shadows for buildings and cars, drawn on one layer so overlaps don't stack."""
        if self._layer is None:
            self._layer = pygame.Surface((W, H), pygame.SRCALPHA)
        layer = self._layer
        layer.fill((0, 0, 0, 0))
        rgba = self.st["cast_shadows"]
        sdx, sdy = self.st.get("shadow_dir", SHADOW_DIR)
        cx, cy = self.cx, self.cy
        fhx, fhy, rx, ry = self.fhx, self.fhy, self.rx, self.ry
        reach = 130.0
        for i in self.world.buildings_near(cx, cy, reach):
            b = self.buildings.get(i)
            if b is None:
                continue
            bx, by, h, _ci, _w, fp, rad = b
            dx, dy = bx - cx, by - cy
            if dx * dx + dy * dy > (reach + rad) ** 2:
                continue
            fwd = dx * fhx + dy * fhy
            slack = rad + h
            if fwd < -slack or abs(dx * rx + dy * ry) > fwd * 1.1 + slack + 6.0:
                continue
            hull = _hull(fp + [(x + sdx * h, y + sdy * h) for x, y in fp])
            gz = self._building_ground(i)[0] + 0.05
            pr = self.project_poly([(x, y, gz) for x, y in hull])
            if pr:
                pygame.draw.polygon(layer, rgba, pr[0])
        for p in self.world.props_near(cx, cy, 100.0, far=0) if hasattr(self.world, "props_near") else ():
            if p["kind"] in ("lamp", "car_block", "fence") or p["kind"] in DETAIL_KINDS or (p["x"] - cx) * fhx + (p["y"] - cy) * fhy < -10.0:
                continue
            ox, oy, rr = p["x"] + sdx * p["h"] * 0.6, p["y"] + sdy * p["h"] * 0.6, p["r"] * 0.9
            gz = self._g(p["x"], p["y"]) + 0.05
            pr = self.project_poly([(ox + rr * math.cos(a), oy + rr * math.sin(a), gz) for a in OCT8])
            if pr:
                pygame.draw.polygon(layer, rgba, pr[0])
        for c in cars:
            pr = self.project_poly(self._car_footprint(c, (sdx * 0.6, sdy * 0.6)))
            if pr:
                pygame.draw.polygon(layer, rgba, pr[0])
        surf.blit(layer, (0, 0))

    # -------------------------------------------------------------- objects
    def _draw_objects(self, surf, car, cars, markers=(), trains=(), extras=()):
        cx, cy = self.cx, self.cy
        fhx, fhy, rx, ry = self.fhx, self.fhy, self.rx, self.ry
        objs = []
        for i in self.world.buildings_near(cx, cy, DRAW_DIST):
            b = self.buildings.get(i)
            if b is None:
                continue
            bx, by, _h, _ci, _w, _p, rad = b
            dx, dy = bx - cx, by - cy
            dist = math.hypot(dx, dy)
            if dist - rad > DRAW_DIST:
                continue
            fwd = dx * fhx + dy * fhy
            if fwd < -rad or abs(dx * rx + dy * ry) > fwd * 0.95 + rad + 6.0:
                continue
            self._emit_building(objs, i, b, dist)
        for p in self.world.props_near(cx, cy, PROP_DIST) if hasattr(self.world, "props_near") else ():
            if p["kind"] == "car_block":
                continue                                 # a parked car's collision circle: the car is drawn as a car
            dx, dy = p["x"] - cx, p["y"] - cy
            fwd = dx * fhx + dy * fhy
            if fwd < -3.0 or abs(dx * rx + dy * ry) > fwd * 0.95 + 6.0:
                continue
            d = math.hypot(dx, dy)
            if d > DETAIL_DIST and p["kind"] in DETAIL_KINDS:
                continue
            objs.append((d, 2, p))
        for c in cars:
            objs.append((math.hypot(c.x - cx, c.y - cy), 1, c))
        for u in trains:                         # train blocks: sorted like cars
            dx, dy = u.x - cx, u.y - cy
            if dx * dx + dy * dy < DRAW_DIST * DRAW_DIST and dx * fhx + dy * fhy > -u.length:
                objs.append((math.hypot(dx, dy), 6, u))
        for e in extras:                        # battle items, sorted with everything else
            dx, dy = e["x"] - cx, e["y"] - cy
            if dx * dx + dy * dy < PROP_DIST * PROP_DIST and dx * fhx + dy * fhy > -4.0:
                objs.append((math.hypot(dx, dy) - (0.3 if e["kind"] == "balloon" else 0.0), 7, e))
        for m in markers:                       # mission beacons show from further away than buildings
            dx, dy = m["x"] - cx, m["y"] - cy
            d = math.hypot(dx, dy)
            if d < 600.0 and dx * fhx + dy * fhy > -m["radius"]:
                objs.append((d, 3, m))
        for pc in self.span_pieces:
            dx, dy = pc[9] - cx, pc[10] - cy
            dist = math.hypot(dx, dy)
            if dist > DRAW_DIST or dx * fhx + dy * fhy < -SPAN_PIECE:
                continue
            objs.append((dist + 11.0, 4, pc))      # +11: a deck piece is painted before cars standing on it
        self._fix_wall_order(objs)                        # cars/props hugging a wall: put them on the right side of it
        objs.sort(key=lambda o: o[0], reverse=True)       # painter's algorithm: far to near
        flat = self.terrain is None
        occ = self._occ is not None
        for dist, kind, obj in objs:
            if occ and kind != 4:                                  # behind a hill? clip at the hill's horizon line
                if kind == 0:
                    ox, oy = (obj[2] + obj[4]) / 2.0, (obj[3] + obj[5]) / 2.0
                    near = min(math.hypot(obj[2] - self.cx, obj[3] - self.cy), math.hypot(obj[4] - self.cx, obj[5] - self.cy))
                    oz = self._building_ground(obj[0])[0] - self._building_ground(obj[0])[1]
                elif kind == 5:
                    ox, oy = self.buildings[obj][0], self.buildings[obj][1]
                    near = math.hypot(ox - self.cx, oy - self.cy) - self.buildings[obj][6]
                    oz = self._building_ground(obj)[0]
                elif kind in (2, 3, 7):
                    ox, oy = obj["x"], obj["y"]
                    near = dist - 1.5
                    oz = None
                else:
                    ox, oy = obj.x, obj.y
                    near = dist - 2.5
                    oz = getattr(obj, "z", None)
                if (near - OCC_START - OCC_MARGIN) / OCC_STEP < self._occ_first:
                    self._draw_object(surf, car, dist, kind, obj, flat)        # nearer than any crest
                    continue
                row = self._occ_row(ox, oy, self._g(ox, oy) if oz is None else oz, near)
                if row <= 0:
                    continue
                if row < H:
                    surf.set_clip(pygame.Rect(0, 0, W, int(row) + 1))
                    self._draw_object(surf, car, dist, kind, obj, flat)
                    surf.set_clip(None)
                    continue
            self._draw_object(surf, car, dist, kind, obj, flat)

    def _draw_object(self, surf, car, dist, kind, obj, flat):
        """Draw one scene object (wall piece, building top, prop, marker, train unit, deck piece or car)."""
        if kind == 0:
            g = 0.0 if flat else self._building_ground(obj[0])[0]
            self.cz -= g                    # everything on the ground is drawn as if the ground were at z=0
            self._draw_wall_piece(surf, obj, dist)
            self.cz += g
        elif kind == 5:
            g = 0.0 if flat else self._building_ground(obj)[0]
            self.cz -= g
            self._draw_building_top(surf, obj, dist)
            self.cz += g
        elif kind == 2:
            g = 0.0 if flat else self._g(obj["x"], obj["y"])
            self.cz -= g
            self._draw_prop(surf, obj, dist)
            self.cz += g
        elif kind == 3:
            g = 0.0 if flat else self._g(obj["x"], obj["y"])
            self.cz -= g
            self._draw_marker(surf, obj, dist)
            self.cz += g
        elif kind == 6:
            g = 0.0 if flat else self._g(obj.x, obj.y)
            self.cz -= g
            self._draw_train_unit(surf, obj, self.fog_band(dist))
            self.cz += g
        elif kind == 4:
            self._draw_deck_piece(surf, obj, dist - 11.0)
        elif kind == 7:
            g = 0.0 if flat else self._g(obj["x"], obj["y"])
            self.cz -= g
            self._draw_battle_thing(surf, obj, dist)
            self.cz += g
        else:
            z = getattr(obj, "z", 0.0)
            if z > 0.01:                    # raised car: same as lowering the camera by z
                self.cz -= z
                self._draw_car(surf, obj, 0 if obj is car else self.fog_band(dist))
                self.cz += z
            else:
                self._draw_car(surf, obj, 0 if obj is car else self.fog_band(dist))

    def _wall(self, surf, a, b, z0, z1, out, base, fog, ink):
        """A vertical quad from point a to b (x, y, base heights ha, hb) between offsets z0..z1, if it faces the camera.
        `out` is the horizontal normal (nx, ny); a and b are (x, y, h)."""
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if (self.cx - mx) * out[0] + (self.cy - my) * out[1] <= 0:
            return
        pts = [(a[0], a[1], a[2] + z0), (b[0], b[1], b[2] + z0), (b[0], b[1], b[2] + z1), (a[0], a[1], a[2] + z1)]
        self._poly(surf, pts, self.col(base, shade_index(out[0], out[1], 0.0), fog), ink)

    def _draw_deck_piece(self, surf, pc, dist):
        """One 10 m piece of an overpass: embankment on the ramps, road slab, concrete barriers."""
        x0, y0, h0, x1, y1, h1, dx, dy, hw, mx, my, top = pc
        g0, g1 = self._g(x0, y0), self._g(x1, y1)
        ramp = (h0 > 0.15 or h1 > 0.15) and min(h0, h1) < top - 0.02    # (relative heights) ramps only
        h0, h1 = h0 + g0, h1 + g1                               # deck heights are stored above the ground
        fog = self.fog_band(dist)
        ink = self.ink(fog)
        st = self.st
        nx, ny = -dy, dx                                        # left-hand normal; the right side is -n
        side = 1.0 if (self.cx - mx) * nx + (self.cy - my) * ny > 0 else -1.0   # +1: camera is on the left
        wallc = (196, 194, 188) if st["ink"] is not None else (150, 150, 150)
        kerb = hw + 0.5
        slope0 = hw + 0.75                                      # the embankment starts just outside the barrier
        # embankment: grass slope from the deck edge down to the ground (only where the deck is raised)
        if ramp:                                                # ramps only: the bridge itself spans open air
            for sgn in (-side, side):                           # far side first, then the deck covers it
                ox, oy = nx * sgn, ny * sgn
                e0, e1 = max(0.0, h0 - g0) * 1.7, max(0.0, h1 - g1) * 1.7
                pts = [(x0 + ox * slope0, y0 + oy * slope0, h0 - 0.2), (x1 + ox * slope0, y1 + oy * slope0, h1 - 0.2),
                       (x1 + ox * (slope0 + e1), y1 + oy * (slope0 + e1), g1 + 0.01),
                       (x0 + ox * (slope0 + e0), y0 + oy * (slope0 + e0), g0 + 0.01)]
                self._poly(surf, pts, self.col(st["grass"], 2 if sgn == side else 0, fog))
        # slab: the road surface, with a thick concrete edge on the camera's side
        deck = [(x0 + nx * kerb, y0 + ny * kerb, h0), (x1 + nx * kerb, y1 + ny * kerb, h1),
                (x1 - nx * kerb, y1 - ny * kerb, h1), (x0 - nx * kerb, y0 - ny * kerb, h0)]
        ex, ey = nx * kerb * side, ny * kerb * side
        a, b = (x0 + ex, y0 + ey, h0), (x1 + ex, y1 + ey, h1)
        self._wall(surf, a, b, -1.1, 0.0, (nx * side, ny * side), wallc, fog, ink)
        if min(h0 - g0, h1 - g1) > 1.2 and self.cz < min(h0, h1) - 1.1:          # seen from underneath: the slab's belly
            self._poly(surf, [(px, py, ph - 1.1) for px, py, ph in deck], self.col(wallc, 0, fog), ink)
        self._poly(surf, deck, self.col(st["kerb"], 3, fog))
        self._poly_fog(surf, [(x0 + nx * hw, y0 + ny * hw, h0 + 0.01), (x1 + nx * hw, y1 + ny * hw, h1 + 0.01),
                              (x1 - nx * hw, y1 - ny * hw, h1 + 0.01), (x0 - nx * hw, y0 - ny * hw, h0 + 0.01)],
                       st["road"]["main"], 2)
        # barriers along both edges: inner face visible from the road, outer face from beside it
        for sgn in (-side, side):
            ox, oy = nx * sgn * (hw + 0.2), ny * sgn * (hw + 0.2)
            a, b = (x0 + ox, y0 + oy, h0), (x1 + ox, y1 + oy, h1)
            inward = (-nx * sgn, -ny * sgn)
            outward = (nx * sgn, ny * sgn)
            self._wall(surf, a, b, 0.0, 0.85, inward, wallc, fog, ink)
            self._wall(surf, a, b, 0.0, 0.85, outward, wallc, fog, ink)
            if self.cz > h0 + 0.85:
                tx, ty = nx * sgn * 0.3, ny * sgn * 0.3
                self._poly(surf, [(a[0] + tx, a[1] + ty, h0 + 0.85), (b[0] + tx, b[1] + ty, h1 + 0.85),
                                  (b[0] - tx, b[1] - ty, h1 + 0.85), (a[0] - tx, a[1] - ty, h0 + 0.85)],
                           self.col(wallc, 3, fog), ink)

    def _fix_wall_order(self, objs):
        """Correct sort keys of cars and props against the wall pieces next to them (in place).

        Centre distances are not enough near a wall: a tree on the sidewalk can be further from the camera than the
        middle of the 12 m wall piece behind it (seen at a slant), so the wall would be painted over the tree. For each
        car/prop within ORDER_NEAR metres of a visible wall piece whose screen area it overlaps (the line of sight
        from the camera through the object crosses the piece), the object must be painted after the piece when it
        stands in front of the wall plane and before it when it is behind. Only the object's key moves (the walls
        stay where they are), and if the two rules disagree the key is left alone.
        """
        cx, cy = self.cx, self.cy
        grid = {}
        for o in objs:
            if o[1] == 0:
                p = o[2]
                x0, y0, x1, y1 = p[2], p[3], p[4], p[5]
                for gx in range(int(min(x0, x1) // ORDER_CELL), int(max(x0, x1) // ORDER_CELL) + 1):
                    for gy in range(int(min(y0, y1) // ORDER_CELL), int(max(y0, y1) // ORDER_CELL) + 1):
                        grid.setdefault((gx, gy), []).append(o)
        if not grid:
            return
        for n, o in enumerate(objs):
            kind = o[1]
            if kind == 1:
                ox, oy, rad = o[2].x, o[2].y, 2.4
            elif kind == 2:
                ox, oy, rad = o[2]["x"], o[2]["y"], 1.5
            else:
                continue
            gx0, gy0 = int(ox // ORDER_CELL), int(oy // ORDER_CELL)
            lo, hi, seen = -1e18, 1e18, set()
            for gx in (gx0 - 1, gx0, gx0 + 1):
                for gy in (gy0 - 1, gy0, gy0 + 1):
                    for w in grid.get((gx, gy), ()):
                        if id(w) in seen:
                            continue
                        seen.add(id(w))
                        p = w[2]
                        x0, y0, x1, y1, nx, ny = p[2], p[3], p[4], p[5], p[6], p[7]
                        s = (ox - x0) * nx + (oy - y0) * ny                # object's side of the wall (+ = camera side)
                        if abs(s) > ORDER_NEAR or abs(s) < 0.05:
                            continue
                        sc = (cx - x0) * nx + (cy - y0) * ny               # camera's side (> 0: wall faces us)
                        if sc <= s:
                            continue                                       # object level with or behind the camera
                        L = math.hypot(x1 - x0, y1 - y0)
                        if L < 1e-6:
                            continue
                        tx, ty = (x1 - x0) / L, (y1 - y0) / L
                        ac, ao = (cx - x0) * tx + (cy - y0) * ty, (ox - x0) * tx + (oy - y0) * ty
                        hit = ac + (ao - ac) * sc / (sc - s)               # where the sight line meets the wall plane
                        if hit < -rad or hit > L + rad:
                            continue                                       # not overlapping on screen
                        if s > 0:
                            hi = min(hi, w[0])                             # in front: key below the wall's
                        else:
                            lo = max(lo, w[0])                             # behind: key above the wall's
            key = o[0]
            if hi < 1e18 and key >= hi and lo < hi - 0.02:
                key = hi - 0.01
            if lo > -1e18 and key <= lo and hi > lo + 0.02:
                key = lo + 0.01
            if key != o[0]:
                objs[n] = (key, kind, o[2])

    def _emit_building(self, objs, idx, b, dist):
        """Queue a building as separate wall pieces plus its top, each sorted by its own distance.

        Sorting a whole building by one distance made big buildings pop in front of or behind cars, trees and
        their neighbours. Long walls are cut into WALL_PIECE-metre pieces so each piece sorts where it really is.
        """
        walls = b[4]
        cx, cy = self.cx, self.cy
        best = None
        for wi, (x0, y0, x1, y1, nx, ny, sh) in enumerate(walls):
            if (cx - x0) * nx + (cy - y0) * ny <= 0:
                continue                                        # back-facing
            L = math.hypot(x1 - x0, y1 - y0)
            n = math.ceil(L / WALL_PIECE) if L > WALL_PIECE * 1.25 else 1
            first = len(objs)
            keys = []
            for k in range(n):
                t0, t1 = k / n, (k + 1) / n
                px0, py0 = x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0
                px1, py1 = x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1
                d = math.hypot((px0 + px1) / 2 - cx, (py0 + py1) / 2 - cy)
                keys.append(d)
                objs.append((d, 0, [idx, wi, px0, py0, px1, py1, nx, ny, sh, False]))
            nearest = first + keys.index(min(keys))
            objs[nearest][2][9] = True                          # graffiti is painted with the nearest piece
            best = min(keys) if best is None else min(best, min(keys))
        self.n_buildings += 1
        ex = self.extras.get(idx)
        has_top = self.cz - self._building_ground(idx)[0] > b[2] or (ex and (ex.get("roof") or ex["landmark"] in ("courthouse", "church")))
        if has_top:
            objs.append(((best - 0.5) if best is not None else dist, 5, idx))   # roof and towers go on top of the walls

    def _house(self, idx):
        """House type and front wall for building idx (None for non-houses). Worked out once, the first time it is
        drawn up close, so loading the map stays fast."""
        if idx not in self._houses:
            info = archetypes.classify(self.world.buildings[idx], idx)
            if info is not None and info["kind"] != "apartment":
                walls = self.buildings[idx][4]
                ex = self.extras.get(idx) or {}
                if ex.get("front") is not None:                              # hand-set: compass bearing the front faces
                    fb = math.radians(ex["front"])
                    fx, fy = math.sin(fb), -math.cos(fb)
                    front = max(range(len(walls)), key=lambda k: walls[k][4] * fx + walls[k][5] * fy)
                else:
                    front = archetypes.front_wall(walls, self.world.on_road)
                info = dict(info, front=front)
                info["door"] = ex["door_at"] if ex.get("door_at") is not None else 0.3 + 0.4 * archetypes._coin(idx, 3)
                info["door_rgb"] = tuple(ex["door"]) if ex.get("door") else None
                info["sidelights"] = bool(ex.get("sidelights"))
                info["shutters"] = tuple(ex["shutters"]) if ex.get("shutters") else None
                info["front_windows"] = ex.get("front_windows") is not False
                info["plaque"] = tuple(ex["plaque"]) if ex.get("plaque") else None
                info["window_h"] = float(ex.get("window_h") or 1.3)
                info["wrap_wall"] = None
                if info.get("wrap") and info["front"] is not None:          # the veranda turns the corner: pick the side
                    n = len(walls)                                            # wall that sees a street sooner, else the longer
                    nbrs = [(info["front"] - 1) % n, (info["front"] + 1) % n]
                    near = archetypes.front_wall([walls[k] for k in nbrs], self.world.on_road)
                    info["wrap_wall"] = nbrs[near] if near is not None else max(
                        nbrs, key=lambda k: math.hypot(walls[k][2] - walls[k][0], walls[k][3] - walls[k][1]))
            elif info is not None:
                info = None                                                 # apartments keep the ribbon windows
            self._houses[idx] = info
        return self._houses[idx]

    def _shop_walls(self, idx):
        """Walls of building idx that get a shop front: those right on a street (a road within 9 m), for downtown
        commercial blocks (zones D, U, N without a landmark) or buildings marked "shopfront". Empty set otherwise."""
        if idx not in self._shops:
            ex = self.extras.get(idx)
            walls = set()
            downtown = ex and ex.get("material") in ("sandstone", "brick") and (
                ex.get("zone") in SHOP_ZONES or ex.get("zone") is None)       # the converter's sandstone district has no zone
            if ex and (ex.get("shopfront") or (ex.get("shopfront") is None and downtown and not ex.get("landmark"))):
                for k, w in enumerate(self.buildings[idx][4]):
                    if math.hypot(w[2] - w[0], w[3] - w[1]) >= 3.0 and archetypes.front_wall([w], self.world.on_road, 9.0, 1.5) == 0:
                        walls.add(k)
            self._shops[idx] = walls
        return self._shops[idx]

    def _building_style(self, idx, b, dist):
        _cx, _cy, h, base, _walls, fp, _rad = b
        ex = self.extras.get(idx)
        landmark = ex["landmark"] if ex else None
        arched = landmark in ("courthouse", "civic", "church") and dist < 80.0
        house = self._house(idx) if dist < HOUSE_DETAIL and self.st.get("house") else None
        shops = self._shop_walls(idx) if dist < SHOP_DETAIL and ex and self.st.get("house") else ()
        return {
            "h": h, "base": base, "ex": ex, "landmark": landmark, "arched": arched, "house": house, "shops": shops,
            "win": self.st["windows"] if dist < 90.0 and h > 3.5 and not arched and not house else None,
            "cornice": self.st["cornice"] if ex and ex["material"] in ("sandstone", "brick") and dist < 120.0 else None,
            "tags": self.graffiti.get(idx) if dist < 80.0 else None,
        }

    def _draw_wall_piece(self, surf, item, dist):
        idx, wi, x0, y0, x1, y1, nx, ny, sh, tagged = item
        b = self.buildings[idx]
        st = self._building_style(idx, b, dist)
        h, base = st["h"], st["base"]
        fog = self.fog_band(dist)
        ink = self.ink(fog)
        if self.terrain is None:
            z0 = z1 = 0.0
        else:                                                   # the wall's foot follows the land (z is relative to the foundation)
            gf = self._building_ground(idx)[0]
            z0, z1 = self._g(x0, y0) - gf - 0.05, self._g(x1, y1) - gf - 0.05
        self._poly(surf, [(x0, y0, z0), (x1, y1, z1), (x1, y1, h), (x0, y0, h)], self.col(base, sh, fog), ink)
        ex = st["ex"]
        if ex and ex.get("plinth") and dist < SHOP_DETAIL:                # a stone or painted base course (or a
            ph = min(h, float(ex.get("plinth_h") or 1.6))                 # brick ground floor under siding: plinth_h)
            self._poly(surf, [(x0, y0, z0), (x1, y1, z1), (x1, y1, ph), (x0, y0, ph)], self.col(tuple(ex["plinth"]), sh, fog), ink)
        if st["house"]:
            self._draw_house_wall(surf, idx, st["house"], wi, x0, y0, x1, y1, nx, ny, h, z0, z1, sh, fog, ink)
        if wi in st["shops"]:
            self._draw_shop_front(surf, idx, st["ex"], x0, y0, x1, y1, h, sh, fog, ink)
        elif st["win"]:
            self._draw_windows(surf, x0, y0, x1, y1, h, self.col(st["win"], sh, fog))
        if st["arched"]:
            self._draw_arched_windows(surf, x0, y0, x1, y1, h, self.col(self.st["windows"] or (40, 60, 118), sh, fog), ink)
        if ex and ex.get("mural") and dist < MURAL_DIST:
            self._draw_mural(surf, idx, wi, x0, y0, x1, y1, nx, ny, h, sh, fog, ink)
        if st["cornice"]:
            self._wall_band(surf, x0, y0, x1, y1, h - 0.75, h - 0.25, self.col(st["cornice"], sh, fog), ink)
        if st["landmark"] == "armoury":
            self._draw_battlements(surf, x0, y0, x1, y1, h, self.col(base, sh, fog), ink)
        if tagged and st["tags"] and wi in st["tags"]:
            w = b[4][wi]
            self._draw_tag(surf, st["tags"][wi], w[0], w[1], w[2], w[3], nx, ny, sh, fog, ink)

    def _draw_house_wall(self, surf, idx, house, wi, x0, y0, x1, y1, nx, ny, h, z0, z1, sh, fog, ink):
        """Foundation, windows, door, garage door and veranda on one wall of a house (close range only)."""
        hs = self.st["house"]
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1.5:
            return
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        kind = house["kind"]
        fh = 0.35 if kind == "minihome" else 0.75                           # foundation / skirting height
        if min(z0, z1) < fh:
            self._poly(surf, [(x0, y0, z0), (x1, y1, z1), (x1, y1, fh), (x0, y0, fh)], self.col(hs["foundation"], sh, fog), ink)
        whole = self.buildings[idx][4][wi]
        front = house["front"] == wi
        # the door's position along this piece of the wall (walls longer than 15 m are drawn in pieces)
        door_u = None
        if front:
            wl = math.hypot(whole[2] - whole[0], whole[3] - whole[1])
            dm = house["door"] * wl
            n_pieces = math.ceil(wl / WALL_PIECE) if wl > WALL_PIECE * 1.25 else 1
            seam = round(dm * n_pieces / wl) * wl / n_pieces
            if 0.0 < seam < wl and abs(dm - seam) < 0.75:
                dm = seam + 0.75                                            # off the seam between two wall pieces
            du = dm - ((x0 - whole[0]) * ux + (y0 - whole[1]) * uy)
            if 0.6 < du < L - 0.6:
                door_u = du

        def rect(u0, u1, za, zb, rgb):
            self._poly(surf, [(x0 + ux * u0, y0 + uy * u0, za), (x0 + ux * u1, y0 + uy * u1, za),
                              (x0 + ux * u1, y0 + uy * u1, zb), (x0 + ux * u0, y0 + uy * u0, zb)], rgb)

        trim, glass = self.col(hs["trim"], sh, fog), self.col(hs["glass"], sh, fog)
        if kind == "garage":
            if front or L >= 5.0:
                w = min(2.6, L - 0.8)
                rect((L - w) / 2, (L + w) / 2, 0.05, 2.2, self.col(house.get("door_rgb") or hs["garage_door"], sh, fog))
            return
        side = 0.0
        dtop = min(fh + 2.1, h - 0.2)                                       # the door stays under the eaves
        if door_u is not None:
            door_rgb = house.get("door_rgb") or hs["doors"][idx % len(hs["doors"])]
            if house.get("sidelights"):                                       # narrow glass panes either side
                side = 0.42
                rect(door_u - 0.6 - side, door_u + 0.6 + side, fh, dtop + 0.15, trim)
                for s0 in (-1, 1):
                    a, b = door_u + s0 * 0.54, door_u + s0 * (0.54 + side - 0.08)
                    rect(min(a, b), max(a, b), fh + 0.35, dtop - 0.05, glass)
            else:
                rect(door_u - 0.6, door_u + 0.6, fh, dtop + 0.15, trim)
            rect(door_u - 0.48, door_u + 0.48, fh, dtop, self.col(door_rgb, sh, fog))
            if house.get("plaque") and dtop + 1.2 < h:                       # a dark name plaque over the door
                rect(door_u - 0.32, door_u + 0.32, dtop + 0.45, dtop + 1.1, self.col(house["plaque"], sh, fog))
        shutter = self.col(house["shutters"], sh, fog) if house.get("shutters") else None
        n = max(1, int((L - 0.8) / 2.7))
        ww = 1.2 if kind == "minihome" else 0.95
        sill = fh + (0.9 if kind == "minihome" else 0.85)
        for row in range(house["storeys"]):
            if front and not house.get("front_windows", True):
                break                                                       # e.g. a meeting house: door only
            z, wh = sill + row * 2.8, house.get("window_h", 1.3)
            if z + wh > h - 0.25:                                           # low walls: a shorter window, set lower
                if not front:
                    break                                                   # front only: bungalows are many (cost)
                z = max(fh + 0.3, min(z, h - 0.25 - 1.0))
                wh = min(1.3, h - 0.25 - z)
                if wh < 0.6:
                    break
            for k in range(n):
                uc = L * (k + 0.5) / n
                if door_u is not None and row == 0 and abs(uc - door_u) < 1.4 + side:
                    continue
                rect(uc - ww / 2 - 0.12, uc + ww / 2 + 0.12, z - 0.12, z + wh + 0.12, trim)
                rect(uc - ww / 2, uc + ww / 2, z, z + wh, glass)
                if shutter:                                                     # a shutter each side of the window
                    for s0 in (-1, 1):
                        a = uc + s0 * (ww / 2 + 0.16)
                        rect(min(a, a + s0 * 0.42), max(a, a + s0 * 0.42), z - 0.08, z + wh + 0.08, shutter)
        if house["porch"] and (front or wi == house.get("wrap_wall")):
            self._draw_porch(surf, x0, y0, ux, uy, nx, ny, L, fh, sh, fog, ink)

    def _draw_mural(self, surf, idx, wi, x0, y0, x1, y1, nx, ny, h, sh, fog, ink):
        """A mural (game/murals.py) on the wall of building idx that faces its "facing" bearing, centred on the wall.
        Drawn once, with the piece of the wall that holds the wall's middle (long walls are drawn in pieces)."""
        m = self.extras[idx]["mural"]
        key = ("mural", idx)
        if key not in self._houses:
            fb = math.radians(m.get("facing", 0.0))
            fx, fy = math.sin(fb), -math.cos(fb)
            walls = self.buildings[idx][4]
            self._houses[key] = max(range(len(walls)), key=lambda k: walls[k][4] * fx + walls[k][5] * fy)
        if wi != self._houses[key] or m.get("design") not in murals.DESIGNS:
            return
        whole = self.buildings[idx][4][wi]
        mx, my = (whole[0] + whole[2]) / 2, (whole[1] + whole[3]) / 2
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 0.1:
            return
        t = ((mx - x0) * (x1 - x0) + (my - y0) * (y1 - y0)) / (L * L)
        if not 0.0 <= t <= 1.0:
            return                                                          # another piece of this wall holds it
        WL = math.hypot(whole[2] - whole[0], whole[3] - whole[1])
        width = min(m.get("width", WL - 1.0), WL - 0.6)
        z0, z1 = m.get("bottom", 1.0), min(m.get("top", h - 0.6), h - 0.2)
        ux, uy = ny, -nx                                                    # left to right, seen from outside
        out = 0.04

        def P(u, v):
            return (mx + ux * (u - 0.5) * width + nx * out, my + uy * (u - 0.5) * width + ny * out, z0 + v * (z1 - z0))
        span = z1 - z0
        for shape in murals.DESIGNS[m["design"]]:
            kind = shape[0]
            if kind == "rect":
                _k, a0, b0, a1, b1, rgb = shape
                self._poly(surf, [P(a0, b0), P(a1, b0), P(a1, b1), P(a0, b1)], self.col(rgb, sh, fog),
                           ink if (a0, b0, a1, b1) == (0.0, 0.0, 1.0, 1.0) else None)
            elif kind == "poly":
                self._poly(surf, [P(a, b) for a, b in shape[1]], self.col(shape[2], sh, fog))
            elif kind == "disc":
                _k, cu, cv, r, rgb = shape
                ru = r * span / width                                       # keep it round on the wall
                self._poly(surf, [P(cu + ru * math.cos(k * math.pi / 5), cv + r * math.sin(k * math.pi / 5))
                                  for k in range(10)], self.col(rgb, sh, fog))
            elif kind == "letters":
                _k, a0, b0, a1, b1, rgb, n = shape
                step = (a1 - a0) / n
                for k in range(n):
                    top = b1 if k % 3 else b1 + (b1 - b0) * 0.3                # the odd capital stands taller
                    self._poly(surf, [P(a0 + k * step, b0), P(a0 + (k + 0.65) * step, b0),
                                      P(a0 + (k + 0.65) * step, top), P(a0 + k * step, top)], self.col(rgb, sh, fog))

    def _draw_shop_front(self, surf, idx, ex, x0, y0, x1, y1, h, sh, fog, ink):
        """Downtown shop front: display windows between stone piers, a door, a sign band, and rows of upper windows
        (one per storey: from "storeys" when set, else from the height)."""
        hs = self.st["house"]
        L = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / L, (y1 - y0) / L

        def rect(u0, u1, za, zb, rgb):
            self._poly(surf, [(x0 + ux * u0, y0 + uy * u0, za), (x0 + ux * u1, y0 + uy * u1, za),
                              (x0 + ux * u1, y0 + uy * u1, zb), (x0 + ux * u0, y0 + uy * u0, zb)], rgb)
        bays = max(1, int(L / 3.6))
        bw = L / bays
        glass, trim = self.col(hs["glass"], sh, fog), self.col(self.st["cornice"], sh, fog)
        door_bay = (idx * 7) % bays
        signs = hs.get("signs") or [(40, 70, 60)]
        if h >= 4.2:
            rect(0.15, L - 0.15, 3.0, 3.75, self.col(signs[idx % len(signs)], sh, fog))           # sign band
        for k in range(bays):
            a, b = k * bw + 0.35, (k + 1) * bw - 0.35
            if k == door_bay:
                m = (a + b) / 2
                rect(a, m - 0.55, 0.5, 2.7, glass)
                rect(m - 0.5, m + 0.5, 0.0, 2.6, self.col(hs["doors"][idx % len(hs["doors"])], sh, fog))
                rect(m + 0.55, b, 0.5, 2.7, glass)
            else:
                rect(a, b, 0.5, 2.8, glass)
        storeys = ex.get("storeys") or max(1, int((h + 0.6) / 3.8))
        z = 4.3
        n = max(1, int(L / 2.5))
        for _row in range(storeys - 1):
            if z + 1.7 > h - 0.4:
                break
            for k in range(n):
                uc = L * (k + 0.5) / n
                rect(uc - 0.6, uc + 0.6, z - 0.15, z + 1.85, trim)
                rect(uc - 0.45, uc + 0.45, z, z + 1.7, glass)
            z += 3.6

    def _draw_porch(self, surf, x0, y0, ux, uy, nx, ny, L, fh, sh, fog, ink):
        """A front veranda: a deck, three posts and a shed roof, 1.8 m deep along most of the front wall."""
        hs = self.st["house"]
        a, b, d = L * 0.1, L * 0.9, 1.8
        deck_z, roof_z = fh, 2.9

        def P(u, out, z):
            return (x0 + ux * u + nx * out, y0 + uy * u + ny * out, z)
        wood, roof = self.col(hs["porch"], sh, fog), self.col(hs["porch_roof"], sh, fog)
        self._poly(surf, [P(a, d, 0.0), P(b, d, 0.0), P(b, d, deck_z), P(a, d, deck_z)], wood, ink)      # deck front
        if self.cz > deck_z:
            self._poly(surf, [P(a, 0, deck_z), P(b, 0, deck_z), P(b, d, deck_z), P(a, d, deck_z)], self.col(hs["porch"], 3, fog), ink)
        for u in (a + 0.15, (a + b) / 2, b - 0.15):
            self._poly(surf, [P(u - 0.09, d - 0.15, deck_z), P(u + 0.09, d - 0.15, deck_z),
                              P(u + 0.09, d - 0.15, roof_z), P(u - 0.09, d - 0.15, roof_z)], self.col(hs["trim"], sh, fog), ink)
        self._poly(surf, [P(a - 0.2, d + 0.2, roof_z), P(b + 0.2, d + 0.2, roof_z),
                          P(b + 0.2, d + 0.2, roof_z + 0.25), P(a - 0.2, d + 0.2, roof_z + 0.25)], roof, ink)       # roof edge
        if self.cz > roof_z:
            self._poly(surf, [P(a - 0.2, 0, roof_z + 0.55), P(b + 0.2, 0, roof_z + 0.55),
                              P(b + 0.2, d + 0.2, roof_z + 0.25), P(a - 0.2, d + 0.2, roof_z + 0.25)],
                       self.col(hs["porch_roof"], 3, fog), ink)

    def _draw_building_top(self, surf, idx, dist):
        b = self.buildings[idx]
        st = self._building_style(idx, b, dist)
        h, base, ex, landmark = st["h"], st["base"], st["ex"], st["landmark"]
        fog = self.fog_band(dist)
        ink = self.ink(fog)
        roof = ex.get("roof") if ex else None
        if roof:
            house = st["house"]
            self._draw_roof(surf, roof, ex["roof_colour"], fog, ink, wall=base,
                            attic=house is not None and house["kind"] in ("cape", "two_storey"))
            if ex.get("dormers") and dist < HOUSE_DETAIL * 1.5:
                self._draw_dormers(surf, idx, b, ex, base, fog, ink)
            if ex.get("chimney"):
                self._draw_chimney(surf, ex["chimney"], fog, ink)
        elif self.cz > h:
            self._poly(surf, [(p[0], p[1], h) for p in b[5]], self.col(base, 3, fog), ink)
        if ex and ex["tower"]:                                     # a central clock tower (the old post office)
            self._draw_clock_tower(surf, b, ex["axis"], base, fog, ink)
        elif landmark == "church":
            steeple = ex.get("steeple", "spire")
            if steeple == "spire":
                self._draw_spire(surf, b, ex["axis"], base, fog, ink)
            elif steeple == "turret":
                self._draw_turret(surf, b, ex["axis"], base, fog, ink)
            elif steeple == "twin":
                self._draw_twin_towers(surf, b, ex["axis"], base, fog, ink)

    def _dormer_frame(self, idx, b, ex):
        """(centre x, y, along-ridge unit, across unit pointing to the street side, half length, half width) or None."""
        key = ("dormer", idx)
        if key not in self._houses:
            pts = b[5]
            frame = None
            if len(pts) == 4:
                cx, cy = b[0], b[1]
                e1 = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
                e2 = (pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
                l1, l2 = math.hypot(*e1), math.hypot(*e2)
                across = self.world.buildings[idx].get("ridge_across", False)
                e, hl, hw = (e1, l1 / 2, l2 / 2) if (l1 >= l2) != bool(across) else (e2, l2 / 2, l1 / 2)
                L = math.hypot(*e) or 1.0
                ux, uy = e[0] / L, e[1] / L
                vx, vy = -uy, ux
                side = 1.0
                if ex.get("front") is not None:                             # hand-set front: dormers on that slope
                    fb = math.radians(ex["front"])
                    side = 1.0 if vx * math.sin(fb) - vy * math.cos(fb) >= 0 else -1.0
                else:
                    for s in (1.0, -1.0):                                   # dormers go on the slope facing the street
                        wx, wy = cx + s * vx * hw, cy + s * vy * hw
                        if archetypes.front_wall([(wx - ux, wy - uy, wx + ux, wy + uy, s * vx, s * vy)], self.world.on_road, 40.0) == 0:
                            side = s
                            break
                frame = (cx, cy, ux, uy, vx * side, vy * side, hl, hw)
            self._houses[key] = frame
        return self._houses[key]

    def _draw_dormers(self, surf, idx, b, ex, base, fog, ink):
        """Dormers on the street-facing roof slope: a little upright front with a window and its own small gable."""
        fr = self._dormer_frame(idx, b, ex)
        if fr is None:
            return
        cx, cy, ux, uy, vx, vy, hl, hw = fr
        h = b[2]
        bld = self.world.buildings[idx]
        rh = float(bld.get("roof_height") or 0.0)
        kind = bld.get("roof")
        if rh < 1.6 or hw < 2.0 or kind not in ("gable", "hip", "mansard"):
            return
        if kind == "mansard":                                              # steep skirt: the dormer stands in it
            vf, z0, ztop = hw - 0.2, h + 0.2, h + min(rh - 0.2, 1.9)
            vb = hw - min(rh * 0.55, hw * 0.5, hl * 0.5) - 0.1
        else:
            vf = hw - 0.9
            z0 = h + rh * (1 - vf / hw)
            ztop = z0 + 1.55
            if ztop + 0.6 > h + rh:
                return                                                     # roof too shallow for a dormer
            vb = max(0.2, hw * (1 - (ztop + 0.4 - h) / rh))
        hs = self.st["house"]
        roof_col = tuple(ex.get("roof_colour") or self.st["slate"])
        n = ex["dormers"]
        w = 1.4

        def P(u, v, z):
            return (cx + ux * u + vx * v, cy + uy * u + vy * v, z)

        def roof_z(v):
            return ztop if kind == "mansard" else h + rh * (1 - v / hw)
        front_seen = (self.cx - (cx + vx * vf)) * vx + (self.cy - (cy + vy * vf)) * vy > 0
        for k in range(n):
            uc = -hl + 2 * hl * (k + 0.5) / n
            a, c = uc - w / 2, uc + w / 2
            for su in (-1, 1):                                             # the cheek (side) that faces the camera
                ue = uc + su * w / 2
                if (self.cx - (cx + ux * ue)) * ux * su + (self.cy - (cy + uy * ue)) * uy * su > 0:
                    self._poly(surf, [P(ue, vf, z0), P(ue, vf, ztop), P(ue, vb, ztop), P(ue, vb, roof_z(vb))],
                               self.col(base, 1, fog), ink)
            if front_seen:
                self._poly(surf, [P(a, vf, z0), P(c, vf, z0), P(c, vf, ztop), P(a, vf, ztop)], self.col(base, 3, fog), ink)
                self._poly(surf, [P(a, vf, ztop), P(c, vf, ztop), P(uc, vf, ztop + 0.6)], self.col(base, 3, fog), ink)
                self._poly(surf, [P(a + 0.2, vf + 0.02, z0 + 0.25), P(c - 0.2, vf + 0.02, z0 + 0.25),
                                  P(c - 0.2, vf + 0.02, ztop - 0.15), P(a + 0.2, vf + 0.02, ztop - 0.15)], self.col(hs["trim"], 3, fog))
                self._poly(surf, [P(a + 0.32, vf + 0.03, z0 + 0.37), P(c - 0.32, vf + 0.03, z0 + 0.37),
                                  P(c - 0.32, vf + 0.03, ztop - 0.27), P(a + 0.32, vf + 0.03, ztop - 0.27)], self.col(hs["glass"], 3, fog))
            for su in (-1, 1):                                             # the dormer's own little gable roof
                self._poly(surf, [P(uc + su * (w / 2 + 0.12), vf + 0.15, ztop - 0.05), P(uc + su * (w / 2 + 0.12), vb, ztop - 0.05),
                                  P(uc, vb, ztop + 0.6), P(uc, vf + 0.15, ztop + 0.6)], self.col(roof_col, 2 if su < 0 else 3, fog), ink)

    def _draw_chimney(self, surf, ch, fog, ink):
        """A brick chimney standing on the ridge: the sides that face the camera, then the cap."""
        corners, z0, z1 = ch
        brick = self.st["materials"]["brick"][0]
        cx, cy = self.cx, self.cy
        mx = sum(p[0] for p in corners) / 4.0
        my = sum(p[1] for p in corners) / 4.0
        for k in range(4):
            a, b = corners[k], corners[(k + 1) % 4]
            nx, ny = (a[0] + b[0]) / 2 - mx, (a[1] + b[1]) / 2 - my               # outward (the box is centred)
            if (cx - a[0]) * nx + (cy - a[1]) * ny <= 0:
                continue
            sh = shade_index(nx, ny, 0.0)
            self._poly(surf, [(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)],
                       self.col(brick, sh, fog), ink)
        if self.cz > z1:
            self._poly(surf, [(p[0], p[1], z1) for p in corners], self.col((70, 60, 58), 3, fog), ink)

    def _draw_roof(self, surf, faces, colour, fog, ink, wall=None, attic=False):
        """Gable / hip / mansard roof faces, far to near, skipping the ones that face away. Upright faces (the gable
        ends) are wall, so they take the wall colour when it is given, with a small attic window when `attic`."""
        cx, cy, cz = self.cx, self.cy, self.cz
        vis = []
        for face, (nx, ny, nz) in faces:
            p = face[0]
            if (cx - p[0]) * nx + (cy - p[1]) * ny + (cz - p[2]) * nz <= 0:
                continue
            mx = sum(q[0] for q in face) / len(face) - cx
            my = sum(q[1] for q in face) / len(face) - cy
            vis.append((mx * mx + my * my, face, shade_index(nx, ny, nz)))
        vis.sort(key=lambda v: -v[0])
        for _d, face, sh in vis:
            upright = wall is not None and len(face) == 3 and abs(face[0][2] - face[1][2]) < 1e-6 and face[2][2] > face[0][2] \
                and abs(face[2][0] - (face[0][0] + face[1][0]) / 2) < 1e-6 and abs(face[2][1] - (face[0][1] + face[1][1]) / 2) < 1e-6
            self._poly(surf, face, self.col(wall if upright else colour, sh, fog), ink)
            if upright and attic:
                self._attic_window(surf, face, sh, fog)

    def _attic_window(self, surf, face, sh, fog):
        """A small window in a gable end, a third of the way up the triangle."""
        hs = self.st["house"]
        (ax, ay, z0), (bx, by, _), (_tx, _ty, top) = face
        L = math.hypot(bx - ax, by - ay)
        rh = top - z0
        if L < 3.0 or rh < 1.6:
            return
        ux, uy = (bx - ax) / L, (by - ay) / L
        mx, my = (ax + bx) / 2, (ay + by) / 2
        zc = z0 + rh * 0.33
        for half_w, half_h, rgb in ((0.55, 0.7, hs["trim"]), (0.42, 0.57, hs["glass"])):
            self._poly(surf, [(mx - ux * half_w, my - uy * half_w, zc - half_h), (mx + ux * half_w, my + uy * half_w, zc - half_h),
                              (mx + ux * half_w, my + uy * half_w, zc + half_h), (mx - ux * half_w, my - uy * half_w, zc + half_h)],
                       self.col(rgb, sh, fog))

    def _wall_band(self, surf, x0, y0, x1, y1, z0, z1, rgb, ink=None):
        self._poly(surf, [(x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1)], rgb, ink)

    def _draw_arched_windows(self, surf, x0, y0, x1, y1, h, rgb, ink):
        """Tall round-topped windows, one row per 4 m storey (civic sandstone buildings)."""
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 3.0:
            return
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        n = max(1, int((L - 1.0) / 2.8))
        step = (L - 1.0) / n
        z = 1.2
        while z + 2.4 < h - 0.9:
            for k in range(n):
                uc = 0.5 + step * (k + 0.5)
                pts = [(uc - 0.55, z), (uc + 0.55, z), (uc + 0.55, z + 1.7)]
                pts += [(uc + 0.55 * math.cos(a), z + 1.7 + 0.55 * math.sin(a)) for a in (0.6, 1.2, 1.94, 2.54)]
                pts.append((uc - 0.55, z + 1.7))
                self._poly(surf, [(x0 + ux * u, y0 + uy * u, v) for u, v in pts], rgb, ink)
            z += 4.0

    def _draw_battlements(self, surf, x0, y0, x1, y1, h, rgb, ink):
        L = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        u = 0.3
        while u + 1.2 <= L:
            a, b = (x0 + ux * u, y0 + uy * u), (x0 + ux * (u + 1.2), y0 + uy * (u + 1.2))
            self._poly(surf, [(a[0], a[1], h), (b[0], b[1], h), (b[0], b[1], h + 1.0), (a[0], a[1], h + 1.0)], rgb, ink)
            u += 2.4

    def _draw_clock_tower(self, surf, b, axis, base, fog, ink):
        cx, cy, h = b[0], b[1], b[2]
        fr = _Frame(cx, cy, axis)
        half, top = 2.4, h + 8.5
        self._draw_box(surf, fr, -half, half, -half, half, h - 0.5, top, base, base, fog, ink)
        self._draw_box(surf, fr, -half - 0.2, half + 0.2, -half - 0.2, half + 0.2, top - 0.5, top,
                       self.st["cornice"], self.st["cornice"], fog, ink)
        self._draw_frustum(surf, fr, (-half - 0.2, half + 0.2, -half - 0.2, half + 0.2), (-0.1, 0.1, -0.1, 0.1),
                           top, top + 4.5, self.st["slate"], self.st["slate"], fog, ink)
        # clock faces: hands move one minute per real second, starting at nine o'clock
        minutes = self.time % 60.0
        hours = (9.0 + self.time / 60.0) % 12.0
        zc = top - 2.6
        for nx, ny in (fr.forward, fr.right, (-fr.forward[0], -fr.forward[1]), (-fr.right[0], -fr.right[1])):
            fx, fy = cx + nx * (half + 0.03), cy + ny * (half + 0.03)
            if (self.cx - fx) * nx + (self.cy - fy) * ny <= 0:
                continue
            ux, uy = ny, -nx                     # viewer's right on this face
            face = [(fx + ux * 1.4 * math.cos(a), fy + uy * 1.4 * math.cos(a), zc + 1.4 * math.sin(a))
                    for a in [k * math.pi / 5 for k in range(10)]]
            self._poly(surf, face, self.col(self.st["clock"], 3, fog), ink)
            c = self.project(fx, fy, zc)
            if c is None or ink is None:
                continue
            for frac, length in ((hours / 12.0, 0.75), (minutes / 60.0, 1.15)):
                a = frac * 2 * math.pi
                tip = self.project(fx + ux * math.sin(a) * length, fy + uy * math.sin(a) * length,
                                   zc + math.cos(a) * length)
                if tip:
                    pygame.draw.line(surf, ink, c[:2], tip[:2], 1)

    def _draw_spire(self, surf, b, axis, base, fog, ink):
        cx, cy, h = b[0], b[1], b[2]
        # put the steeple at one end of the long axis, like a church front
        ax, ay = math.cos(axis), math.sin(axis)
        far = max(((p[0] - cx) * ax + (p[1] - cy) * ay) for p in b[5])
        fr = _Frame(cx + ax * max(0.0, far - 3.0), cy + ay * max(0.0, far - 3.0), axis)
        self._draw_box(surf, fr, -1.8, 1.8, -1.8, 1.8, h - 0.5, h + 4.0, base, base, fog, ink)
        self._draw_frustum(surf, fr, (-1.9, 1.9, -1.9, 1.9), (-0.05, 0.05, -0.05, 0.05), h + 4.0, h + 15.0,
                           self.st["slate"], self.st["slate"], fog, ink)

    def _end_frame(self, b, axis, inset):
        """A frame at the far end of a building's long axis (where a church's tower stands)."""
        cx, cy = b[0], b[1]
        ax, ay = math.cos(axis), math.sin(axis)
        far = max(((p[0] - cx) * ax + (p[1] - cy) * ay) for p in b[5])
        return _Frame(cx + ax * max(0.0, far - inset), cy + ay * max(0.0, far - inset), axis), far

    def _draw_turret(self, surf, b, axis, base, fog, ink):
        """A square castellated bell tower at one corner of the church front (Trinity-St. Stephen's)."""
        h, pts = b[2], b[5]
        area = abs(sum(pts[k][0] * pts[k - 1][1] - pts[k - 1][0] * pts[k][1] for k in range(len(pts)))) / 2
        s = max(2.3, min(4.2, math.sqrt(area) / 11.0))                  # half width: grows with the church
        fr, _far = self._end_frame(b, axis, s + 0.2)
        fr = _Frame(fr.x + fr.right[0] * s * 1.3, fr.y + fr.right[1] * s * 1.3, axis)
        top = h + 2.6 * s
        self._draw_box(surf, fr, -s, s, -s, s, h - 0.5, top, base, base, fog, ink)
        m, q = s * 0.42, s * 0.2                                         # merlon size and gap
        for a0, a1, b0, b1 in ((-s, -s + m, -s, -s + m), (s - m, s, -s, -s + m), (-s, -s + m, s - m, s), (s - m, s, s - m, s),
                               (-q, q, -s, -s + m), (-q, q, s - m, s), (-s, -s + m, -q, q), (s - m, s, -q, q)):
            self._draw_box(surf, fr, a0, a1, b0, b1, top, top + 0.5 * s, base, base, fog, ink)      # merlons

    def _draw_twin_towers(self, surf, b, axis, base, fog, ink):
        """Two tall towers with pointed caps either side of the church front (First Baptist)."""
        h = b[2]
        fr, _far = self._end_frame(b, axis, 1.8)
        for side in (-1.0, 1.0):
            off = side * 4.2
            t = _Frame(fr.x + fr.right[0] * off, fr.y + fr.right[1] * off, axis)
            top = h + (7.0 if side > 0 else 5.0)                                           # one taller, as most have
            self._draw_box(surf, t, -1.6, 1.6, -1.6, 1.6, h - 0.5, top, base, base, fog, ink)
            self._draw_frustum(surf, t, (-1.8, 1.8, -1.8, 1.8), (-0.05, 0.05, -0.05, 0.05), top, top + 5.5,
                               self.st["slate"], self.st["slate"], fog, ink)

    def _draw_tag(self, surf, shapes, x0, y0, x1, y1, nx, ny, sh, fog, ink):
        L = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        ox, oy = x0 + nx * 0.05, y0 + ny * 0.05
        for colour, pts in shapes:
            world = [(ox + ux * u, oy + uy * u, max(0.05, v)) for u, v in pts]
            self._poly(surf, world, self.col(colour, sh, fog), ink)

    # ---------------------------------------------------------------- props
    def _billboard(self, x, y, z0, z1, half):
        """Screen-space quad for a vertical pole that always faces the camera."""
        a, b = self.project(x, y, z0), self.project(x, y, z1)
        if a is None or b is None:
            return None
        wa, wb = max(0.6, self.focal * half / a[2]), max(0.6, self.focal * half / b[2])
        return [(a[0] - wa, a[1]), (a[0] + wa, a[1]), (b[0] + wb, b[1]), (b[0] - wb, b[1])]

    def _draw_prop(self, surf, p, dist):
        st = self.st
        fog = self.fog_band(dist)
        ink = self.ink(fog)
        x, y, h = p["x"], p["y"], p["h"]
        if p["kind"] == "tree":
            trunk = self._billboard(x, y, 0.0, h * 0.62, 0.2)
            if trunk:
                self._emit(surf, trunk, self.col(st["trunk"], 3, fog), ink)
            c = self.project(x, y, h - p["r"] * 0.8)
            if c is None:
                return
            R = self.focal * p["r"] / c[2]
            if R < 0.8:
                return
            if p.get("leaf"):                                   # a hand-set leaf colour (a purple-leaf plum...)
                lit = tuple(p["leaf"])
                shade = tuple(int(v * 0.72) for v in lit)
            else:
                lit, shade = st["tree_cols"][p["c"] % len(st["tree_cols"])]
            outer = [(c[0] + R * k * math.cos(a), c[1] + R * 0.9 * k * math.sin(a)) for a, k in BLOB12]
            self._emit(surf, outer, self.col(shade, 3, fog), ink)
            s, ox, oy = 0.78, -R * 0.14, -R * 0.16      # lit blob offset up-left leaves a shadow crescent
            inner = [(c[0] + ox + R * s * k * math.cos(a), c[1] + oy + R * 0.9 * s * k * math.sin(a))
                     for a, k in BLOB12]
            self._emit(surf, inner, self.col(lit, 3, fog))
        elif p["kind"] == "cenotaph":
            fr = _Frame(x, y, 0.0)
            g, br = st["granite"], st["bronze"]
            self._draw_box(surf, fr, -1.4, 1.4, -1.4, 1.4, 0.0, 0.8, g, g, fog, ink)
            self._draw_frustum(surf, fr, (-0.8, 0.8, -0.8, 0.8), (-0.55, 0.55, -0.55, 0.55), 0.8, 4.4, g, g, fog, ink)
            self._draw_frustum(surf, fr, (-0.35, 0.35, -0.35, 0.35), (-0.2, 0.2, -0.2, 0.2), 4.4, 6.0, br, br, fog, ink)
        elif p["kind"] == "lighthouse":
            self._draw_lighthouse(surf, p, fog, ink)
        elif p["kind"] == "horse":
            self._draw_horse(surf, p, fog, ink)
        elif p["kind"] == "gravestone":                       # one flat slab face, the side toward the camera
            hd = p.get("heading", 0.0)
            fx, fy = math.cos(hd), math.sin(hd)
            w = p.get("w", 0.7) / 2
            t = 0.08 if (self.cx - x) * fx + (self.cy - y) * fy > 0 else -0.08
            bx, by = x + fx * t, y + fy * t
            self._poly(surf, [(bx + fy * w, by - fx * w, 0.0), (bx - fy * w, by + fx * w, 0.0),
                              (bx - fy * w, by + fx * w, h), (bx + fy * w, by - fx * w, h)],
                       self.col(tuple(p.get("colour") or (120, 122, 128)), 2, fog), ink)
        elif p["kind"] == "fence":
            self._draw_fence(surf, p, fog, ink)
        elif p["kind"] == "dam":
            self._draw_dam(surf, p, fog, ink)
        elif p["kind"] in DETAIL_KINDS:
            self._draw_furniture(surf, p, fog, ink, dist)
        else:
            pole = self._billboard(x, y, 0.0, h, 0.08)
            if pole:
                self._emit(surf, pole, self.col(st["lamp"], 3, fog), ink)
            hx, hy = x + p.get("dx", 0.0) * 0.9, y + p.get("dy", 0.0) * 0.9
            head = self._billboard(hx, hy, h - 0.15, h + 0.12, 0.35)
            if head:
                self._emit(surf, head, self.col(st["lamp_head"], 3, fog), ink)

    def _disc(self, surf, x, y, z, radius_m, rgb, ink=None, sides=8, outline=None):
        """A small camera-facing round or octagonal plate (signs, signal lamps)."""
        c = self.project(x, y, z)
        if c is None:
            return
        R = self.focal * radius_m / c[2]
        if R < 0.7:
            return
        k = [(c[0] + R * math.cos(a + math.pi / sides), c[1] + R * math.sin(a + math.pi / sides))
             for a in [i * 2 * math.pi / sides for i in range(sides)]]
        self._emit(surf, k, rgb, ink)
        if outline is not None and R > 2.5:
            pygame.draw.polygon(surf, outline, [(c[0] + (px - c[0]) * 0.72, c[1] + (py - c[1]) * 0.72) for px, py in k], 1)

    def _oct(self, surf, x, y, z0, z1, r0, r1, rgb, fog, ink, cap=False, shade=None):
        """An eight-sided tapered tower section: only the sides facing the camera, and its top when seen from above."""
        ang = [math.pi / 8 + k * math.pi / 4 for k in range(8)]
        for k in range(8):
            a0, a1 = ang[k], ang[(k + 1) % 8]
            am = (a0 + a1) / 2 if k < 7 else a0 + math.pi / 8
            nx, ny = math.cos(am), math.sin(am)
            if (self.cx - (x + nx * r0)) * nx + (self.cy - (y + ny * r0)) * ny <= 0:
                continue
            sh = shade if shade is not None else shade_index(nx, ny, 0.0)
            self._poly(surf, [(x + r0 * math.cos(a0), y + r0 * math.sin(a0), z0), (x + r0 * math.cos(a1), y + r0 * math.sin(a1), z0),
                              (x + r1 * math.cos(a1), y + r1 * math.sin(a1), z1), (x + r1 * math.cos(a0), y + r1 * math.sin(a0), z1)],
                       self.col(rgb, sh, fog), ink)
        if cap and self.cz > z1:
            self._poly(surf, [(x + r1 * math.cos(a), y + r1 * math.sin(a), z1) for a in ang], self.col(rgb, 0, fog), ink)

    def _draw_lighthouse(self, surf, p, fog, ink):
        """A white octagonal lighthouse with a red gallery, glowing lantern and red cap; at the border welcome site
        ("site": "border") also a porch, a granite planter, the welcome sign and two flagpoles.
        Local frame for the extras: a = towards the road the site faces, b = to its right."""
        x, y = p["x"], p["y"]
        white, red, granite = (246, 246, 242), (196, 44, 44), (146, 148, 150)
        glass = (252, 232, 136)
        border = p.get("site") == "border"
        hd = p.get("heading", 0.0)
        fr = _Frame(x, y, hd)
        fx, fy = fr.forward
        tower_first = border and (self.cx - x) * fx + (self.cy - y) * fy > 0    # camera on the sign side

        def site():
            mulch = (96, 68, 46)
            self._draw_box(surf, fr, -3.2, 3.2, -3.6, 3.6, 0.0, 0.35, granite, mulch, fog, ink)       # planter
            self._draw_box(surf, fr, 1.35, 2.35, -0.65, 0.65, 0.35, 2.95, white, white, fog, ink)    # porch
            self._draw_box(surf, fr, 2.35, 2.4, -0.38, 0.38, 0.35, 2.55, red, red, fog, ink)          # its door
            self._draw_box(surf, fr, 1.3, 2.45, -0.75, 0.75, 2.95, 3.2, red, red, fog, ink)           # its roof
            blue, gold, plate, post = (26, 78, 142), (224, 184, 62), (242, 244, 246), (124, 84, 48)
            sa, sb = 6.5, 4.2                                                                       # the sign
            for b in (sb - 1.85, sb + 1.85):
                self._draw_box(surf, fr, sa - 0.14, sa + 0.14, b - 0.12, b + 0.12, 0.0, 3.15, post, post, fog, ink)
            self._draw_box(surf, fr, sa - 0.09, sa + 0.09, sb - 1.75, sb + 1.75, 1.15, 2.85, blue, blue, fog, ink)
            self._draw_box(surf, fr, sa - 0.12, sa + 0.12, sb - 1.78, sb + 1.78, 2.85, 3.05, gold, gold, fog, ink)
            for side in (1, -1):                                                                    # white text panel
                a = sa + side * 0.1
                if (self.cx - (x + fx * a)) * fx * side + (self.cy - (y + fy * a)) * fy * side > 0:
                    self._draw_box(surf, fr, a - 0.01, a + 0.01, sb - 1.35, sb + 1.35, 1.55, 2.45, plate, plate, fog)
            for fa, fb, flag in ((-2.6, -5.4, (206, 36, 44)), (-2.8, 1.2, (32, 92, 168))):           # flagpoles
                pole = self._billboard(x + fx * fa - fy * fb, y + fy * fa + fx * fb, 0.0, 8.2, 0.06)
                if pole:
                    self._emit(surf, pole, self.col(white, 3, fog), ink)
                self._draw_box(surf, fr, fa - 0.02, fa + 0.02, fb + 0.06, fb + 1.55, 7.05, 8.0, flag, flag, fog, ink)

        def tower():
            self._oct(surf, x, y, 0.35, 1.15, 2.15, 2.05, granite, fog, ink, cap=True)
            self._oct(surf, x, y, 1.15, 6.6, 1.9, 1.25, white, fog, ink)
            self._oct(surf, x, y, 6.6, 6.82, 1.55, 1.55, red, fog, ink, cap=True)
            self._oct(surf, x, y, 6.82, 8.05, 0.92, 0.92, glass, fog, ink, shade=0)                  # lit: no shading
            self._oct(surf, x, y, 6.82, 7.35, 1.48, 1.48, red, fog, ink)                            # gallery rail
            self._oct(surf, x, y, 8.05, 8.95, 1.08, 0.08, red, fog, ink)
            spire = self._billboard(x, y, 8.95, 9.45, 0.08)
            if spire:
                self._emit(surf, spire, self.col(red, 3, fog), ink)

        if not border:
            tower()
        elif tower_first:
            tower()
            site()
        else:
            site()
            tower()

    def _draw_dam(self, surf, p, fog, ink):
        """A concrete overflow dam: spillway with a falling water curtain and white water at its foot, a sluice, gate
        piers with a catwalk and red handwheels, and a timber-baffled fish ladder down the end bank. The map's own
        river water lies around it; the dam adds its plunge pool and the sheet of water on the crest.
        Local frame: a = downstream, b = along the crest (+b = the fish-ladder end), z = up from the river."""
        hd = p.get("heading", 0.0)
        fx, fy = math.cos(hd), math.sin(hd)
        rx, ry = -fy, fx
        x, y, H, L = p["x"], p["y"], p["h"], p.get("length", 50.0)
        hb = L / 2.0
        col = lambda rgb, sh=2: self.col(rgb, sh, fog)                       # noqa: E731
        concrete, dark, moss = (176, 174, 166), (132, 130, 122), (114, 126, 102)
        deep, fall, foam = (36, 78, 108), (145, 202, 228), (232, 244, 248)
        timber, steel, red, grass = (134, 92, 56), (64, 72, 78), (184, 62, 54), (88, 128, 66)
        pulse = int(10 * math.sin(self.time * 6.0))
        fall = tuple(max(0, min(255, v + pulse)) for v in fall)
        fr = _Frame(x, y, hd)

        def P(a, b, z):
            return (x + fx * a + rx * b, y + fy * a + ry * b, z)

        def quad(pts, rgb, sh=2, outline=True):
            self._poly(surf, [P(*q) for q in pts], col(rgb, sh), ink if outline else None)

        def box(a0, a1, b0, b1, z0, z1, rgb):
            self._draw_box(surf, fr, a0, a1, b0, b1, z0, z1, rgb, rgb, fog, ink)

        s0, s1 = -hb, hb - 8.0                                                # spillway span; the north 8 m: works
        downstream = (self.cx - x) * fx + (self.cy - y) * fy > 0

        def water_below():
            quad([(0.6, s0 - 2, 0.04), (14.0, s0 - 2, 0.04), (14.0, s1 + 2, 0.04), (0.6, s1 + 2, 0.04)], deep, 3, False)
            quad([(2.1, s0, 0.08), (4.8, s0, 0.08), (4.8, s1, 0.08), (2.1, s1, 0.08)], foam, 3, False)

        def reservoir():                                                      # the water about to spill over
            quad([(-2.2, s0, H + 0.02), (-6.0, s0, H + 0.02), (-6.0, s1, H + 0.02), (-2.2, s1, H + 0.02)], deep, 3, False)

        def works():                                                          # sluice, gate piers, catwalk, wheels
            box(-2.5, 0.5, s1, s1 + 2.3, 0.0, H + 0.4, dark)
            quad([(0.55, s1 + 0.3, H - 0.1), (0.55, s1 + 2.0, H - 0.1), (3.6, s1 + 2.0, 0.2), (3.6, s1 + 0.3, 0.2)], foam, 3, False)
            for b0 in (s1 + 2.3, s1 + 3.8, s1 + 5.3):
                box(-2.8, 1.0, b0, b0 + 0.9, 0.0, H + 1.6, concrete)
            box(-3.0, 1.2, s1 + 2.1, s1 + 6.4, H + 1.4, H + 1.75, steel)
            for b in (s1 + 3.35, s1 + 4.85):
                box(-1.1, -0.8, b - 0.15, b + 0.15, H + 1.75, H + 2.75, steel)
                box(-1.3, -0.6, b - 0.35, b + 0.35, H + 2.65, H + 2.8, red)

        def ladder():                                                         # flume down the bank, with baffles
            b0, b1 = s1 + 6.2, s1 + 8.0
            for b in (b0, b1):
                quad([(-2.0, b, 0.0), (16.0, b, 0.0), (16.0, b, 1.4), (-2.0, b, H + 0.6)], moss, 2)
            quad([(-2.0, b0, H - 0.2), (16.0, b0, 0.7), (16.0, b1, 0.7), (-2.0, b1, H - 0.2)], fall, 3, False)
            for k in range(9):
                t = (k + 0.5) / 9
                a, z = -1.2 + t * 16.4, H - 0.1 - t * (H - 1.0)
                quad([(a + 0.35, b0, z - 0.15), (a + 0.35, b1, z - 0.15), (a - 0.15, b1, z + 0.45), (a - 0.15, b0, z + 0.45)], timber, 2)

        def spillway():
            box(-2.2, 0.6, s0, s1, 0.0, H, concrete)

        def curtain():
            quad([(0.65, s0 + 0.3, H + 0.05), (0.65, s1 - 0.3, H + 0.05), (2.2, s1 - 0.3, 0.15), (2.2, s0 + 0.3, 0.15)], fall, 3, False)

        water_below()
        if downstream:
            for draw in (reservoir, spillway, curtain, works, ladder):
                draw()
        else:
            for draw in (ladder, curtain, spillway, works, reservoir):
                draw()

    def _draw_fence(self, surf, p, fog, ink):
        """One piece of a white rail fence: a post at its start (and end, for the last piece) and two rails."""
        (ax, ay), (bx, by) = p["a"], p["b"]
        L = math.hypot(bx - ax, by - ay)
        if L < 0.1:
            return
        c = self.col(tuple(p.get("colour") or (244, 244, 238)), 2, fog)
        h = p["h"]
        for z in (h * 0.45, h * 0.85):                     # rails: one flat face each
            self._poly(surf, [(ax, ay, z - 0.07), (bx, by, z - 0.07), (bx, by, z + 0.07), (ax, ay, z + 0.07)], c, ink)
        for px, py in (((ax, ay), (bx, by)) if p.get("last") else ((ax, ay),)):
            post = self._billboard(px, py, 0.0, h + 0.1, 0.07)
            if post:
                self._emit(surf, post, c, ink)

    def _draw_horse(self, surf, p, fog, ink):
        """A black horse at full gallop with all four hooves off the ground: a frozen moment (p["lift"] metres up).
        Each part is a side profile (a = forward, z = up) pushed out sideways (b = to the horse's right)."""
        fx, fy = math.cos(p.get("heading", 0.0)), math.sin(p.get("heading", 0.0))
        rx, ry = -fy, fx
        x, y, lift = p["x"], p["y"], p.get("lift", 0.3)
        coat = tuple(p.get("colour") or (30, 28, 34))
        leg = tuple(max(0, v - 12) for v in coat)
        right_seen = (self.cx - x) * rx + (self.cy - y) * ry > 0
        front_seen = (self.cx - x) * fx + (self.cy - y) * fy > 0

        def P(a, b, z):
            return (x + fx * a + rx * b, y + fy * a + ry * b, z + lift)

        def slab(profile, b0, b1, rgb):
            near, far = (b1, b0) if right_seen else (b0, b1)
            self._poly(surf, [P(a, far, z) for a, z in profile], self.col(rgb, 1, fog), ink)
            for (a0, z0), (a1, z1) in zip(profile, profile[1:] + profile[:1]):
                self._poly(surf, [P(a0, b0, z0), P(a1, b0, z1), P(a1, b1, z1), P(a0, b1, z0)], self.col(rgb, 3, fog), ink)
            self._poly(surf, [P(a, near, z) for a, z in profile], self.col(rgb, 2, fog), ink)

        legs = {   # side -> (front leg, hind leg) profiles
            1: ([(0.75, 1.2), (0.92, 1.15), (1.58, 0.45), (1.46, 0.36)],                          # front: reaching
                [(-0.78, 1.2), (-0.56, 1.2), (-1.42, 0.46), (-1.58, 0.52)]),                       # hind: stretched
            -1: ([(0.52, 1.2), (0.72, 1.15), (0.98, 0.76), (0.74, 0.52), (0.64, 0.6), (0.8, 0.8)],  # front: folded
                 [(-0.62, 1.2), (-0.44, 1.15), (-0.04, 0.62), (-0.16, 0.52)]),                     # hind: gathering
        }
        body = [(-0.95, 1.1), (0.85, 1.05), (1.0, 1.45), (0.75, 1.7), (-0.85, 1.66), (-1.06, 1.42)]
        neck = [(0.58, 1.42), (0.96, 1.36), (1.36, 1.96), (1.1, 2.22)]
        head = [(1.05, 2.02), (1.32, 2.28), (1.82, 1.86), (1.74, 1.68)]
        tail = [(-0.94, 1.56), (-1.06, 1.64), (-1.62, 1.26), (-1.56, 1.14)]
        far_side = -1 if right_seen else 1
        for prof in legs[far_side]:                                       # far legs, behind the body
            slab(prof, far_side * 0.2 - 0.06, far_side * 0.2 + 0.06, leg)
        parts = [(tail, -0.05, 0.05), (body, -0.27, 0.27), (neck, -0.15, 0.15), (head, -0.12, 0.12)]
        for prof, b0, b1 in (parts if front_seen else parts[::-1]):
            slab(prof, b0, b1, coat)
        for prof in legs[-far_side]:                                      # near legs, in front of the body
            slab(prof, -far_side * 0.2 - 0.06, -far_side * 0.2 + 0.06, leg)

    def _draw_furniture(self, surf, p, fog, ink, dist):
        """Stop signs, signals, rail crossing signs, hydrants, benches and bins: small chunky shapes."""
        st = self.st
        x, y, h, kind = p["x"], p["y"], p["h"], p["kind"]
        pole_col = self.col(st["lamp"], 3, fog)
        if kind == "stopsign":
            pole = self._billboard(x, y, 0.0, h - 0.3, 0.05)
            if pole:
                self._emit(surf, pole, pole_col, ink)
            self._disc(surf, x, y, h - 0.35, 0.42, self.col((212, 38, 44), 3, fog), ink, 8, self.col((250, 250, 250), 3, fog))
        elif kind == "signal":
            pole = self._billboard(x, y, 0.0, h, 0.08)
            if pole:
                self._emit(surf, pole, pole_col, ink)
            head = self._billboard(x, y, h - 1.5, h + 0.1, 0.26)
            if head:
                self._emit(surf, head, self.col((38, 38, 48), 3, fog), ink)
            lit = SD.signal_light(self.time, p.get("ph", 0))     # 0 red, 1 yellow, 2 green (traffic obeys the same)
            for i, (z, on, off) in enumerate(((h - 0.15, (255, 60, 50), (96, 30, 30)),
                                              (h - 0.7, (255, 214, 60), (96, 84, 30)),
                                              (h - 1.25, (80, 240, 120), (30, 90, 46)))):
                self._disc(surf, x, y, z, 0.17, on if i == lit else off, None, 6)
        elif kind == "crossbuck":
            pole = self._billboard(x, y, 0.0, h - 0.4, 0.05)
            if pole:
                self._emit(surf, pole, pole_col, ink)
            c = self.project(x, y, h - 0.1)
            if c is not None:
                R = self.focal * 0.75 / c[2]
                if R > 1.0:
                    w = self.col((250, 250, 250), 3, fog)
                    wide, thin = max(2, int(R * 0.3)), max(1, int(R * 0.14))
                    for sgn in (1.0, -1.0):
                        a = (c[0] - R, c[1] - sgn * R * 0.55)
                        b = (c[0] + R, c[1] + sgn * R * 0.55)
                        pygame.draw.line(surf, ink or w, a, b, wide)
                        pygame.draw.line(surf, w, a, b, thin)
            self.polys += 2
        elif kind == "hydrant":
            body = self._billboard(x, y, 0.0, 0.7, 0.15)
            if body:
                self._emit(surf, body, self.col((206, 44, 44), 3, fog), ink)
            cap = self._billboard(x, y, 0.7, 0.92, 0.19)
            if cap:
                self._emit(surf, cap, self.col((250, 214, 70), 3, fog), ink)
        elif kind == "bin":
            body = self._billboard(x, y, 0.0, 0.95, 0.22)
            if body:
                self._emit(surf, body, self.col((58, 110, 86), 3, fog), ink)
        elif kind == "bench":
            fr = _Frame(x, y, math.atan2(p.get("dy", 0.0) or 0.0, p.get("dx", 1.0) or 1.0))
            wood, dark = self.col((176, 110, 60), 3, fog), self.col((92, 70, 52), 3, fog)
            if dist > 45.0:
                self._draw_box(surf, fr, -0.3, 0.3, -0.85, 0.85, 0.0, 0.7, wood, wood, fog, ink)
            else:
                self._draw_box(surf, fr, -0.25, 0.25, -0.8, 0.8, 0.0, 0.45, dark, wood, fog, ink)          # seat
                self._draw_box(surf, fr, -0.3, -0.22, -0.8, 0.8, 0.45, 0.95, wood, wood, fog, ink)         # back

    def _draw_battle_thing(self, surf, e, dist):
        """Balloons, item boxes, pucks, seekers and oil slicks (game/battle.py)."""
        fog = min(self.fog_band(dist), 3)
        ink = self.ink(fog)
        x, y, kind = e["x"], e["y"], e["kind"]
        if kind == "balloon":
            string = self.project_poly([(e["ax"], e["ay"], 1.6), (x, y, e["z"] - 0.35), (x, y, e["z"] - 0.36)])
            if string:
                pygame.draw.line(surf, ink or (20, 20, 30), string[0][0], string[0][1])
            self._disc(surf, x, y, e["z"], 0.38, self.col(e["colour"], 3, fog), ink, 10)
        elif kind == "box":
            fr = _Frame(x, y, e["spin"])
            z0 = 0.9 + 0.2 * math.sin(e["spin"] * 2.0)
            gold, white = (255, 206, 60), (250, 250, 250)
            self._draw_box(surf, fr, -0.65, 0.65, -0.65, 0.65, z0, z0 + 1.3, gold, white, fog, ink)
            self._draw_box(surf, fr, -0.2, 0.2, -0.68, 0.68, z0 + 0.45, z0 + 0.85, (210, 60, 200), (210, 60, 200), fog)
        elif kind in ("puck", "seeker"):
            fr = _Frame(x, y, e.get("spin", 0.0))
            c = e["colour"]
            r = 0.45 if kind == "puck" else 0.4
            self._draw_box(surf, fr, -r, r, -r, r, 0.15, 0.5 if kind == "puck" else 0.75, c, c, fog, ink)
            if kind == "seeker":
                self._draw_box(surf, fr, -0.1, 0.1, -0.5, 0.5, 0.75, 0.95, (250, 250, 250), (250, 250, 250), fog, ink)
        elif kind == "slick":
            r = e["r"]
            pts = [(x + r * (1.0 + 0.18 * math.sin(k * 2.7)) * math.cos(k * math.pi / 6),
                    y + r * (0.85 + 0.15 * math.cos(k * 1.9)) * math.sin(k * math.pi / 6), 0.06) for k in range(12)]
            pr = self.project_poly(pts)
            if pr:
                pygame.draw.polygon(surf, self.col((34, 30, 40), 3, fog), pr[0])
                hl = self.project_poly([(x - 0.3, y - 0.2, 0.07), (x + 0.2, y - 0.35, 0.07), (x + 0.1, y - 0.1, 0.07)])
                if hl:
                    pygame.draw.polygon(surf, self.col((120, 110, 160), 3, fog), hl[0])

    def _draw_marker(self, surf, m, dist):
        """Mission beacon: a ring on the road, a tall light column and a bobbing diamond."""
        fog = min(self.fog_band(dist), 3)
        ink = self.ink(fog)
        x, y, r, col = m["x"], m["y"], m["radius"], self.col(m["colour"], 3, fog)
        ring = self.project_poly([(x + r * math.cos(a), y + r * math.sin(a), 0.07)
                                  for a in [k * math.pi / 8 for k in range(16)]])
        if ring:
            pygame.draw.polygon(surf, col, ring[0], 2)
        pole = self._billboard(x, y, 0.0, 22.0, 0.5)
        if pole:
            self._emit(surf, pole, col, ink)
        c = self.project(x, y, 4.0 + 0.6 * math.sin(self.time * 3.0))
        if c:
            R = max(2.0, self.focal * 0.9 / c[2])
            diamond = [(c[0], c[1] - R * 1.4), (c[0] + R, c[1]), (c[0], c[1] + R * 1.4), (c[0] - R, c[1])]
            self._emit(surf, diamond, _lerp_rgb(col, (255, 255, 255), 0.45), ink)

    def _draw_windows(self, surf, x0, y0, x1, y1, h, rgb):
        """One ribbon of windows per 3.2 m storey, inset from the wall ends."""
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 2.6:
            return
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        inset = min(0.9, L * 0.15)
        ax, ay = x0 + ux * inset, y0 + uy * inset
        bx, by = x1 - ux * inset, y1 - uy * inset
        z = 1.1
        while z + 1.3 < h - 0.4:
            self._poly(surf, [(ax, ay, z), (bx, by, z), (bx, by, z + 1.3), (ax, ay, z + 1.3)], rgb)
            z += 3.2

    def _draw_box(self, surf, car, a0, a1, b0, b1, z0, z1, side_base, top_base, fog=0, ink=None):
        fx, fy = car.forward
        rx, ry = car.right
        x, y = car.x, car.y

        def P(a, b, z):
            return (x + fx * a + rx * b, y + fy * a + ry * b, z)

        faces = (
            ([P(a1, b0, z0), P(a1, b1, z0), P(a1, b1, z1), P(a1, b0, z1)], (fx, fy)),      # front
            ([P(a0, b1, z0), P(a0, b0, z0), P(a0, b0, z1), P(a0, b1, z1)], (-fx, -fy)),    # back
            ([P(a0, b0, z0), P(a1, b0, z0), P(a1, b0, z1), P(a0, b0, z1)], (-rx, -ry)),    # left
            ([P(a1, b1, z0), P(a0, b1, z0), P(a0, b1, z1), P(a1, b1, z1)], (rx, ry)),      # right
        )
        for pts, (nx, ny) in faces:
            p0 = pts[0]
            if (self.cx - p0[0]) * nx + (self.cy - p0[1]) * ny <= 0:
                continue
            self._poly(surf, pts, self.col(side_base, shade_index(nx, ny, 0.0), fog), ink)
        if self.cz > z1:
            self._poly(surf, [P(a0, b0, z1), P(a1, b0, z1), P(a1, b1, z1), P(a0, b1, z1)],
                       self.col(top_base, 3, fog), ink)

    def _draw_frustum(self, surf, car, bot, top, z0, z1, side_base, top_base, fog=0, ink=None):
        """A box whose top is smaller than its bottom (a tapered car cabin)."""
        ba0, ba1, bb0, bb1 = bot
        ta0, ta1, tb0, tb1 = top
        fx, fy = car.forward
        rx, ry = car.right
        x, y = car.x, car.y

        def P(a, b, z):
            return (x + fx * a + rx * b, y + fy * a + ry * b, z)

        dz = z1 - z0
        faces = (   # points, outward horizontal direction, how far the face leans in going up
            ([P(ba1, bb0, z0), P(ba1, bb1, z0), P(ta1, tb1, z1), P(ta1, tb0, z1)], fx, fy, ba1 - ta1),
            ([P(ba0, bb1, z0), P(ba0, bb0, z0), P(ta0, tb0, z1), P(ta0, tb1, z1)], -fx, -fy, ta0 - ba0),
            ([P(ba0, bb0, z0), P(ba1, bb0, z0), P(ta1, tb0, z1), P(ta0, tb0, z1)], -rx, -ry, tb0 - bb0),
            ([P(ba1, bb1, z0), P(ba0, bb1, z0), P(ta0, tb1, z1), P(ta1, tb1, z1)], rx, ry, bb1 - tb1),
        )
        for pts, hx, hy, lean in faces:
            L = math.hypot(dz, lean)
            nx, ny, nz = hx * dz / L, hy * dz / L, lean / L
            p0 = pts[0]
            if (self.cx - p0[0]) * nx + (self.cy - p0[1]) * ny + (self.cz - p0[2]) * nz <= 0:
                continue
            self._poly(surf, pts, self.col(side_base, shade_index(nx, ny, nz), fog), ink)
        if self.cz > z1:
            self._poly(surf, [P(ta0, tb0, z1), P(ta1, tb0, z1), P(ta1, tb1, z1), P(ta0, tb1, z1)],
                       self.col(top_base, 3, fog), ink)

    SPARKS = ((255, 236, 170), (80, 150, 255), (255, 160, 40), (200, 90, 255))     # white, blue, orange, purple

    def _draw_cartoon_car(self, surf, car, fog):
        """Chunky car: big wheels sticking out, tapered cabin, headlights. The shape comes from the car's model
        (sedan, SUV, crossover, pickup); a bumper hop lifts it, a power slide throws sparks, a boost shows a flame."""
        hop = getattr(car, "hop_z", 0.0)
        self.cz -= hop                                       # raising the car = lowering the camera relative to it
        try:
            self._draw_cartoon_car_body(surf, car, fog)
        finally:
            self.cz += hop

    def _draw_cartoon_car_body(self, surf, car, fog):
        pal = getattr(car, "palette", PLAYER_PALETTE)
        sp = getattr(car, "spec", None) or MODELS["sedan"]
        ink = self.ink(fog)
        fx, fy = car.forward
        rx, ry = car.right
        hl, hw = sp["length"] / 2.0, sp["width"] / 2.0
        ride, belt, roof = sp["ride"], sp["z"][0], sp["z"][1]
        wa = sp["wheel"]
        wr = ride + 0.42                                     # wheel height
        near = 1.0 if (self.cx - car.x) * rx + (self.cy - car.y) * ry > 0 else -1.0
        detailed = fog <= 1
        wheel = (26, 24, 34)

        def wheels(side):
            lo, hi = (hw - 0.3, hw + 0.14) if side > 0 else (-hw - 0.14, -hw + 0.3)
            for a in (wa, -wa):
                self._draw_box(surf, car, a - 0.46, a + 0.46, lo, hi, 0.0, wr, wheel, wheel, fog, ink)

        if detailed:
            wheels(-near)                                    # far-side wheels behind the body
        self._draw_box(surf, car, -hl + 0.08, hl - 0.08, -hw + 0.08, hw - 0.08, ride if detailed else 0.08, belt,
                       pal["body"], pal["body"], fog, ink)
        bed = sp.get("bed")
        if bed is not None:                                  # pickup bed: side rails, tailgate and a dark floor
            top = belt + 0.32
            for b0, b1 in ((-hw + 0.08, -hw + 0.24), (hw - 0.24, hw - 0.08)):
                self._draw_box(surf, car, bed[0], bed[1], b0, b1, belt, top, pal["body"], pal["body"], fog, ink)
            self._draw_box(surf, car, bed[0], bed[0] + 0.14, -hw + 0.08, hw - 0.08, belt, top, pal["body"], pal["body"], fog, ink)
            self._draw_box(surf, car, bed[0] + 0.14, bed[1], -hw + 0.24, hw - 0.24, belt, belt + 0.03, (24, 24, 30), (24, 24, 30), fog, ink)
        c0, c1 = sp["cab"]
        t0, t1 = sp["cab_top"]
        self._draw_frustum(surf, car, (c0, c1, -hw + 0.1, hw - 0.1), (t0, t1, -hw + 0.34, hw - 0.34), belt, roof,
                           pal["glass"], pal["roof"], fog, ink)
        if sp.get("spare"):                                  # spare wheel on the back door
            self._draw_box(surf, car, -hl - 0.34, -hl + 0.06, -0.42, 0.42, ride + 0.3, ride + 1.1, wheel, (60, 60, 68), fog, ink)
        if pal.get("lightbar"):
            left_on = int(self.time * 6.0) % 2 == 0
            red = (240, 40, 40) if left_on else (110, 20, 20)
            blue = (70, 110, 255) if not left_on else (24, 36, 100)
            self._draw_box(surf, car, -0.45, 0.15, -0.58, 0.0, roof, roof + 0.2, red, red, fog, ink)
            self._draw_box(surf, car, -0.45, 0.15, 0.0, 0.58, roof, roof + 0.2, blue, blue, fog, ink)
        if detailed:
            wheels(near)                                     # near-side wheels in front of the body
        lz = ride + 0.25
        for ax, face, colour in ((-hl - 0.02, -1.0, pal["tail"]), (hl - 0.06, 1.0, (255, 246, 180))):
            if (self.cx - car.x) * fx * face + (self.cy - car.y) * fy * face <= 0:
                continue
            for b0, b1 in ((-hw + 0.1, -hw + 0.5), (hw - 0.5, hw - 0.1)):
                pts = [(car.x + fx * ax + rx * b, car.y + fy * ax + ry * b, z)
                       for b, z in ((b0, lz), (b1, lz), (b1, lz + 0.26), (b0, lz + 0.26))]
                self._poly(surf, pts, self.col(colour, 3, fog), ink)
        if fog <= 1:
            self._draw_effects(surf, car, hl, hw, wa, fog, ink)

    def _draw_effects(self, surf, car, hl, hw, wa, fog, ink):
        """Power-slide sparks at the rear wheels (colour = charge) and a flame out of the back while boosting."""
        tick = int(self.time * 24.0)
        if getattr(car, "drift", 0):
            col = self.SPARKS[car.charge_level]
            for side in (-1.0, 1.0):
                for k in range(2):
                    j = ((tick * 7 + k * 5 + (side > 0) * 3) % 5) * 0.12
                    b = side * (hw + 0.1 + j)
                    a = -wa - 0.2 - j * 2.0
                    self._draw_box(surf, car, a - 0.12, a + 0.12, b - 0.1, b + 0.1, 0.15 + j, 0.4 + j, col, col, fog, None)
        if getattr(car, "boost_t", 0.0) > 0.0:
            n = 1.0 + 0.5 * (tick % 3)
            for colour, w, ln in (((255, 120, 30), 0.28, 1.0 * n), ((255, 230, 120), 0.14, 0.6 * n)):
                self._draw_box(surf, car, -hl - ln, -hl, -w, w, 0.35, 0.7, colour, colour, fog, None)

    FREIGHT = ((196, 92, 64), (130, 144, 168), (96, 156, 120), (214, 190, 120), (110, 126, 200), (170, 110, 80))

    def _draw_train_unit(self, surf, u, fog):
        """One 9 m block of the train: dark underframe, then a body (locomotive, cab or freight car)."""
        ink = self.ink(fog)
        h = u.length / 2.0 - 0.08
        self._draw_box(surf, u, -h, h, -1.15, 1.15, 0.3, 1.0, (40, 40, 48), (40, 40, 48), fog, ink)
        if u.kind == "car":
            body = self.FREIGHT[(u.idx // 2) % len(self.FREIGHT)]
            self._draw_box(surf, u, -h, h, -HALF_W_DRAW, HALF_W_DRAW, 1.0, 4.2, body, body, fog, ink)
            return
        red, stripe = (176, 44, 44), (240, 200, 60)
        self._draw_box(surf, u, -h, h, -HALF_W_DRAW, HALF_W_DRAW, 1.0, 3.5, red, red, fog, ink)
        self._draw_box(surf, u, -h, h, -HALF_W_DRAW - 0.02, HALF_W_DRAW + 0.02, 2.2, 2.6, stripe, stripe, fog, ink)
        if u.kind == "cab":                       # the cab at the front half of the leading block
            self._draw_box(surf, u, 0.0, h, -HALF_W_DRAW + 0.1, HALF_W_DRAW - 0.1, 3.5, 4.6, (70, 100, 170), red, fog, ink)

    def _draw_car(self, surf, car, fog=0):
        if self.st["cartoon_cars"]:
            self._draw_cartoon_car(surf, car, fog)
            return
        pal = getattr(car, "palette", PLAYER_PALETTE)
        ink = self.ink(fog)
        self._draw_box(surf, car, -1.9, 1.9, -0.8, 0.8, 0.0, 0.4, pal["lower"], pal["lower"], fog, ink)   # wheels / skirt
        self._draw_box(surf, car, -2.1, 2.1, -0.9, 0.9, 0.4, 1.0, pal["body"], pal["body"], fog, ink)      # body
        self._draw_box(surf, car, -1.2, 0.8, -0.75, 0.75, 1.0, 1.6, pal["glass"], pal["roof"], fog, ink)   # cabin
        if pal.get("lightbar"):
            left_on = int(self.time * 6.0) % 2 == 0
            red = (240, 40, 40) if left_on else (110, 20, 20)
            blue = (70, 110, 255) if not left_on else (24, 36, 100)
            self._draw_box(surf, car, -0.2, 0.4, -0.65, 0.0, 1.6, 1.78, red, red, fog, ink)
            self._draw_box(surf, car, -0.2, 0.4, 0.0, 0.65, 1.6, 1.78, blue, blue, fog, ink)
        # tail lights on the rear face
        fx, fy = car.forward
        rx, ry = car.right
        if (self.cx - car.x) * -fx + (self.cy - car.y) * -fy > 0:
            ax = -2.12
            for b0, b1 in ((-0.8, -0.4), (0.4, 0.8)):
                pts = [(car.x + fx * ax + rx * b, car.y + fy * ax + ry * b, z)
                       for b, z in ((b0, 0.6), (b1, 0.6), (b1, 0.85), (b0, 0.85))]
                self._poly(surf, pts, self.col(pal["tail"], 3, fog))
