"""Battle items: item boxes at junctions, the items they hand out, and the shots and slicks those items leave on the map.

Pure logic (no pygame): game/battle.py runs it each physics step and game/render3d.py draws what it describes.
All names and looks are this game's own.

  puck        a flat disc fired straight ahead; skims along the road and bounces off buildings up to 4 times
  seeker      a homing shot that turns towards the nearest rival; breaks on the first wall it touches
  slick       an oil slick dropped behind the car; whoever drives over it spins out
  turbo       a 2 second burst of speed (ramming the rival while it lasts pops one of their balloons)
  ghost       6 seconds untouchable: shots and slicks pass through, top speed up, and touching the rival pops a balloon
  triple      three pucks circling the car: they block shots coming in, and fire one at a time
"""
import math

ITEMS = ("puck", "seeker", "slick", "turbo", "ghost", "triple")
NAMES = {"puck": "PUCK", "seeker": "SEEKER", "slick": "OIL SLICK", "turbo": "TURBO CAN", "ghost": "GHOST MODE",
         "triple": "TRIPLE PUCK"}
COLOURS = {"puck": (70, 210, 230), "seeker": (240, 70, 60), "slick": (34, 30, 40), "turbo": (255, 150, 30),
           "ghost": (236, 240, 255), "triple": (70, 210, 230)}
WEIGHTS = {"puck": 3.0, "seeker": 2.0, "slick": 3.0, "turbo": 3.0, "ghost": 1.0, "triple": 1.5}

ROULETTE_TIME = 1.2      # seconds the item box spins through items before one is picked
BOX_RESPAWN = 8.0        # seconds before a collected box comes back
BOX_REACH = 2.6          # metres: drive this close to a box to collect it
BOX_SPACING = 70.0       # metres between boxes at least

PUCK_SPEED, PUCK_LIFE, PUCK_BOUNCES = 34.0, 7.0, 4
SEEKER_SPEED, SEEKER_LIFE, SEEKER_TURN = 30.0, 9.0, 3.2       # m/s, seconds, rad/s
SHOT_HIT = 1.9           # metres from a car's centre that counts as a hit
OWNER_SAFE = 0.5         # seconds a new shot cannot hit the car that fired it
SLICK_RADIUS, SLICK_LIFE, SLICK_SAFE = 1.7, 45.0, 1.0
ORBIT_RADIUS, ORBIT_SPIN = 2.6, 4.0                            # metres, rad/s
ORBIT_BLOCK = 1.3        # metres: an incoming shot this close to an orbiting puck is stopped by it


def pick_item(rng):
    """One item, weighted (ghost and triple are rarer)."""
    total = sum(WEIGHTS[k] for k in ITEMS)
    r = rng.uniform(0.0, total)
    for k in ITEMS:
        r -= WEIGHTS[k]
        if r <= 0.0:
            return k
    return ITEMS[-1]


class ItemBox:
    __slots__ = ("x", "y", "wait")

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.wait = 0.0          # seconds until it is back (0 = there)

    @property
    def present(self):
        return self.wait <= 0.0


def box_sites(graph, centre, radius, spacing=BOX_SPACING, limit=80):
    """Junctions (3 or more roads meet) within `radius` of `centre`, at least `spacing` apart, nearest first."""
    cx, cy = centre
    nodes = [n for n in range(len(graph.nodes)) if len(graph.out[n]) >= 3]
    nodes.sort(key=lambda n: (graph.nodes[n][0] - cx) ** 2 + (graph.nodes[n][1] - cy) ** 2)
    out = []
    for n in nodes:
        x, y = graph.nodes[n]
        if math.hypot(x - cx, y - cy) > radius:
            break
        if all(math.hypot(x - b.x, y - b.y) >= spacing for b in out):
            out.append(ItemBox(x, y))
            if len(out) >= limit:
                break
    return out


class Shot:
    """A puck or a seeker skimming along the ground."""
    __slots__ = ("kind", "x", "y", "vx", "vy", "owner", "life", "bounces", "age")

    def __init__(self, kind, x, y, heading, owner):
        speed = PUCK_SPEED if kind == "puck" else SEEKER_SPEED
        self.kind, self.owner = kind, owner
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(heading) * speed, math.sin(heading) * speed
        self.life = PUCK_LIFE if kind == "puck" else SEEKER_LIFE
        self.bounces = 0
        self.age = 0.0


class Slick:
    __slots__ = ("x", "y", "owner", "life", "age")

    def __init__(self, x, y, owner):
        self.x, self.y, self.owner = x, y, owner
        self.life, self.age = SLICK_LIFE, 0.0


def fire(kind, car, owner):
    """The shot (puck/seeker) a car fires: from just in front of its nose, along its heading."""
    fx, fy = car.forward
    return Shot(kind, car.x + fx * 3.2, car.y + fy * 3.2, car.heading, owner)


def drop_slick(car, owner):
    fx, fy = car.forward
    return Slick(car.x - fx * 3.4, car.y - fy * 3.4, owner)


def orbit_points(car, count, t):
    """Where the `count` pucks circling a car are at time t."""
    return [(car.x + ORBIT_RADIUS * math.cos(t * ORBIT_SPIN + k * 2 * math.pi / 3),
             car.y + ORBIT_RADIUS * math.sin(t * ORBIT_SPIN + k * 2 * math.pi / 3)) for k in range(count)]


def _blocked(world, x, y):
    return world.in_building(x, y) or not world.in_bounds(x, y)


def step_shot(shot, world, dt, rivals):
    """Move a shot one step. rivals = [(player index, car)] it may home on or hit (its owner is left out by the caller
    while the shot is new). Returns "fly", "gone" (worn out, or broke on a wall) or ("hit", player index)."""
    shot.age += dt
    shot.life -= dt
    if shot.life <= 0.0:
        return "gone"
    if shot.kind == "seeker" and rivals:
        _i, target = min(rivals, key=lambda ic: (ic[1].x - shot.x) ** 2 + (ic[1].y - shot.y) ** 2)
        want = math.atan2(target.y - shot.y, target.x - shot.x)
        have = math.atan2(shot.vy, shot.vx)
        turn = (want - have + math.pi) % (2 * math.pi) - math.pi
        have += max(-SEEKER_TURN * dt, min(SEEKER_TURN * dt, turn))
        shot.vx, shot.vy = math.cos(have) * SEEKER_SPEED, math.sin(have) * SEEKER_SPEED
    nx, ny = shot.x + shot.vx * dt, shot.y + shot.vy * dt
    if _blocked(world, nx, ny):
        if shot.kind != "puck" or shot.bounces >= PUCK_BOUNCES:
            return "gone"
        shot.bounces += 1
        flip_x, flip_y = _blocked(world, nx, shot.y), _blocked(world, shot.x, ny)
        if flip_x:
            shot.vx = -shot.vx
        if flip_y:
            shot.vy = -shot.vy
        if not flip_x and not flip_y:                # straight into a corner: back the way it came
            shot.vx, shot.vy = -shot.vx, -shot.vy
        nx, ny = shot.x + shot.vx * dt, shot.y + shot.vy * dt
        if _blocked(world, nx, ny):
            return "gone"
    shot.x, shot.y = nx, ny
    for i, car in rivals:
        if (car.x - shot.x) ** 2 + (car.y - shot.y) ** 2 < SHOT_HIT * SHOT_HIT:
            return ("hit", i)
    return "fly"
