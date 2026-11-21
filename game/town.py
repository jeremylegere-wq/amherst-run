"""The living town (M4): civilian traffic, police, the wanted level and player damage.

Rules in short:
  * Hitting a civilian car adds heat (0.6 per hit). Heat 0..4 decides how many police chase (1..4).
  * Police spawn on roads 70-120 m away, preferring the side behind the player.
  * Stay out of sight for a few seconds and the heat drains; at zero the police stand down.
  * Police that stay within 8 m of a (nearly) stopped player for 2.5 s make a BUSTED arrest.
  * Damage builds up from impacts and slows the car down; at 100 the car is WRECKED.
  * After BUSTED or WRECKED the game resets the player (Game asks via consume_reset()).
"""
import math
import random

from .ai import AICar, PAL_POLICE, PAL_TRAFFIC, clear_line, drive_police, drive_traffic
from .junctions import Junctions
from .collision import collide_cars, move_and_slide, settle_height
from .roadgraph import RoadGraph

CONTROL_DT = 0.05            # AI decisions per second = 20
MANAGE_DT = 0.25             # spawn / despawn checks
TRAFFIC_DESPAWN = 260.0
POLICE_DESPAWN = 320.0
MAX_HEAT = 4.0
PACE_MIN, PACE_MAX = 0.88, 1.06   # civilian drivers aim for this fraction of the posted limit
SIGHT_RANGE = 140.0          # police see the player this far along a clear line
HIT_HEAT = 0.6
HIT_MIN_IMPACT = 4.0         # m/s (~14 km/h): lighter taps on civilian cars do not bring the police
LOSE_GRACE = 8.0             # seconds unseen before heat starts to drain
HEAT_DECAY = 0.15            # heat per second once draining
BUSTED_RANGE = 8.0
BUSTED_SPEED = 4.0
BUSTED_TIME = 2.5
RESET_DELAY = 3.5
DAMAGE_PER_MS = 1.2          # damage per m/s of impact above the free 3 m/s
TRAFFIC_W = {"main": 3.0, "side": 2.0, "lane": 0.3}
TRAFFIC_AREA = 200.0         # metres: road length within this radius sets how busy the streets are
DENSE_ROAD_M = 4400.0        # this much road nearby (downtown's grid) gets the full traffic target
MIN_TRAFFIC = 3              # even a quiet rural road sees the odd car
SPAWN_MIN, SPAWN_MAX = 150.0, 230.0   # new cars appear this far away, so they do not pop into view
POLICE_W = {"main": 3.0, "side": 2.0, "lane": 0.0}


class Town:
    def __init__(self, world, graph=None, seed=1, traffic=16, cops=True):
        self.world = world
        self.graph = graph or RoadGraph(world.roads)
        self.junctions = Junctions(self.graph, getattr(world, "marks", ()))   # lights, stop signs, right of way
        self.rng = random.Random(seed)
        self.traffic_target = traffic
        self.extra = []                   # more human players (split screen); traffic is kept around all of them
        self._density = {}                # 100 m cell -> how busy its streets are (local_target)
        self.cops = cops                  # False = cop-free mode: no police, no heat, no busting
        self.reset()

    def reset(self):
        self.cars = []
        self.time = 0.0
        self.heat = 0.0
        self.damage = 0.0
        self.state = "playing"        # playing / busted / wrecked
        self.state_t = 0.0
        self.busted_t = 0.0
        self.hit_cd = 0.0
        self.spawn_cd = 0.0
        self.lose_t = 0.0
        self.seen = False
        self.events = []
        self._ctl_acc = 0.0
        self._mng_acc = 0.0
        self._filled = False
        self._reset_flag = False

    def consume_reset(self):
        flag, self._reset_flag = self._reset_flag, False
        return flag

    @property
    def police(self):
        return [c for c in self.cars if c.kind == "police"]

    @property
    def stars(self):
        return int(math.ceil(self.heat - 1e-9))

    def set_cops(self, on):
        """Switch cop-free mode off/on. Turning cops off stands the police down at once."""
        self.cops = bool(on)
        if not self.cops:
            self.heat = 0.0
            self.busted_t = 0.0
            self.cars = [c for c in self.cars if c.kind != "police"]

    def add_heat(self, amount):
        if not self.cops:
            return
        self.heat = max(0.0, min(MAX_HEAT, self.heat + amount))
        self.lose_t = 0.0

    def player_power(self):
        return 1.0 - 0.35 * min(1.0, self.damage / 100.0)

    def _hurt(self, impact):
        if self.state == "playing":
            self.damage = min(100.0, self.damage + max(0.0, impact - 3.0) * DAMAGE_PER_MS)

    # ------------------------------------------------------------------ update
    def update(self, dt, player, wall_impact=0.0):
        self.time += dt
        self.hit_cd = max(0.0, self.hit_cd - dt)
        self.spawn_cd = max(0.0, self.spawn_cd - dt)
        if not self._filled:
            self._manage(player, fill=True)
            self._filled = True
        self._mng_acc += dt
        if self._mng_acc >= MANAGE_DT:
            self._mng_acc = 0.0
            self._manage(player)
        self._ctl_acc += dt
        if self._ctl_acc >= CONTROL_DT:
            step, self._ctl_acc = self._ctl_acc, 0.0
            self._control(step, player)

        if wall_impact > 0.0:
            self._hurt(wall_impact)

        world = self.world
        for c in self.cars:
            px, py = c.x, c.y
            on_road = True if c.kind == "traffic" else world.on_road(c.x, c.y)
            c.update(dt, c.throttle, c.brake, c.steer, False, on_road)
            move_and_slide(c, world, px, py)
            settle_height(c, world, dt)

        everyone = self.cars + [player] + self.extra
        for i in range(len(everyone)):
            a = everyone[i]
            for j in range(i + 1, len(everyone)):
                b = everyone[j]
                if abs(a.x - b.x) > 6.0 or abs(a.y - b.y) > 6.0:
                    continue
                imp = collide_cars(a, b)
                if imp > 0.8:
                    self._on_crash(a, b, imp, player)

        self._update_state(dt, player)

    def _on_crash(self, a, b, imp, player):
        if a is not player and b is not player:
            return
        other = b if a is player else a
        if self.state != "playing":
            return
        self._hurt(imp)
        if other.kind == "traffic" and imp > HIT_MIN_IMPACT and self.hit_cd <= 0.0:
            self.add_heat(HIT_HEAT)
            self.hit_cd = 1.5
            self.events.append("hit")
            del self.events[:-20]

    def _update_state(self, dt, player):
        if self.state != "playing":
            self.state_t += dt
            if self.state_t > RESET_DELAY:
                self._reset_flag = True
            return
        if self.heat > 0.0:
            if self.seen:
                self.lose_t = 0.0
            else:
                self.lose_t += dt
            if self.lose_t > LOSE_GRACE:
                self.heat = max(0.0, self.heat - HEAT_DECAY * dt)
            near = any(math.hypot(c.x - player.x, c.y - player.y) < BUSTED_RANGE for c in self.police)
            if near and player.speed < BUSTED_SPEED:
                self.busted_t += dt
            else:
                self.busted_t = max(0.0, self.busted_t - 1.5 * dt)
            if self.busted_t > BUSTED_TIME:
                self._end("busted")
        else:
            self.busted_t = 0.0
        if self.damage >= 100.0:
            self._end("wrecked")

    def _end(self, state):
        self.state, self.state_t = state, 0.0
        self.events.append(state)

    # ----------------------------------------------------------------- control
    def _control(self, dt, player):
        g, rng = self.graph, self.rng
        civ_others = self.cars + [player] + self.extra
        active = self.heat > 0.0 and self.state == "playing"
        v_cap = 26.0 + 2.5 * min(4, self.stars)
        for c in self.cars:
            if c.kind == "traffic":
                drive_traffic(c, g, civ_others, rng, dt, self.junctions, self.time)
            else:
                drive_police(c, g, self.world, player, self.cars, dt, rng, active, v_cap)

    # --------------------------------------------------------- spawn / despawn
    def _manage(self, player, fill=False):
        g = self.graph
        if not g.edges:
            return
        fx, fy = player.forward
        keep = []
        for c in self.cars:
            dx, dy = c.x - player.x, c.y - player.y
            d = math.hypot(dx, dy)
            if c.kind == "traffic":
                d = min([d] + [math.hypot(c.x - p.x, c.y - p.y) for p in self.extra])
                gone = c.dead or d > TRAFFIC_DESPAWN
            else:
                gone = c.dead or d > POLICE_DESPAWN
                if self.heat <= 0.0 and self.state == "playing":
                    c.stand_t += MANAGE_DT
                    behind = dx * fx + dy * fy < 0
                    gone = gone or d > 60.0 or (behind and d > 25.0) or c.stand_t > 6.0
            if not gone:
                keep.append(c)
        self.cars = keep

        # are the police watching the player?
        self.seen = any(
            (d := math.hypot(c.x - player.x, c.y - player.y)) < 25.0
            or (d < SIGHT_RANGE and clear_line(self.world, c.x, c.y, player.x, player.y))
            for c in self.police)

        n = sum(1 for c in self.cars if c.kind == "traffic")
        budget = self.local_target(player) - n
        tries = 0
        while budget > 0 and tries < (40 if fill else 8):
            tries += 1
            focus = self.rng.choice([player] + self.extra) if self.extra else player
            if self._spawn_traffic(focus, 30.0 if fill else SPAWN_MIN, 190.0 if fill else SPAWN_MAX):
                budget -= 1

        if self.state == "playing" and self.heat > 0.0 and self.spawn_cd <= 0.0 \
                and len(self.police) < min(4, self.stars):
            if self._spawn_police(player):
                self.spawn_cd = 2.5

    def local_target(self, player):
        """How many civilian cars to keep around: the full target where streets are dense (downtown), fewer where
        there is little road (the rural loop), worked out from the road length within TRAFFIC_AREA metres."""
        if self.traffic_target <= 0:
            return 0
        cell = (int(player.x // 100), int(player.y // 100))
        if cell not in self._density:
            g = self.graph
            total = sum(g.edges[i].length for i in g.edges_near(player.x, player.y, TRAFFIC_AREA)
                        if g.edges[i].rtype != "lane")
            self._density[cell] = min(1.0, total / DENSE_ROAD_M)
        return max(MIN_TRAFFIC, round(self.traffic_target * self._density[cell]))

    def _occupied(self, x, y, player):
        if self.world.in_building(x, y):
            return True
        for c in self.cars + [player] + self.extra:
            if abs(c.x - x) < 9.0 and abs(c.y - y) < 9.0:
                return True
        return False

    def _spawn_traffic(self, player, rmin, rmax):
        g = self.graph
        pick = g.random_spawn(player.x, player.y, rmin, rmax, self.rng, TRAFFIC_W)
        if pick is None:
            return False
        eid, s = pick
        x, y, h = g.lane_point(eid, s)
        if self._occupied(x, y, player) or self.world.height_at(x, y, 999.0) - self.world.ground(x, y) > 0.3:
            return False                                       # (not on an overpass deck or ramp: start on the ground)
        c = AICar("traffic", self.rng.choice(PAL_TRAFFIC), x, y, h)
        c.z = self.world.height_at(x, y, 0.0)
        c.edge = eid
        c.nxt = g.choose_next(eid, self.rng)
        c.pace = self.rng.uniform(PACE_MIN, PACE_MAX)       # law-abiding, but nobody drives exactly the limit
        v = g.edges[eid].cruise * c.pace
        c.vx, c.vy = math.cos(h) * v, math.sin(h) * v
        self.cars.append(c)
        return True

    def _spawn_police(self, player):
        g = self.graph
        fx, fy = player.forward
        choice = None
        for _ in range(6):
            pick = g.random_spawn(player.x, player.y, 70.0, 120.0, self.rng, POLICE_W)
            if pick is None:
                continue
            x, y, h = g.lane_point(*pick)
            if self._occupied(x, y, player):
                continue
            choice = (x, y, h)
            if (x - player.x) * fx + (y - player.y) * fy < 0:       # behind the player: take it
                break
        if choice is None:
            return False
        x, y, h = choice
        c = AICar("police", PAL_POLICE, x, y, h)
        c.z = self.world.height_at(x, y, 0.0)
        c.path_t = self.rng.random()                                  # stagger route planning
        c.vx, c.vy = math.cos(h) * 10.0, math.sin(h) * 10.0
        self.cars.append(c)
        return True
