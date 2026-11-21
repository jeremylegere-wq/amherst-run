"""World data: loads the converted map and answers spatial queries."""
import json
import math
import os
from collections import OrderedDict, defaultdict

CELL = 40.0  # spatial grid cell size in metres
WOODS_CELLS_KEPT = 3000   # streamed woods cells kept in memory; the oldest are dropped (and remade if seen again)
WOODS_SYNC = 12.0         # props_near always makes the woods of cells this close to the point (so collision sees them)
WOODS_PER_CALL = 1        # ...and at most this many farther cells per call, nearest first (spreads the cost over frames)


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _cells(bb):
    x0, y0, x1, y1 = bb
    for cx in range(int(x0 // CELL), int(x1 // CELL) + 1):
        for cy in range(int(y0 // CELL), int(y1 // CELL) + 1):
            yield cx, cy


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_in_polygon(x, y, pts):
    """Ray-casting point-in-polygon test."""
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


CLEARANCE = 1.8         # a deck lower than this has no road under it (it is a ramp, so it is the ground)
SPAN_RAMP = 60.0       # metres of approach ramp on each side of an overpass deck


def _walk(points, dist):
    """The first `dist` metres of a polyline (the last point is interpolated)."""
    out, left = [tuple(points[0])], dist
    for a, b in zip(points, points[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg >= left:
            t = left / seg if seg else 0.0
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            return out
        out.append(tuple(b))
        left -= seg
    return out


def _densify(points, step):
    """Insert points so no segment is longer than `step` (so a ramp's smooth height profile has enough samples)."""
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        n = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for i in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
    return out


def build_spans(roads):
    """Overpasses: every road with a 'lift' becomes a span = ramp up, flat deck, ramp down.

    A span is {"road", "width", "lift", "points": [(x, y)...], "h": [metres...]}. Ramps follow the road the deck
    continues into, SPAN_RAMP metres on each side, rising smoothly from the ground.
    """
    spans = []
    for road in roads:
        lift = road.get("lift")
        if not lift:
            continue
        deck = [tuple(p) for p in road["points"]]
        hs = [lift] * len(deck)
        for end in (0, 1):
            ex, ey = deck[0] if end == 0 else deck[-1]
            ramp = None
            for o in roads:
                if o is road or o.get("bridge") or o.get("lift"):
                    continue
                for oend in (0, 1):
                    q = o["points"][0] if oend == 0 else o["points"][-1]
                    if abs(q[0] - ex) < 3.0 and abs(q[1] - ey) < 3.0:
                        pts = o["points"] if oend == 0 else o["points"][::-1]
                        ramp = _densify(_walk(pts, SPAN_RAMP), 8.0)
                        break
                if ramp:
                    break
            if not ramp or len(ramp) < 2:
                continue
            total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(ramp, ramp[1:])) or 1.0
            run, rh = 0.0, [lift]
            for a, b in zip(ramp, ramp[1:]):
                run += math.hypot(b[0] - a[0], b[1] - a[1])
                u = 1.0 - run / total                       # 1 at the deck, 0 at the ground
                rh.append(lift * u * u * (3 - 2 * u))
            if end == 0:
                deck = ramp[::-1] + deck[1:]
                hs = rh[::-1] + hs[1:]
            else:
                deck = deck[:-1] + ramp
                hs = hs[:-1] + rh
        spans.append({"road": road, "width": road["width"], "lift": lift, "points": deck, "h": hs})
    return spans


def sp_height(sp, x, y):
    """Deck height of a span at (x, y), or None when the point is off the deck."""
    pts, hs = sp["points"], sp["h"]
    half = sp["width"] / 2 + 0.3
    best = None
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        if ll < 1e-9:
            continue
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ll))
        d = math.hypot(x - (ax + dx * t), y - (ay + dy * t))
        if d <= half and (best is None or d < best[0]):
            best = (d, hs[i] + (hs[i + 1] - hs[i]) * t)
    return best[1] if best else None


def parked_blocks(parked):
    """Invisible collision circles ("car_block" props) covering each parked car: one in the middle, one near each end."""
    from .car import MODELS
    out = []
    for c in parked:
        spec = MODELS.get(c.get("model"), MODELS["sedan"])
        r = spec["width"] / 2.0
        off = max(0.0, spec["length"] / 2.0 - r)
        fx, fy = math.cos(c["heading"]), math.sin(c["heading"])
        for a in (-off, 0.0, off):
            out.append({"kind": "car_block", "x": c["x"] + fx * a, "y": c["y"] + fy * a, "h": 0.0, "r": 0.0, "cr": r})
    return out


class World:
    def __init__(self, data, terrain=None):
        self.custom_path = None
        self.terrain = terrain                    # game.terrain.Terrain, or None for a flat world
        self.addresses = None                     # game.addresses.Addresses (real civic numbers), set by World.load
        self.meta = data["meta"]
        self.roads = data["roads"]
        self.buildings = data["buildings"]
        self.rails = data.get("rails", [])
        self.water = data.get("water", [])
        self.parks = data.get("parks", [])
        self.lots = data.get("lots", [])                       # open parking lots (game/parking.py)
        self.areas = data.get("areas", [])                     # land use colours (game/extras.py)
        self.waterways = data.get("waterways", [])             # rivers, streams and ditches as lines
        landmarks = data.get("landmarks", [])
        self.horizon = [l for l in landmarks if l["kind"] == "turbine"]   # drawn on the skyline
        for group in (self.roads, self.buildings, self.rails, self.water, self.parks, self.lots, self.areas, self.waterways):
            for item in group:
                item["bbox"] = _bbox(item["points"])
        self.bounds = tuple(self.meta["bounds"])
        # where the town actually is (long roads can trail far outside the downloaded box)
        if self.buildings:
            bx = [b["bbox"] for b in self.buildings]
            self.core_bounds = (max(self.bounds[0], min(b[0] for b in bx) - 150),
                                max(self.bounds[1], min(b[1] for b in bx) - 150),
                                min(self.bounds[2], max(b[2] for b in bx) + 150),
                                min(self.bounds[3], max(b[3] for b in bx) + 150))
        else:
            self.core_bounds = self.bounds

        # Road segments and building indices go into grids for fast lookups
        self._road_grid = defaultdict(list)
        for r in self.roads:
            pts = r["points"]
            for a, b in zip(pts, pts[1:]):
                seg = (a[0], a[1], b[0], b[1], r["width"])
                for c in _cells(_bbox([a, b])):
                    self._road_grid[c].append(seg)
        self._name_grid = defaultdict(list)          # same segments with the road index, for street names
        for ri, r in enumerate(self.roads):
            pts = r["points"]
            for a, b in zip(pts, pts[1:]):
                for c in _cells(_bbox([a, b])):
                    self._name_grid[c].append((a[0], a[1], b[0], b[1], r["width"], ri))
        self.spans = build_spans(self.roads)         # overpass decks and their approach ramps
        self._span_grid = defaultdict(list)
        for sp in self.spans:
            for c in _cells(_bbox(sp["points"])):
                self._span_grid[c].append(sp)
        self._bld_grid = defaultdict(list)
        for i, b in enumerate(self.buildings):
            for c in _cells(b["bbox"]):
                self._bld_grid[c].append(i)

        # street props (trees, lamp posts): OSM ones plus procedural ones along the streets
        self.props = []
        self._prop_grid = defaultdict(list)
        procedural = self.meta.get("procedural_props", True)
        from .streetdetail import mark_details
        self.woods = data.get("woods", [])                      # NSTDB treed areas (tools/fetch_landcover.py)
        self.marks = data.get("marks", [])                      # OSM stop signs, signals, crossings...
        self.paint, mark_props = mark_details(self)             # stop bars and crosswalks, plus signs and signals
        osm_props = ([l for l in landmarks if l["kind"] in ("cenotaph", "lighthouse")] + data.get("props", [])
                     + mark_props)
        if procedural or osm_props:
            from .props import build_props
            for p in build_props(self, osm_props, seed=self.meta.get("seed", 1), procedural=procedural):
                if self._near_span(p["x"], p["y"], 4.0):
                    continue                          # no trees or lamps on or beside a deck and its ramps
                self._prop_grid[(int(p["x"] // CELL), int(p["y"] // CELL))].append(p)
                self.props.append(p)
        self.parked = data.get("parked", [])                  # hand-placed parked cars (map_edits.json "cars")
        for p in parked_blocks(self.parked):                  # solid: three circles along each car
            self._prop_grid[(int(p["x"] // CELL), int(p["y"] // CELL))].append(p)
        # the woods' trees are made per prop cell the first time props_near looks there (see _make_woods)
        self._woods_index = None
        self._woods_made = OrderedDict()                      # cell -> how many fixed props it had before its woods
        self._woods_seed = self.meta.get("seed", 1)
        if procedural and self.woods:
            from .landcover import WoodsIndex
            self._woods_index = WoodsIndex(self.woods)

    @classmethod
    def load(cls, path, custom="auto", zoning=True, terrain=True):
        """Load a map file. `custom` is a custom-buildings file (default: custom_buildings.json beside the map).
        terrain=False ignores elevation.json (flat world, cheaper to draw)."""
        with open(path) as f:
            data = json.load(f)
        from . import lidar
        line = lidar.apply(data, lidar.load_beside(path))                       # measured heights and roofs (LiDAR)
        if line:
            print(line)
        from . import mapedits
        for line in mapedits.apply(data, mapedits.load_beside(path)):          # your hand edits (tools/map_editor.py)
            print(line)
        from . import parking                         # open parking lots; after the edits (they key on whole roads)
        line = parking.apply(data, parking.load_beside(path))
        if line:
            print(line)
        from . import extras                          # land use, waterways, power lines, fences (OSM extras)
        line = extras.apply(data, extras.load_beside(path))
        if line:
            print(line)
        if zoning:                                    # zone looks first, so custom buildings and landmarks win
            from . import zoning as zoning_mod
            zones = zoning_mod.load_beside(path)
            if zones is not None:
                zoning_mod.apply(data, zones)
        from .landcover import load_beside as load_woods
        data["woods"] = load_woods(path)
        if custom == "auto":
            custom = os.path.join(os.path.dirname(os.path.abspath(path)), "custom_buildings.json")
        if custom and os.path.exists(custom):
            from .builder import apply_custom, load_doc
            try:
                for line in apply_custom(data, load_doc(custom)):
                    print(line)
            except (ValueError, json.JSONDecodeError) as e:
                print("custom buildings ignored:", e)
        from .terrain import Terrain
        elev = os.path.join(os.path.dirname(os.path.abspath(path)), "elevation.json")
        world = cls(data, terrain=Terrain.load(elev) if terrain else None)
        world.custom_path = custom or None
        from .addresses import Addresses
        world.addresses = Addresses.load(os.path.join(os.path.dirname(os.path.abspath(path)), "addresses.json"))
        return world

    def ground(self, x, y):
        """Height of the natural ground at (x, y) in metres (0 on a flat map)."""
        return self.terrain.height(x, y) if self.terrain is not None else 0.0

    # --- editing buildings while the game runs (build mode) ------------------
    def _index_building(self, i):
        for c in _cells(self.buildings[i]["bbox"]):
            self._bld_grid[c].append(i)

    def _unindex_building(self, i):
        for c in _cells(self.buildings[i]["bbox"]):
            lst = self._bld_grid.get(c)
            if lst and i in lst:
                lst.remove(i)

    def add_building(self, b):
        b["bbox"] = _bbox(b["points"])
        self.buildings.append(b)
        self._index_building(len(self.buildings) - 1)
        return len(self.buildings) - 1

    def set_building(self, i, b):
        self._unindex_building(i)
        b["bbox"] = _bbox(b["points"])
        self.buildings[i] = b
        self._index_building(i)

    def remove_building(self, i):
        """Take a building out of the world. The slot stays (indices are stable) as a speck far off the map."""
        self._unindex_building(i)
        far = -1.0e6
        self.buildings[i] = {"points": [[far, far], [far, far + 1], [far + 1, far]], "bbox": (far, far, far + 1, far + 1),
                             "removed": True}
    # --- queries -----------------------------------------------------------
    def in_lot(self, x, y):
        """True if (x, y) is on an open parking lot."""
        if not self.lots:
            return False
        if not hasattr(self, "_lot_grid"):
            self._lot_grid = defaultdict(list)
            for i, lot in enumerate(self.lots):
                for c in _cells(lot["bbox"]):
                    self._lot_grid[c].append(i)
        for i in self._lot_grid.get((int(x // CELL), int(y // CELL)), ()):
            lot = self.lots[i]
            x0, y0, x1, y1 = lot["bbox"]
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, lot["points"]):
                return True
        return False

    def on_road(self, x, y):
        """True if (x, y) lies within any road's width, or on an open parking lot."""
        cx, cy = int(x // CELL), int(y // CELL)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for ax, ay, bx, by, w in self._road_grid.get((gx, gy), ()):
                    if _seg_dist(x, y, ax, ay, bx, by) <= w / 2:
                        return True
        return self.in_lot(x, y)

    def _near_span(self, x, y, margin):
        for sp in self._span_grid.get((int(x // CELL), int(y // CELL)), ()):
            pts = sp["points"]
            for a, b in zip(pts, pts[1:]):
                if _seg_dist(x, y, a[0], a[1], b[0], b[1]) <= sp["width"] / 2 + margin:
                    return True
        return False

    def road_at(self, x, y, z=0.0):
        """The road under (x, y) as a dict (None off-road). On an overpass, z picks the deck or the road below."""
        z = z - self.ground(x, y)                  # heights below are relative to the ground
        cx, cy = int(x // CELL), int(y // CELL)
        best = None
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for ax, ay, bx, by, w, ri in self._name_grid.get((gx, gy), ()):
                    d = _seg_dist(x, y, ax, ay, bx, by) - w / 2
                    if d > 1.5:
                        continue
                    r = self.roads[ri]
                    if r["type"] == "lane" and r.get("service") in ("driveway", "track", "private"):
                        d += 3.0                       # a street beats a driveway
                    if r.get("lift"):                  # an overpass deck: only counts when the car is up there
                        h = self.deck_height(x, y, r)
                        d += abs(z - h) * 0.5 if h is not None else 9.0
                    elif z > 2.5:                      # up on a deck: the road below is not the one we are on
                        d += (z - 2.5) * 0.5
                    if best is None or d < best[0]:
                        best = (d, r)
        return best[1] if best else None

    def deck_height(self, x, y, road):                # relative to the ground
        """Height of an overpass span of this road at (x, y) or None if (x, y) is not on its deck."""
        for sp in self._span_grid.get((int(x // CELL), int(y // CELL)), ()):
            if sp["road"] is road:
                h = sp_height(sp, x, y)
                if h is not None:
                    return h
        return None

    def height_at(self, x, y, z_hint=0.0):
        """Surface height under (x, y): the ground, or an overpass deck/ramp on top of it - nearest z_hint."""
        g = self.ground(x, y)
        spans = self._span_grid.get((int(x // CELL), int(y // CELL)))
        if not spans:
            return g
        hs = [h for h in (sp_height(sp, x, y) for sp in spans) if h is not None]
        if not hs:
            return g
        if min(hs) < CLEARANCE:                   # a low ramp IS the ground here: nothing can drive beneath it
            return g + min(hs)
        rel, best = z_hint - g, 0.0               # higher up there is room for the road below as well
        for h in hs:
            if abs(h - rel) < abs(best - rel):
                best = h
        return g + best

    def in_building(self, x, y):
        for i in self._bld_grid.get((int(x // CELL), int(y // CELL)), ()):
            b = self.buildings[i]
            x0, y0, x1, y1 = b["bbox"]
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, b["points"]):
                return True
        return False

    def buildings_near(self, x, y, r):
        """Indices of buildings whose grid cells overlap the square of half-size r around (x, y)."""
        out = set()
        for gx in range(int((x - r) // CELL), int((x + r) // CELL) + 1):
            for gy in range(int((y - r) // CELL), int((y + r) // CELL) + 1):
                out.update(self._bld_grid.get((gx, gy), ()))
        return out

    def road_clearance(self, x, y):
        """Distance from (x, y) to the nearest road edge within ~40 m (negative when on a road)."""
        best = 1e9
        cx, cy = int(x // CELL), int(y // CELL)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for ax, ay, bx, by, w in self._road_grid.get((gx, gy), ()):
                    d = _seg_dist(x, y, ax, ay, bx, by) - w / 2
                    if d < best:
                        best = d
        return best

    def props_near(self, x, y, r, far=WOODS_PER_CALL):
        """Props within roughly r metres (square test) of a point. Woods trees in cells not seen before are made here:
        all of those near the point, and `far` of the others (a second query in the same frame passes 0)."""
        out = []
        gx0, gx1, gy0, gy1 = int((x - r) // CELL), int((x + r) // CELL), int((y - r) // CELL), int((y + r) // CELL)
        if self._woods_index is not None:
            self._stream_woods(x, y, gx0, gx1, gy0, gy1, far)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                for p in self._prop_grid.get((gx, gy), ()):
                    if abs(p["x"] - x) <= r and abs(p["y"] - y) <= r:
                        out.append(p)
        return out

    def _prop_within(self, x, y, gap):
        """True when any prop already in the grid stands closer than `gap` to (x, y) (makes no woods)."""
        g2 = gap * gap
        for gx in range(int((x - gap) // CELL), int((x + gap) // CELL) + 1):
            for gy in range(int((y - gap) // CELL), int((y + gap) // CELL) + 1):
                for p in self._prop_grid.get((gx, gy), ()):
                    if (p["x"] - x) ** 2 + (p["y"] - y) ** 2 < g2:
                        return True
        return False

    def _stream_woods(self, x, y, gx0, gx1, gy0, gy1, n_far):
        """Make the missing woods cells of this block: all those within WOODS_SYNC of (x, y), and n_far of the
        others, nearest first. The rest wait for later calls (the renderer asks every frame)."""
        made, far = self._woods_made, []
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                if (gx, gy) in made:
                    continue
                dx = max(gx * CELL - x, 0.0, x - (gx + 1) * CELL)
                dy = max(gy * CELL - y, 0.0, y - (gy + 1) * CELL)
                d = dx * dx + dy * dy
                if d <= WOODS_SYNC * WOODS_SYNC:
                    self._make_woods(gx, gy)
                else:
                    far.append((d, gx, gy))
        if far and n_far > 0:
            far.sort()
            for _d, gx, gy in far[:n_far]:
                self._make_woods(gx, gy)

    def warm_woods(self, x, y, r):
        """Make every woods cell within r of (x, y) now (a loading screen, a test, a benchmark)."""
        for gx in range(int((x - r) // CELL), int((x + r) // CELL) + 1):
            for gy in range(int((y - r) // CELL), int((y + r) // CELL) + 1):
                if self._woods_index is not None and (gx, gy) not in self._woods_made:
                    self._make_woods(gx, gy)

    def _make_woods(self, gx, gy):
        """Plant the woods trees of prop cell (gx, gy), after the fixed props already there."""
        cell = self._prop_grid.get((gx, gy))
        self._woods_made[(gx, gy)] = len(cell) if cell else 0
        if len(self._woods_made) > WOODS_CELLS_KEPT:           # forget the oldest cell's trees; they come back the same
            old, n = self._woods_made.popitem(last=False)
            lst = self._prop_grid.get(old)
            if lst:
                del lst[n:]
        x0, y0 = gx * CELL, gy * CELL
        bx0, by0, bx1, by1 = self.bounds
        if x0 > bx1 or y0 > by1 or x0 + CELL < bx0 or y0 + CELL < by0:
            return
        from .props import MIN_GAP, woods_cell
        trees = woods_cell(self, self._woods_index, gx, gy, CELL, lambda x, y: self._prop_within(x, y, MIN_GAP),
                           seed=self._woods_seed)
        trees = [t for t in trees if not self._near_span(t["x"], t["y"], 4.0)]
        if trees:
            self._prop_grid[(gx, gy)].extend(trees)

    def woods_trees_made(self):
        """How many streamed woods trees are in memory now (for tests and benchmarks)."""
        return sum(len(self._prop_grid.get(c, ())) - n for c, n in self._woods_made.items())

    def in_bounds(self, x, y, margin=0.0):
        x0, y0, x1, y1 = self.bounds
        return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin

    def spawn(self):
        """Return (x, y, heading). Uses meta spawn if present, else the longest main road."""
        if "spawn" in self.meta:
            return tuple(self.meta["spawn"])
        best, best_len = None, -1.0
        for r in self.roads:
            if r["type"] != "main":
                continue
            for a, b in zip(r["points"], r["points"][1:]):
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                if L > best_len:
                    best, best_len = (a, b), L
        if best is None and self.roads:
            a, b = self.roads[0]["points"][:2]
            best = (a, b)
        if best is None:
            return (0.0, 0.0, 0.0)
        (ax, ay), (bx, by) = best
        return ((ax + bx) / 2, (ay + by) / 2, math.atan2(by - ay, bx - ax))

    def visible(self, group, x0, y0, x1, y1):
        """Yield items in `group` whose bbox overlaps the given world rectangle."""
        for item in group:
            bx0, by0, bx1, by1 = item["bbox"]
            if bx1 >= x0 and bx0 <= x1 and by1 >= y0 and by0 <= y1:
                yield item
