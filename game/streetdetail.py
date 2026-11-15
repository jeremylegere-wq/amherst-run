"""Street detail built from the map: road paint rules, sidewalks, crosswalks, stop lines, signs and furniture.

Where the data comes from
  * the map's "marks" (OpenStreetMap nodes: stop signs, traffic signals, crossings, rail crossings, and hydrants /
    benches / bins / bus stops if anyone ever maps them),
  * road attributes from the Nova Scotia Road Network (road class "rc", lane count, paved/gravel surface),
  * Canadian road-paint conventions (yellow centre lines, white edge lines, white stop bars and zebra crosswalks),
  * seeded procedural placement for what OpenStreetMap does not have in Amherst: sidewalks, hydrants, benches, bins.

Nothing here draws anything; the renderer reads `marking`, `sidewalk`, `world.paint` and the props.
"""
import math

HIGHWAY_KMH = 90
SIDEWALK_MAX_KMH = 60          # faster roads get a gravel shoulder instead of a sidewalk
SIDEWALK_W = {"concrete": 1.8, "brick": 2.6}
STOP_BACK = 4.5                # metres between a stop line and the junction node
FURNITURE_KINDS = ("stopsign", "signal", "crossbuck", "hydrant", "bench", "bin")
HYDRANT_SPACING = 130.0
BENCH_SPACING = 55.0
BIN_SPACING = 38.0
MAX_FURNITURE = 1800

# marking codes (ints so the renderer's piece tuples stay small)
NONE, DOUBLE_YELLOW, DASH_YELLOW, DASH_WHITE, HIGHWAY, EDGES = range(6)
# sidewalk codes
EDGE, CONCRETE, BRICK = range(3)


SIGNAL_CYCLE = 16.0            # seconds; east-west (phase 0) and north-south (phase 1) take turns
SIGNAL_GREEN = 7.0             # then 1 s of yellow, then red for the other half of the cycle


def signal_light(t, ph):
    """0 red, 1 yellow, 2 green for a signal approach of phase ph at game time t. Shared by renderer and traffic."""
    t = (t + SIGNAL_CYCLE / 2.0 * ph) % SIGNAL_CYCLE
    return 0 if t >= SIGNAL_CYCLE / 2.0 else (2 if t < SIGNAL_GREEN else 1)


def is_highway(road):
    return road["type"] == "main" and road.get("speed", 0) >= HIGHWAY_KMH


def marking(road):
    """Paint on a road, by Canadian convention: none on lanes, drives and gravel; yellow centre lines on two-way
    arterials and collectors; white lane lines on 3+ lanes; edge lines on highways and ramps."""
    if road.get("surface") == "gravel" or road["type"] == "lane" or road.get("service"):
        return NONE
    if road.get("ramp") or (road.get("oneway") and is_highway(road)):
        return EDGES if road.get("ramp") else HIGHWAY
    if is_highway(road):
        return HIGHWAY
    if road["type"] == "main":
        if road.get("oneway"):
            return EDGES
        return DASH_WHITE if (road.get("lanes") or 2) >= 3 else DOUBLE_YELLOW
    if road.get("oneway"):
        return NONE
    if road.get("rc") in ("CO", "LC") or road.get("speed", 50) >= 60:
        return DASH_YELLOW
    return NONE


def sidewalk(road, downtown):
    """EDGE (narrow shoulder), CONCRETE or BRICK sidewalk for a road at a place."""
    if (road.get("surface") == "gravel" or road["type"] == "lane" or road.get("service") or road.get("ramp")
            or road.get("lift") or is_highway(road) or road.get("speed", 50) > SIDEWALK_MAX_KMH):
        return EDGE
    return BRICK if downtown else CONCRETE


class Downtown:
    """Is a spot in the sandstone / brick centre of town? (Amherst's downtown has brick-paved sidewalks.)"""

    CELL = 40.0

    def __init__(self, buildings):
        self.cells = set()
        for b in buildings:
            if b.get("material") in ("sandstone", "brick") and b.get("points"):
                xs = [p[0] for p in b["points"]]
                ys = [p[1] for p in b["points"]]
                self.cells.add((int(sum(xs) / len(xs) // self.CELL), int(sum(ys) / len(ys) // self.CELL)))

    def near(self, x, y):
        cx, cy = int(x // self.CELL), int(y // self.CELL)
        return any((cx + i, cy + j) in self.cells for i in (-1, 0, 1) for j in (-1, 0, 1))


# ------------------------------------------------------------------ geometry
def _closest(road, x, y):
    """(distance, point, unit direction of that segment, distance to the nearer road end) on a road polyline."""
    pts = road["points"]
    best = None
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            continue
        t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
        qx, qy = a[0] + dx * t, a[1] + dy * t
        d = math.hypot(x - qx, y - qy)
        if best is None or d < best[0]:
            L = math.sqrt(L2)
            best = (d, (qx, qy), (dx / L, dy / L))
    if best is None:
        return None
    end = min(math.hypot(x - pts[0][0], y - pts[0][1]), math.hypot(x - pts[-1][0], y - pts[-1][1]))
    return best + (end,)


def _near_roads(world, x, y, reach):
    out = []
    for r in world.roads:
        if r.get("lift") or r.get("service") in ("driveway", "private", "track"):
            continue
        x0, y0, x1, y1 = r.get("bbox") or _bbox(r)
        if x < x0 - reach or x > x1 + reach or y < y0 - reach or y > y1 + reach:
            continue
        c = _closest(r, x, y)
        if c and c[0] <= r["width"] / 2.0 + reach:
            out.append((c[0], r) + c[1:])
    return out


def _bbox(road):
    xs = [p[0] for p in road["points"]]
    ys = [p[1] for p in road["points"]]
    return min(xs), min(ys), max(xs), max(ys)


def _quad(cx, cy, ax, ay, along, across):
    """Rectangle centred on (cx, cy): `along` metres along (ax, ay), `across` metres across it."""
    nx, ny = -ay, ax
    hl, hw = along / 2.0, across / 2.0
    return [(cx - ax * hl - nx * hw, cy - ay * hl - ny * hw), (cx + ax * hl - nx * hw, cy + ay * hl - ny * hw),
            (cx + ax * hl + nx * hw, cy + ay * hl + ny * hw), (cx - ax * hl + nx * hw, cy - ay * hl + ny * hw)]


def _paint(pts, colour):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"pts": [(round(x, 2), round(y, 2)) for x, y in pts], "colour": colour,
            "mx": sum(xs) / len(xs), "my": sum(ys) / len(ys)}


def _prop(kind, x, y, h, r, cr, dx=0.0, dy=0.0, c=0, **extra):
    p = {"kind": kind, "x": round(x, 2), "y": round(y, 2), "h": h, "r": r, "cr": cr, "c": c, "dx": dx, "dy": dy}
    p.update(extra)
    return p


# ------------------------------------------------------------------ mark -> paint + props
def _approaches(world, x, y):
    """Roads arriving at a junction node: [(road, approach unit vector toward the node, point on road)].

    A stop sign sits on the minor road, which is the one that ENDS at the node, so roads whose end is within
    4 m of it count; failing that, the lowest-class road through the node (both directions)."""
    near = _near_roads(world, x, y, 4.0)
    out, ended = [], False
    for d, r, q, direction, end in near:
        if end < 4.0:
            ended = True
            pts = r["points"]
            at_end = math.hypot(x - pts[-1][0], y - pts[-1][1]) <= math.hypot(x - pts[0][0], y - pts[0][1])
            a = direction if at_end else (-direction[0], -direction[1])
            if r.get("oneway") and not at_end:
                continue                                       # nobody drives toward the node on this road
            out.append((r, a, q))
    if out or ended:
        return out
    if near:
        rank = {"lane": 0, "side": 1, "main": 2}
        d, r, q, direction, _end = min(near, key=lambda n: (rank.get(n[1]["type"], 1), n[0]))
        res = [(r, direction, q)]
        if not r.get("oneway"):
            res.append((r, (-direction[0], -direction[1]), q))
        return res
    return []


def _stop_line(road, a, node, colour="white"):
    """Paint polygon for the stop bar across the right-hand lane of an approach, and the sign position."""
    hw = road["width"] / 2.0
    rx, ry = -a[1], a[0]                                       # right of the direction of travel
    lx, ly = node[0] - a[0] * STOP_BACK, node[1] - a[1] * STOP_BACK
    centre = (lx + rx * hw / 2.0, ly + ry * hw / 2.0)
    bar = _paint(_quad(centre[0], centre[1], a[0], a[1], 0.5, hw - 0.4), colour)
    sign = (lx + rx * (hw + 1.3) - a[0] * 0.5, ly + ry * (hw + 1.3) - a[1] * 0.5)
    return bar, sign, (-a[0], -a[1])


def mark_details(world):
    """(paint polygons, props) made from world.marks."""
    paint, props = [], []
    for m in getattr(world, "marks", ()):
        kind, x, y = m.get("kind"), float(m["x"]), float(m["y"])
        if kind == "crossing":
            if m.get("style") == "unmarked":
                continue
            near = [n for n in _near_roads(world, x, y, 2.5) if n[1]["type"] in ("main", "side")]
            if not near:
                continue
            _d, r, q, direction, _end = min(near, key=lambda n: n[0])
            hw = r["width"] / 2.0
            if hw < 2.5:
                continue
            n_bars = max(2, int(2 * hw / 1.2))
            nx, ny = -direction[1], direction[0]
            for i in range(n_bars):                            # zebra bars run along the road, spread across it
                off = -hw + 0.6 + i * (2 * hw - 1.2) / max(1, n_bars - 1)
                paint.append(_paint(_quad(q[0] + nx * off, q[1] + ny * off, direction[0], direction[1], 3.0, 0.55), "white"))
        elif kind in ("stop", "signal"):
            for i, (r, a, _q) in enumerate(_approaches(world, x, y)):
                bar, sign, face = _stop_line(r, a, (x, y))
                paint.append(bar)
                if kind == "stop":
                    props.append(_prop("stopsign", sign[0], sign[1], 2.4, 0.45, 0.15, face[0], face[1]))
                else:
                    ph = 0 if abs(a[0]) >= abs(a[1]) else 1      # east-west and north-south take turns
                    props.append(_prop("signal", sign[0], sign[1], 5.2, 0.4, 0.2, face[0], face[1], ph=ph))
        elif kind == "rail_crossing":
            near = _near_roads(world, x, y, 6.0)
            if not near:
                continue
            _d, r, q, direction, _end = min(near, key=lambda n: n[0])
            hw = r["width"] / 2.0
            for a in (direction, (-direction[0], -direction[1])):
                rx, ry = -a[1], a[0]
                px, py = q[0] - a[0] * 7.0 + rx * (hw + 1.3), q[1] - a[1] * 7.0 + ry * (hw + 1.3)
                props.append(_prop("crossbuck", px, py, 2.7, 0.7, 0.15, -a[0], -a[1]))
        elif kind in ("hydrant", "bench", "bin"):
            props.append(_prop(kind, x, y, *_SIZE[kind]))
        elif kind == "bus_stop":
            props.append(_prop("bench", x, y, *_SIZE["bench"]))
    return paint, props


_SIZE = {"hydrant": (0.9, 0.28, 0.25), "bench": (0.95, 0.9, 0.55), "bin": (1.0, 0.3, 0.3)}


# ------------------------------------------------------------------ procedural furniture
def furniture(world, rng, free, site_ok, add):
    """Hydrants along streets, benches and bins on downtown brick sidewalks. Returns a list of props.

    free(x, y) / add(x, y) are the prop spacing helpers and site_ok(x, y, clear, radius) the placement test of
    game.props, passed in so this module stays free of import cycles."""
    downtown = Downtown(world.buildings)
    out = []
    for r in world.roads:
        if len(out) >= MAX_FURNITURE:
            break
        if (r["type"] == "lane" or r.get("service") or r.get("lift") or r.get("bridge") or r.get("ramp")
                or r.get("surface") == "gravel" or is_highway(r) or r.get("speed", 50) > SIDEWALK_MAX_KMH):
            continue
        hw = r["width"] / 2.0
        pts = r["points"]
        run = rng.uniform(0.0, HYDRANT_SPACING)                 # distance along the road to the next hydrant
        bench_at, bin_at = rng.uniform(10.0, BENCH_SPACING), rng.uniform(5.0, BIN_SPACING)
        s0 = 0.0
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 1.0:
                continue
            dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, ny = -dy, dx
            for s in _steps(s0, s0 + L, run, HYDRANT_SPACING, rng):
                side = 1.0 if rng.random() < 0.5 else -1.0
                px, py = a[0] + dx * (s - s0) + nx * side * (hw + 2.4), a[1] + dy * (s - s0) + ny * side * (hw + 2.4)
                if free(px, py) and site_ok(px, py, 0.8, 0.3):
                    out.append(_prop("hydrant", px, py, *_SIZE["hydrant"], c=0))
                    add(px, py)
            if downtown.near(a[0], a[1]):
                for s in _steps(s0, s0 + L, bench_at, BENCH_SPACING, rng):
                    side = 1.0 if rng.random() < 0.5 else -1.0
                    px, py = a[0] + dx * (s - s0) + nx * side * (hw + 1.0), a[1] + dy * (s - s0) + ny * side * (hw + 1.0)
                    if free(px, py) and site_ok(px, py, 0.6, 0.5):
                        out.append(_prop("bench", px, py, *_SIZE["bench"], dx=-nx * side, dy=-ny * side))
                        add(px, py)
                for s in _steps(s0, s0 + L, bin_at, BIN_SPACING, rng):
                    side = 1.0 if rng.random() < 0.5 else -1.0
                    px, py = a[0] + dx * (s - s0) + nx * side * (hw + 1.2), a[1] + dy * (s - s0) + ny * side * (hw + 1.2)
                    if free(px, py) and site_ok(px, py, 0.6, 0.3):
                        out.append(_prop("bin", px, py, *_SIZE["bin"]))
                        add(px, py)
            s0 += L
            run = _next(s0, run, HYDRANT_SPACING)
            bench_at = _next(s0, bench_at, BENCH_SPACING)
            bin_at = _next(s0, bin_at, BIN_SPACING)
    return out


def _steps(lo, hi, first, spacing, rng):
    """Positions in [lo, hi) of a series that starts at `first` and repeats every ~spacing."""
    s = first
    while s < lo:
        s += spacing
    while s < hi:
        yield s
        s += spacing * rng.uniform(0.8, 1.25)


def _next(passed, first, spacing):
    s = first
    while s < passed:
        s += spacing
    return s
