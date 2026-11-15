"""Missions (M5): jobs you start by driving into a glowing marker at a landmark.

Hubs come from building roles set in the landmark file (and Victoria Square):
  deliveries (post office)  -> Parcel Run: deliver 1-3 parcels to street addresses before time runs out.
                               Stop (under 6 m/s) at each address. Some parcels are fragile.
  getaway (banks)           -> Getaway: you get three stars; lose the police before the clock runs out.
  tour (square, museum)     -> Heritage Tour: checkpoint race past the town's landmarks.
  courthouse                -> Pay your fine: clears your wanted level for $100 a star.
Hubs and delivery addresses only trigger when you pull up and (nearly) stop in the marker.
Jobs pay cash (plus a time bonus). You can't take a job while wanted. Getting busted costs $100.
Targets come from the road graph, so this works on any map.
"""
import math
import random

from .roadgraph import NO_AI_SERVICE

HUB_STYLE = {   # role -> (marker colour, title)
    "deliveries": ((255, 150, 30), "Parcel Run"),
    "getaway": ((236, 52, 52), "Getaway"),
    "tour": ((80, 220, 120), "Heritage Tour"),
    "courthouse": ((80, 150, 255), "Pay Fines"),
}
ROLE_ALIASES = {"museum": "tour"}
HUB_RADIUS = 5.0            # hubs sit at the kerb; pull up and stop in them
DROP_RADIUS = 7.0
CHECK_RADIUS = 10.0
DROP_SPEED = 6.0             # m/s: you have to (nearly) stop at a delivery address
FINE_PER_STAR = 100
BUSTED_FINE = 100
BANNER_TIME = 3.5
CRUISE = 12.0                # m/s used to size delivery time limits (a careful autopilot has ~15-25% spare)
FRAGILE_DAMAGE = 25.0
TOUR_RADIUS = 900.0          # Heritage Tour checkpoints stay within this distance of the start
SPAWN_W = {"main": 3.0, "side": 2.0, "lane": 0.2}


class Target:
    __slots__ = ("x", "y", "radius", "label", "stop")

    def __init__(self, x, y, radius, label, stop=False):
        self.x, self.y, self.radius, self.label, self.stop = x, y, radius, label, stop


class Hub:
    __slots__ = ("x", "y", "role", "label", "colour", "title")

    def __init__(self, x, y, role, label):
        self.x, self.y, self.role, self.label = x, y, role, label
        self.colour, self.title = HUB_STYLE[role]


class Mission:
    def __init__(self, kind, title, colour, targets, time_limit, reward, fragile=False):
        self.kind, self.title, self.colour = kind, title, colour
        self.targets, self.stage = targets, 0
        self.time_limit = self.time_left = time_limit
        self.reward, self.fragile = reward, fragile
        self.elapsed = 0.0
        self.start_damage = 0.0


def _centroid(pts):
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


class MissionManager:
    def __init__(self, world, town, seed=1):
        self.world, self.town = world, town
        self.graph = town.graph
        self.rng = random.Random(seed)
        self.cash = 0
        self.completed = 0
        self.mission = None
        self.banner = None               # (text, colour, seconds left)
        self._inside = None              # hub the player is sitting in (must leave before it re-triggers)
        self._prev_state = "playing"
        self.all_hubs = self._find_hubs()

    @property
    def hubs(self):
        """Hubs in use: with the cops off there are no getaways and no fines to pay."""
        if self.town.cops:
            return self.all_hubs
        return [h for h in self.all_hubs if h.role not in ("getaway", "courthouse")]

    # ------------------------------------------------------------------ setup
    def _curb_point(self, x, y, kerb=False):
        """Road point nearest to (x, y), nudged towards it: into the near lane, or right to the kerb."""
        best = None
        for r in self.world.roads:
            if r.get("service") in NO_AI_SERVICE:
                continue                       # never put a beacon in a driveway or parking aisle
            hw = r["width"] / 2.0
            pts = r["points"]
            for a, b in zip(pts, pts[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                L2 = dx * dx + dy * dy
                if L2 == 0:
                    continue
                t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
                qx, qy = a[0] + t * dx, a[1] + t * dy
                d = math.hypot(x - qx, y - qy) + (30.0 if r["type"] == "lane" else 0.0)
                if best is None or d < best[0]:
                    best = (d, qx, qy, hw, math.hypot(x - qx, y - qy))
        if best is None:
            return x, y
        _d, qx, qy, hw, real = best
        if real > 1e-6:
            off = min(real, max(0.0, hw - 0.3) if kerb else hw * 0.5)
            qx += (x - qx) / real * off
            qy += (y - qy) / real * off
        return qx, qy

    def _find_hubs(self):
        hubs = []
        items = [(b.get("role"), b.get("label", ""), b["points"]) for b in self.world.buildings if b.get("role")]
        items += [("tour", p.get("label", "Square"), p["points"]) for p in getattr(self.world, "parks", ())
                  if p.get("landmark") == "square"]
        for role, label, pts in items:
            role = ROLE_ALIASES.get(role, role)
            if role not in HUB_STYLE:
                continue
            x, y = self._curb_point(*_centroid(pts), kerb=True)
            if any(math.hypot(h.x - x, h.y - y) < 4.0 for h in hubs):
                continue
            hubs.append(Hub(x, y, role, label))
        return hubs

    # -------------------------------------------------------------- helpers
    def _say(self, text, colour=(252, 222, 48)):
        self.banner = (text, colour, BANNER_TIME)

    def _route_len(self, a, b):
        g = self.graph
        na, nb = g.nearest_node(a[0], a[1], 120.0), g.nearest_node(b[0], b[1], 120.0)
        path = g.shortest_path(na, nb) if na is not None and nb is not None else None
        if not path:
            return math.hypot(b[0] - a[0], b[1] - a[1]) * 1.4
        pts = [a] + [g.nodes[n] for n in path] + [b]
        return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))

    def street_name(self, x, y):
        best = None
        for r in self.world.roads:
            name = r.get("name")
            if not name:
                continue
            for a, b in zip(r["points"], r["points"][1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                L2 = dx * dx + dy * dy or 1.0
                t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
                d = math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
                if best is None or d < best[0]:
                    best = (d, name)
        return best[1] if best and best[0] < 40 else "the address"

    def address(self, x, y):
        """The civic address for a drop point: the real house number on that street from the Nova Scotia Civic
        Address File when data/addresses.json has one within 45 m, else a made-up one (distance along the street,
        odd/even by side, about 9 m per lot)."""
        best = None
        for r in self.world.roads:
            name = r.get("name")
            if not name:
                continue
            along = 0.0
            for a, b in zip(r["points"], r["points"][1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                seg = math.hypot(dx, dy)
                L2 = dx * dx + dy * dy or 1.0
                t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
                d = math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
                if best is None or d < best[0]:
                    best = (d, name, along + t * seg, (dx * (y - a[1]) - dy * (x - a[0])) >= 0)
                along += seg
        if best is None or best[0] >= 40:
            return "the address"
        _d, name, along, left = best
        real = self.world.addresses.near(x, y, name) if getattr(self.world, "addresses", None) else None
        if real:
            return real
        number = int(along // 9.0) * 2 + (2 if left else 1) + 10
        return "%d %s" % (number, name)

    def _road_point_near(self, x, y, rmin, rmax):
        pick = self.graph.random_spawn(x, y, rmin, rmax, self.rng, SPAWN_W, tries=20)
        if pick is None:
            return None
        px, py, _h = self.graph.lane_point(*pick)
        return px, py

    # --------------------------------------------------------------- starting
    def _enter_hub(self, hub, player):
        town = self.town
        if hub.role == "courthouse":
            if town.heat <= 0:
                self._say("NO FINES DUE", (200, 200, 210))
            else:
                cost = FINE_PER_STAR * town.stars
                if self.cash >= cost:
                    self.cash -= cost
                    town.add_heat(-10.0)
                    self._say(f"FINE PAID  -${cost}", hub.colour)
                else:
                    self._say(f"FINE IS ${cost}", (236, 52, 52))
            return
        if town.heat > 0:
            self._say("LOSE THE COPS FIRST", (236, 52, 52))
            return
        maker = {"deliveries": self._make_delivery, "getaway": self._make_getaway, "tour": self._make_tour}[hub.role]
        m = maker(hub)
        if m is None:
            self._say("NO JOBS RIGHT NOW", (200, 200, 210))
            return
        m.start_damage = town.damage
        self.mission = m
        self._say(m.title.upper(), m.colour)

    def _make_delivery(self, hub):
        n = self.rng.choice([1, 2, 2, 3])
        fragile = self.rng.random() < 0.3
        targets, prev, total = [], (hub.x, hub.y), 0.0
        for _ in range(n):
            pt = self._road_point_near(prev[0], prev[1], 180.0, 600.0)
            if pt is None:
                break
            total += self._route_len(prev, pt)
            targets.append(Target(pt[0], pt[1], DROP_RADIUS, self.address(*pt), stop=True))
            prev = pt
        if not targets:
            return None
        title = "Fragile Parcel" if fragile else ("Parcel Run" if len(targets) == 1 else f"Parcel Run x{len(targets)}")
        return Mission("delivery", title, hub.colour, targets, total / CRUISE + 12.0 * len(targets),
                       120 + 60 * len(targets) + (80 if fragile else 0), fragile)

    def _make_getaway(self, hub):
        self.town.add_heat(2.6)
        return Mission("getaway", "Getaway", hub.colour, [], 120.0, 450)

    def _make_tour(self, hub):
        spots = []
        for b in self.world.buildings:
            if b.get("landmark") and b.get("label"):
                spots.append((b["label"], _centroid(b["points"])))
        for p in getattr(self.world, "parks", ()):
            if p.get("landmark") == "square":
                spots.append((p.get("label", "Square"), _centroid(p["points"])))
        for p in self.world.props:
            if p["kind"] in ("cenotaph", "lighthouse") and p.get("label"):
                spots.append((p["label"], (p["x"], p["y"])))
        pts = []
        for label, (x, y) in spots:
            cx, cy = self._curb_point(x, y)
            d_hub = math.hypot(cx - hub.x, cy - hub.y)
            if 60 < d_hub < TOUR_RADIUS and all(math.hypot(cx - q[1], cy - q[2]) > 40 for q in pts):
                pts.append((label, cx, cy))
        # visit them nearest-first from the hub
        order, cur = [], (hub.x, hub.y)
        while pts and len(order) < 5:
            nxt = min(pts, key=lambda q: math.hypot(q[1] - cur[0], q[2] - cur[1]))
            pts.remove(nxt)
            order.append(nxt)
            cur = (nxt[1], nxt[2])
        while len(order) < 3:
            pt = self._road_point_near(cur[0], cur[1], 150.0, 400.0)
            if pt is None:
                break
            order.append(("Checkpoint", pt[0], pt[1]))
            cur = pt
        if len(order) < 2:
            return None
        targets = [Target(x, y, CHECK_RADIUS, label) for label, x, y in order]
        total, prev = 0.0, (hub.x, hub.y)
        for t in targets:
            total += self._route_len(prev, (t.x, t.y))
            prev = (t.x, t.y)
        # calibrated on real Amherst: a careful drive with no traffic finishes with ~25% to spare
        return Mission("tour", "Heritage Tour", hub.colour, targets, total / 11.0 + 12.0 * len(targets),
                       200 + 40 * len(targets))

    # ----------------------------------------------------------------- update
    def update(self, dt, player):
        town = self.town
        st = town.state
        if self.banner and st == "playing":          # messages wait while BUSTED/WRECKED is on screen
            text, colour, left = self.banner
            self.banner = (text, colour, left - dt) if left - dt > 0 else None
        if st != self._prev_state and st in ("busted", "wrecked"):
            lost = self.mission is not None
            self.mission = None
            if st == "busted":
                fine = min(self.cash, BUSTED_FINE)
                self.cash -= fine
                self._say(("JOB LOST  " if lost else "") + (f"FINED -${fine}" if fine else "NO CASH TO FINE"),
                          (236, 52, 52))
            elif lost:
                self._say("JOB LOST", (236, 52, 52))
        self._prev_state = st
        if st != "playing":
            return
        if self.mission:
            self._update_mission(dt, player)
        else:
            self._check_hubs(player)

    def _check_hubs(self, player):
        for hub in self.hubs:
            d = math.hypot(player.x - hub.x, player.y - hub.y)
            if d < HUB_RADIUS and player.speed < DROP_SPEED:
                if self._inside is not hub:
                    self._inside = hub
                    self._enter_hub(hub, player)
                return
        if self._inside is not None and math.hypot(player.x - self._inside.x,
                                                   player.y - self._inside.y) > HUB_RADIUS + 5.0:
            self._inside = None

    def _update_mission(self, dt, player):
        m, town = self.mission, self.town
        m.time_left -= dt
        m.elapsed += dt
        if m.kind == "getaway":
            if town.heat <= 0.0 and m.elapsed > 2.0:
                self._complete()
                return
        elif m.stage < len(m.targets):
            t = m.targets[m.stage]
            if math.hypot(player.x - t.x, player.y - t.y) < t.radius and (not t.stop or player.speed < DROP_SPEED):
                m.stage += 1
                if m.stage >= len(m.targets):
                    self._complete()
                    return
                self._say("DELIVERED!" if m.kind == "delivery" else "CHECKPOINT!", m.colour)
        if m.fragile and town.damage - m.start_damage > FRAGILE_DAMAGE:
            self._fail("PARCEL SMASHED")
        elif m.time_left <= 0.0:
            self._fail("OUT OF TIME")

    def _complete(self):
        m = self.mission
        pay = m.reward + 2 * int(max(0.0, m.time_left))
        self.cash += pay
        self.completed += 1
        self.mission = None
        self._say(f"JOB DONE  +${pay}", (130, 250, 100))

    def _fail(self, reason):
        self.mission = None
        self._say(reason, (236, 52, 52))

    def abort(self):
        self.mission = None
        self._inside = None

    # ------------------------------------------------------------ for the HUD
    def current_target(self):
        m = self.mission
        if m and m.stage < len(m.targets):
            t = m.targets[m.stage]
            return t.x, t.y
        return None

    def objective(self):
        m = self.mission
        if m is None:
            return ""
        if m.kind == "getaway":
            return "Lose the police!"
        t = m.targets[min(m.stage, len(m.targets) - 1)]
        n = f"{m.stage + 1}/{len(m.targets)}"
        if m.kind == "delivery":
            return f"{'Fragile! ' if m.fragile else ''}Deliver to {t.label} ({n}) - stop at the marker"
        return f"Checkpoint {n}: {t.label}"

    def hint(self, player):
        for hub in self.hubs:
            if math.hypot(player.x - hub.x, player.y - hub.y) < 30.0:
                if hub.role == "courthouse":
                    stars = self.town.stars
                    return f"{hub.label}: fine ${FINE_PER_STAR * stars}" if stars else f"{hub.label}: no fines due"
                return f"{hub.label}: drive into the marker for {hub.title}"
        return ""

    def markers(self):
        """What the renderers should draw: dicts with x, y, colour, radius, kind."""
        m = self.mission
        if m is None:
            return [{"x": h.x, "y": h.y, "colour": h.colour, "radius": HUB_RADIUS, "kind": "hub"} for h in self.hubs]
        if m.stage < len(m.targets):
            t = m.targets[m.stage]
            return [{"x": t.x, "y": t.y, "colour": m.colour, "radius": t.radius, "kind": "target"}]
        return []
