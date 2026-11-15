"""A freight train that runs along the real rail line now and then.

The OSM/NSRN rail ways are stitched into one long chain (following the straightest continuation at each junction),
a stretch of it around the town is used as the run, and every few minutes a train (locomotive + cars) drives the
whole stretch and disappears at the far end. It is solid: cars that touch it are pushed off and slowed.
"""
import math
import random

TRAIN_SPEED = 16.0            # m/s (about 58 km/h)
FIRST_DELAY = (50.0, 90.0)    # seconds until the first train after the game starts
GAP = (240.0, 420.0)          # seconds between trains once one has cleared the stretch
SECTION = 1500.0              # metres of track either side of the town centre that a train runs through
LOCO_UNITS = 2                # locomotive = two 9 m blocks (cab at the front one)
UNIT_LEN = 9.0
CAR_UNITS = (6, 11)           # freight cars behind it (two blocks each) - min, max
HALF_W = 1.45                 # train is 2.9 m wide
HEIGHT = 4.2
JOIN_TOL = 4.0                # rail ends closer than this are the same junction


def _length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def stitch(rails):
    """Join rail ways end to end into the longest chain that keeps going as straight as it can."""
    ways = [r["points"] for r in rails if len(r["points"]) >= 2]
    if not ways:
        return []
    nodes = []                                             # clustered end points

    def node(p):
        for i, q in enumerate(nodes):
            if math.hypot(p[0] - q[0], p[1] - q[1]) < JOIN_TOL:
                return i
        nodes.append(tuple(p[:2]))
        return len(nodes) - 1

    edges = [(node(w[0]), node(w[-1]), w) for w in ways]
    edges = [e for e in edges if e[0] != e[1]]
    at = {}
    for ei, (a, b, _w) in enumerate(edges):
        at.setdefault(a, []).append(ei)
        at.setdefault(b, []).append(ei)

    def heading(p, q):
        return math.atan2(q[1] - p[1], q[0] - p[0])

    def oriented(ei, start):
        a, b, w = edges[ei]
        return list(w) if a == start else list(reversed(w))

    best = []
    starts = [n for n in at if len(at[n]) == 1] or list(at)
    for s in starts:
        for first in at[s]:
            used, chain, cur = {first}, oriented(first, s), edges[first][1] if edges[first][0] == s else edges[first][0]
            while True:
                h0 = heading(chain[-2], chain[-1])
                cands = []
                for ei in at.get(cur, ()):
                    if ei in used:
                        continue
                    seg = oriented(ei, cur)
                    turn = abs((heading(seg[0], seg[1]) - h0 + math.pi) % (2 * math.pi) - math.pi)
                    cands.append((turn, ei, seg))
                if not cands:
                    break
                turn, ei, seg = min(cands, key=lambda c: c[0])
                if turn > math.radians(70):                # no sharp turns: that would be a different line
                    break
                used.add(ei)
                chain += seg[1:]
                a, b, _w = edges[ei]
                cur = b if a == cur else a
            if _length(chain) > _length(best):
                best = chain
    return best


class Unit:
    """One block of the train: gives the renderer the same forward/right axes a car has."""
    __slots__ = ("x", "y", "heading", "kind", "length", "idx", "forward", "right")

    def __init__(self, x, y, heading, kind, length, idx=0):
        self.x, self.y, self.heading, self.kind, self.length, self.idx = x, y, heading, kind, length, idx
        self.forward = (math.cos(heading), math.sin(heading))
        self.right = (-math.sin(heading), math.cos(heading))


class Train:
    def __init__(self, world, seed=1, enabled=True):
        self.rng = random.Random(seed * 104729 + 11)
        self.chain = stitch(world.rails) if enabled else []
        self.cum = [0.0]
        for a, b in zip(self.chain, self.chain[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.total = self.cum[-1]
        self.active = False
        self._cache = None
        self.s = 0.0                   # position of the front of the train along the stretch
        self.dir = 1
        self.cars = 0
        self.wait = self.rng.uniform(*FIRST_DELAY)
        self.lo = self.hi = 0.0
        if self.total > 0:
            self._pick_stretch(world)

    # --- track ---------------------------------------------------------------
    def _pick_stretch(self, world):
        """Limit the run to SECTION metres either side of the point of the chain nearest the town centre."""
        x, y = world.spawn()[:2]
        best, best_s = 1e18, 0.0
        for i, (a, b) in enumerate(zip(self.chain, self.chain[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy or 1.0
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
            d = math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
            if d < best:
                best, best_s = d, self.cum[i] + t * math.sqrt(L2)
        self.lo = max(0.0, best_s - SECTION)
        self.hi = min(self.total, best_s + SECTION)

    def point_at(self, s):
        """(x, y, heading) on the chain at distance s."""
        s = max(0.0, min(self.total, s))
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        a, b = self.chain[lo], self.chain[lo + 1]
        seg = self.cum[lo + 1] - self.cum[lo] or 1.0
        t = (s - self.cum[lo]) / seg
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, math.atan2(b[1] - a[1], b[0] - a[0])

    # --- running -------------------------------------------------------------
    @property
    def length(self):
        return (LOCO_UNITS + 2 * self.cars) * UNIT_LEN

    def update(self, dt):
        if self.total <= 0 or self.hi - self.lo < 200.0:
            return
        self._cache = None
        if not self.active:
            self.wait -= dt
            if self.wait <= 0.0:
                self.active = True
                self.cars = self.rng.randint(*CAR_UNITS)
                self.dir = self.rng.choice((1, -1))
                self.s = self.lo if self.dir > 0 else self.hi            # front starts at the entry end
            return
        self.s += self.dir * TRAIN_SPEED * dt
        tail = self.s - self.dir * self.length
        past = (self.s > self.hi and tail > self.hi) if self.dir > 0 else (self.s < self.lo and tail < self.lo)
        if past:
            self.active = False
            self.wait = self.rng.uniform(*GAP)

    def units(self):
        """Blocks of the running train from the front backwards (empty when no train is running)."""
        if not self.active:
            return []
        if self._cache is not None:
            return self._cache
        out = []
        n = LOCO_UNITS + 2 * self.cars
        for i in range(n):
            s = self.s - self.dir * (i + 0.5) * UNIT_LEN
            if s < self.lo - UNIT_LEN or s > self.hi + UNIT_LEN:
                continue
            x, y, h = self.point_at(s)
            if self.dir < 0:
                h += math.pi                                              # the front faces down the chain
            kind = "cab" if i == 0 else "loco" if i < LOCO_UNITS else "car"
            out.append(Unit(x, y, h, kind, UNIT_LEN, i))
        self._cache = out
        return out

    def push_out(self, car):
        """If `car` is inside a train block, shove it clear and slow it. Returns the impact speed (0 if no contact)."""
        if not self.active:
            return 0.0
        for u in self.units():
            dx, dy = car.x - u.x, car.y - u.y
            if dx * dx + dy * dy > 100.0:
                continue
            a = dx * u.forward[0] + dy * u.forward[1]
            b = dx * u.right[0] + dy * u.right[1]
            ha, hb = u.length / 2 + 1.2, HALF_W + 1.2                      # car half sizes added
            if abs(a) < ha and abs(b) < hb:
                if hb - abs(b) < ha - abs(a):                              # nearest edge: the side
                    b = math.copysign(hb, b)
                else:
                    a = math.copysign(ha, a)
                car.x = u.x + u.forward[0] * a + u.right[0] * b
                car.y = u.y + u.forward[1] * a + u.right[1] * b
                hit = car.speed
                car.vx *= 0.2
                car.vy *= 0.2
                return hit
        return 0.0
