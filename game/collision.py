"""Collision helpers: car vs world (slides along walls) and car vs car."""
import math


BOUNDS_MARGIN = 12.0   # how far past the map edge a car may drive
BOUNCE = 0.2           # fraction of the blocked velocity that bounces back
SCRAPE = 0.97          # speed kept along a wall while scraping it
BOUNCE_FULL = 0.3      # bounce when blocked on both axes
CAR_RADIUS = 1.15      # each car is two circles this big, 2 m apart
RESTITUTION = 0.35


def _sample_points(car, thorough):
    c = car.corners()
    if not thorough:
        return c
    pts = list(c)
    for i in range(4):
        a, b = c[i], c[(i + 1) % 4]
        pts.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    pts.append((car.x, car.y))
    return pts


def _hits_static(car, world, thorough=False):
    """Buildings and the map edge only (props are pushed out separately)."""
    for x, y in _sample_points(car, thorough):
        if world.in_building(x, y) or not world.in_bounds(x, y, margin=BOUNDS_MARGIN):
            return True
    return False


def car_hits_world(car, world, thorough=False):
    """True if the car overlaps a building, a tree/lamp post, or is past the map edge.

    thorough=True also tests edge midpoints and the centre (use for the player).
    """
    return _hits_static(car, world, thorough) or _hits_prop(car, world)


def _push_out_props(car, world):
    """Push the car off any tree trunk or lamp post it overlaps, and bounce the velocity going into it.

    Pushing out (instead of undoing the move) matters: steering can rotate the car's side into a trunk,
    and undoing only the position would leave it pinned there. Returns the impact speed (m/s).
    """
    props = world.props_near(car.x, car.y, 4.0) if hasattr(world, "props_near") else ()
    if not props:
        return 0.0
    hl, hw = car.length / 2, car.width / 2
    impact = 0.0
    for _ in range(2):
        moved = False
        fx, fy = car.forward
        rx, ry = car.right
        for p in props:
            dx, dy = p["x"] - car.x, p["y"] - car.y
            a, b = dx * fx + dy * fy, dx * rx + dy * ry          # prop centre in car coordinates
            qa, qb = max(-hl, min(hl, a)), max(-hw, min(hw, b))  # nearest point of the car's rectangle
            ea, eb = a - qa, b - qb
            d = math.hypot(ea, eb)
            cr = p["cr"]
            if d >= cr:
                continue
            if d < 1e-6:                     # trunk centre inside the car: leave by the nearest side
                if hw - abs(b) < hl - abs(a):
                    na, nb, push = 0.0, math.copysign(1.0, b or 1.0), hw - abs(b) + cr
                else:
                    na, nb, push = math.copysign(1.0, a or 1.0), 0.0, hl - abs(a) + cr
            else:
                na, nb, push = ea / d, eb / d, cr - d
            wx, wy = fx * na + rx * nb, fy * na + ry * nb         # world direction from car towards prop
            car.x -= wx * push
            car.y -= wy * push
            vn = car.vx * wx + car.vy * wy
            if vn > 0:
                car.vx -= (1 + BOUNCE) * vn * wx
                car.vy -= (1 + BOUNCE) * vn * wy
                impact = max(impact, vn)
            moved = True
        if not moved:
            break
    return impact


def _hits_prop(car, world):
    """True if a tree trunk or lamp post (a small circle) overlaps the car's rectangle."""
    props = world.props_near(car.x, car.y, 4.0) if hasattr(world, "props_near") else ()
    if not props:
        return False
    fx, fy = car.forward
    rx, ry = car.right
    hl, hw = car.length / 2, car.width / 2
    for p in props:
        dx, dy = p["x"] - car.x, p["y"] - car.y
        a, b = dx * fx + dy * fy, dx * rx + dy * ry           # prop centre in car coordinates
        qa, qb = max(-hl, min(hl, a)), max(-hw, min(hw, b))   # nearest point of the rectangle
        if (a - qa) ** 2 + (b - qb) ** 2 < p["cr"] ** 2:
            return True
    return False


def move_and_slide(car, world, prev_x, prev_y, thorough=False):
    """Resolve a move that already happened (car.x/y is the new position).

    Tries to keep the movement along one axis so the car scrapes along a wall instead of
    stopping dead. Returns the impact speed in m/s (0.0 if nothing was hit).
    """
    prop_impact = _push_out_props(car, world)
    if not _hits_static(car, world, thorough):
        return prop_impact
    nx, ny = car.x, car.y
    vx, vy = car.vx, car.vy

    car.x, car.y = nx, prev_y                    # keep the x movement, undo y
    if not _hits_static(car, world, thorough):
        car.vy = -vy * BOUNCE
        car.vx = vx * SCRAPE
        return abs(vy)

    car.x, car.y = prev_x, ny                    # keep the y movement, undo x
    if not _hits_static(car, world, thorough):
        car.vx = -vx * BOUNCE
        car.vy = vy * SCRAPE
        return abs(vx)

    car.x, car.y = prev_x, prev_y                # blocked both ways: go back
    impact = math.hypot(vx, vy)
    if _hits_static(car, world, thorough):
        # already wedged (e.g. rotated into a wall): let the car crawl out instead of freezing
        car.x, car.y = nx, ny
        car.vx, car.vy = vx * 0.5, vy * 0.5
        return 0.0
    car.vx, car.vy = -vx * BOUNCE_FULL, -vy * BOUNCE_FULL
    return impact


def _radius(car):
    return car.width / 2 + 0.25


def _circles(car):
    """Two circles that cover the car: centres this far along the car from its middle."""
    fx, fy = car.forward
    off = max(0.4, car.length / 2 - _radius(car))
    return ((car.x + fx * off, car.y + fy * off), (car.x - fx * off, car.y - fy * off))


LEVEL_GAP = 2.6        # cars whose heights differ by more than this are on different levels (overpass vs road below)


SLOPE_PULL = 4.0               # m/s^2 per unit of slope (real gravity would be 9.8: arcade-soft)


def settle_height(car, world, dt):
    """Ease the car onto the road surface under it: the ground, or an overpass deck/ramp."""
    target = world.height_at(car.x, car.y, car.z) if hasattr(world, "height_at") else 0.0
    car.z += (target - car.z) * min(1.0, 12.0 * dt)
    terrain = getattr(world, "terrain", None)
    if terrain is not None and hasattr(car, "vx") and abs(car.z - terrain.height(car.x, car.y)) < 0.5:
        nx, ny, nz = terrain.normal(car.x, car.y)               # downhill pull: uphill slows, downhill speeds up
        k = SLOPE_PULL * dt / max(nz, 0.2)
        car.vx += nx * k
        car.vy += ny * k


def collide_cars(a, b):
    """Push two overlapping cars apart and exchange momentum.

    Returns the impact speed (m/s along the contact normal), or 0.0 if they don't touch.
    """
    if abs(a.x - b.x) > 6.0 or abs(a.y - b.y) > 6.0 or abs(getattr(a, "z", 0.0) - getattr(b, "z", 0.0)) > LEVEL_GAP:
        return 0.0
    best = None
    limit = _radius(a) + _radius(b)
    for ax, ay in _circles(a):
        for bx, by in _circles(b):
            dx, dy = ax - bx, ay - by
            d2 = dx * dx + dy * dy
            if d2 < limit * limit:
                d = math.sqrt(d2)
                pen = limit - d
                if best is None or pen > best[0]:
                    if d < 1e-6:
                        best = (pen, 1.0, 0.0)
                    else:
                        best = (pen, dx / d, dy / d)
    if best is None:
        return 0.0
    pen, nx, ny = best                           # normal points from b towards a
    ma, mb = a.mass, b.mass
    tot = ma + mb
    a.x += nx * pen * mb / tot
    a.y += ny * pen * mb / tot
    b.x -= nx * pen * ma / tot
    b.y -= ny * pen * ma / tot
    rel = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny
    if rel >= 0:
        return 0.0                               # already separating
    j = -(1.0 + RESTITUTION) * rel / (1.0 / ma + 1.0 / mb)
    a.vx += j * nx / ma
    a.vy += j * ny / ma
    b.vx -= j * nx / mb
    b.vy -= j * ny / mb
    return -rel
