"""AI drivers: civilian traffic that follows the road graph, and police that chase the player.

Both kinds drive the same Car physics as the player. The drivers only set three controls
(throttle, brake, steer); they run about 20 times a second, the physics runs at 60 Hz.
"""
import math

from .car import Car

PAL_POLICE = {"body": (236, 236, 240), "lower": (22, 22, 30), "glass": (50, 70, 120),
              "tail": (232, 40, 40), "roof": (22, 22, 30), "lightbar": True}


def _pal(body):
    return {"body": body, "lower": (30, 30, 40), "glass": (70, 100, 170),
            "tail": (200, 40, 40), "roof": body, "lightbar": False}


PAL_TRAFFIC = [_pal(c) for c in ((196, 60, 60), (60, 120, 200), (80, 160, 90), (200, 200, 205),
                                 (70, 70, 80), (210, 130, 50), (150, 90, 170), (120, 190, 190))]


def wrap(a):
    """Wrap an angle to (-pi, pi]."""
    return (a + math.pi) % (2 * math.pi) - math.pi


class AICar(Car):
    def __init__(self, kind, palette, x, y, heading):
        super().__init__(x, y, heading)
        self.kind = kind                 # "traffic" or "police"
        self.palette = palette
        self.mass = 1.2 if kind == "police" else 1.0
        self.throttle = False
        self.brake = False
        self.steer = 0.0
        self.edge = None                 # traffic: current road-graph edge
        self.nxt = None                  # traffic: edge after this one
        self.route = []                  # police: node ids still to visit
        self.path_t = 0.0                # police: seconds until the route is recomputed
        self.stuck = 0.0
        self.wait = 0.0
        self.reverse_t = 0.0
        self.rev_steer = 1.0
        self.stand_t = 0.0               # police: time spent standing down
        self.dead = False                # flagged for removal
        self.pace = 1.0                  # traffic: fraction of the posted limit this driver aims for
        # traffic at junctions (game/junctions.py)
        self.jn_node = None              # the junction this car is approaching
        self.jn_pass = None              # the junction it has been cleared to drive through
        self.jn_hold = False             # held at a line this tick (red light, stop sign, giving way)
        self.jn_stopped = False          # has made its full stop at the stop sign
        self.jn_stop_t = 0.0             # seconds standing at the stop line
        self.jn_wait = 0.0               # seconds waiting at the line for a gap


def steer_to(car, tx, ty, gain=2.0):
    """Steering (-1..1) towards a point, plus the heading error in radians."""
    err = wrap(math.atan2(ty - car.y, tx - car.x) - car.heading)
    return max(-1.0, min(1.0, err * gain)), err


def speed_control(car, v_t):
    """Set throttle/brake to hold target speed v_t. Never brakes below 1 m/s (that would reverse)."""
    vf = car.forward_speed()
    car.throttle = car.brake = False
    if v_t < 0.3:
        car.brake = vf > 1.0
    elif vf < v_t - 0.4:
        car.throttle = True
    elif vf > v_t + 1.2:
        car.brake = vf > 1.0


def clear_line(world, x0, y0, x1, y1, step=4.0):
    """True if no building lies on the straight line between two points."""
    d = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(d / step))
    for i in range(1, n):
        t = i / n
        if world.in_building(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t):
            return False
    return True


def obstacle_limit(car, others, look=16.0, width=2.3):
    """Highest safe speed given cars ahead in a narrow cone (1e9 if the road is clear)."""
    fx, fy = car.forward
    rx, ry = car.right
    limit = 1e9
    for o in others:
        if o is car:
            continue
        dx, dy = o.x - car.x, o.y - car.y
        f = dx * fx + dy * fy
        if f < 0.5 or f > look:
            continue
        if abs(dx * rx + dy * ry) > width:
            continue
        v = max(0.0, f - 4.4) * 1.3 + max(0.0, o.vx * fx + o.vy * fy)
        if v < limit:
            limit = v
    return limit


def drive_traffic(car, graph, others, rng, dt, junctions=None, now=0.0):
    """Follow the right-hand lane of the current edge, slow for corners, cars ahead and junction rules.

    junctions (game.junctions.Junctions, optional) adds traffic lights, stop signs and right of way; now is the
    game clock that the signals run on.

    Smooth feel: steer is lerped towards the target each tick (no instant snapping),
    and the target speed is low-pass filtered so acceleration/braking feels gradual.
    """
    if car.edge is None:
        car.dead = True
        return
    for _ in range(2):
        e = graph.edges[car.edge]
        lx, ly = e.ax - e.dy * e.lane, e.ay + e.dx * e.lane       # start of the lane line
        px, py = car.x - lx, car.y - ly
        s = px * e.dx + py * e.dy                                  # distance along the lane
        lat = -px * e.dy + py * e.dx                               # sideways offset (right is +)
        if s > e.length - 1.0 and car.nxt is not None:
            car.edge = car.nxt
            car.nxt = graph.choose_next(car.edge, rng)
            continue
        break
    if abs(lat) > 12.0 or s < -15.0:
        car.dead = True                                            # knocked far off its road
        return

    look = max(5.0, min(12.0, 4.0 + car.speed * 0.55))
    st = s + look
    if st <= e.length or car.nxt is None:
        t = min(st, e.length)
        tx, ty = lx + e.dx * t, ly + e.dy * t
    else:
        n = graph.edges[car.nxt]
        over = min(st - e.length, n.length)
        tx = n.ax - n.dy * n.lane + n.dx * over
        ty = n.ay + n.dx * n.lane + n.dy * over

    v_t = e.cruise * car.pace
    if car.nxt is not None:
        n = graph.edges[car.nxt]
        ang = abs(wrap(math.atan2(n.dy, n.dx) - math.atan2(e.dy, e.dx)))
        vc = max(4.5, min(n.cruise * car.pace, v_t * (1.0 - 1.2 * ang / math.pi)))
        v_t = min(v_t, math.sqrt(vc * vc + 2 * 7.0 * max(0.0, e.length - s - 2.0)))

    raw_steer, err = steer_to(car, tx, ty)
    if abs(err) > 1.0:
        v_t = min(v_t, 5.0)
    v_obs = obstacle_limit(car, others)
    v_t = min(v_t, v_obs)
    v_jn =junctions.limit(car, car.edge, s, others, now, dt) if junctions is not None else 1e9
    v_t = min(v_t, v_jn)

    # --- smooth steering: lerp towards target, faster at speed for stability ---
    steer_rate = 4.0 + car.speed * 0.15   # rad/s equivalent (higher = snappier)
    max_delta   = steer_rate * dt
    delta       = max(-max_delta, min(max_delta, raw_steer - car.steer))
    car.steer   = max(-1.0, min(1.0, car.steer + delta))

    # --- smooth speed target: low-pass so sudden obstacles don't snap controls ---
    if not hasattr(car, '_v_smooth'):
        car._v_smooth = v_t
    alpha = 1.0 - math.exp(-6.0 * dt)   # ~0.18 per tick at 30 Hz → about 0.5 s to settle
    car._v_smooth += (v_t - car._v_smooth) * alpha
    # stopping at a junction line or behind a stopped car is not smoothed, or followers rear-end the queue
    speed_control(car, min(car._v_smooth, v_jn, v_obs))

    if car.speed < 0.6 and v_t > 1.5:
        car.stuck += dt
    else:
        car.stuck = max(0.0, car.stuck - dt)
    held = car.jn_hold                 # waiting at a red light or a stop sign is not a jam
    if not held:                                          # (held: the jam timer pauses, it does not drain)
        car.wait = car.wait + dt if v_t < 0.5 else max(0.0, car.wait - dt)
    if car.stuck > 6.0 or car.wait > 20.0:
        car.dead = True


def drive_police(car, graph, world, player, others, dt, rng, active, v_cap):
    """Chase the player: straight at him when there is a clear view, otherwise along the road graph."""
    if not active:                                                 # heat is 0: stand down
        car.throttle, car.steer = False, 0.0
        car.brake = car.forward_speed() > 1.0
        return
    if car.reverse_t > 0.0:                                        # backing out of a jam
        car.reverse_t -= dt
        car.throttle, car.brake, car.steer = False, True, car.rev_steer
        if car.reverse_t <= 0.0:
            car.stuck = 0.0
        return

    dx, dy = player.x - car.x, player.y - car.y
    dist = math.hypot(dx, dy)
    if dist < 70.0 and clear_line(world, car.x, car.y, player.x, player.y):
        lead = min(0.6, dist / 40.0)
        tx, ty = player.x + player.vx * lead, player.y + player.vy * lead
        v_t = v_cap
        if dist < 14.0:
            v_t = max(player.speed + 4.0, 7.0)                     # stay glued to his bumper
        car.path_t = 0.0                                           # plan a fresh route if the view is lost
    else:
        car.path_t -= dt
        if car.path_t <= 0.0 or not car.route:
            car.path_t = 1.0 + rng.random() * 0.4
            # moving: keep going forward; nearly stopped: free to turn around
            src = graph.nearest_node(car.x, car.y, 70.0, car.heading if car.speed > 4.0 else None)
            dst = graph.nearest_node(player.x, player.y, 90.0)
            path = graph.shortest_path(src, dst) if src is not None and dst is not None else None
            car.route = path or []
        nodes = graph.nodes
        while car.route and math.hypot(nodes[car.route[0]][0] - car.x, nodes[car.route[0]][1] - car.y) < 7.0:
            car.route.pop(0)
        if car.route:
            tx, ty = nodes[car.route[0]]
            v_t = v_cap
            if len(car.route) > 1:
                nx, ny = nodes[car.route[1]]
                ang = abs(wrap(math.atan2(ny - ty, nx - tx) - math.atan2(ty - car.y, tx - car.x)))
                vc = max(7.0, v_cap * (1.0 - 1.1 * ang / math.pi))
                d = math.hypot(tx - car.x, ty - car.y)
                v_t = min(v_t, math.sqrt(vc * vc + 2 * 9.0 * max(0.0, d - 4.0)))
        else:
            tx, ty, v_t = player.x, player.y, 14.0

    if player.speed < 5.0 and dist < 25.0:                         # box him in, don't ram a parked car
        v_t = min(v_t, max(0.0, dist - 5.5))

    steer, err = steer_to(car, tx, ty)
    if abs(err) > 1.0:
        v_t = min(v_t, 6.0)
    v_t = min(v_t, obstacle_limit(car, others, look=12.0, width=1.7))
    car.steer = steer
    speed_control(car, v_t)

    if car.speed < 1.0 and v_t > 4.0:
        car.stuck += dt
    else:
        car.stuck = max(0.0, car.stuck - dt)
    if car.stuck > 1.5:
        car.reverse_t = 1.2
        car.rev_steer = -1.0 if steer >= 0 else 1.0
        car.stuck = 0.0
