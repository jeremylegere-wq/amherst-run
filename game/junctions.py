"""Junction rules for AI traffic: traffic lights, stop signs and right of way.

Every road-graph node where three or more roads meet is a junction. Each edge that drives INTO a junction gets one
control, decided once when the town is built:

  SIGNAL  an OpenStreetMap traffic_signals node. East-west and north-south approaches take turns on the same 16 s
          cycle the renderer uses to light the signal heads (streetdetail.signal_light), so cars obey what you see.
  STOP    an OpenStreetMap stop sign on this approach: come to a full stop at the line, then go when it is clear.
  YIELD   no sign mapped, but this is the minor road (lane < side < main, or the stem of a T): slow down and
          give way to anyone in the junction or arriving soon on another approach.
  ALLWAY  a junction of equal roads with no through road (a plain 4-way): first come, first served.
  None    the priority road: just drive (car-ahead braking in ai.obstacle_limit still applies).

Cars look ahead to the next junction through plain bend/subdivision nodes (precomputed per edge), so they can brake in
time even when the junction is a few short edges away. Only traffic uses this; police and players ignore it, and
traffic gives way to them like to anyone else.
"""
import math

from .streetdetail import STOP_BACK, signal_light

SIGNAL, STOP, YIELD, ALLWAY = "signal", "stop", "yield", "allway"
RANK = {"lane": 0, "side": 1, "main": 2}
LOOK_AHEAD = 90.0          # metres: how far ahead (through plain nodes) a car looks for the next junction
ACT_RANGE = 45.0           # metres to the stop line at which a car starts to care
MARK_SNAP = 15.0           # an OSM signal/stop node belongs to the nearest junction within this distance
CAR_HALF = 2.4             # stop with the car's centre this far behind the line (front bumper at the line)
BRAKE = 4.0                # m/s^2 used to plan a comfortable stop
CREEP = 5.0                # m/s: speed to roll into a yield / all-way junction when it is clear
GAP = 3.0                  # seconds: a car closer than this to the junction on another approach has to be let by
STOP_HOLD = 0.8            # seconds standing still at a stop sign before looking to go
IMPATIENT = 4.0            # seconds waiting before a car only checks the junction box itself (breaks dead-locks)


def _stop_speed(d_line):
    """Target speed that brings a car to rest at the line. ai.speed_control only brakes once the car is 1.2 m/s
    over target, so the curve is lowered by that much and aims a metre short."""
    return max(0.0, math.sqrt(2.0 * BRAKE * max(0.0, d_line - 1.0)) - 1.2)


class Junctions:
    def __init__(self, graph, marks=()):
        self.g = graph
        self.control = {}      # incoming edge id -> SIGNAL / STOP / YIELD / ALLWAY (missing = priority)
        self.phase = {}        # incoming edge id -> 0 (east-west) or 1 (north-south) at signals
        self.box = {}          # junction node -> radius of the junction box in metres
        self.stop_at = {}      # junction node -> distance from the node to a car's stopping point
        self._ahead = {}       # edge id -> (junction node, metres from the edge's end, incoming edge) or None
        nbrs = [set() for _ in graph.nodes]
        self.into = [[] for _ in graph.nodes]
        for eid, e in enumerate(graph.edges):
            nbrs[e.a].add(e.b)
            nbrs[e.b].add(e.a)
            self.into[e.b].append(eid)
        self.is_junction = [len(n) >= 3 for n in nbrs]
        for n, j in enumerate(self.is_junction):
            if j:
                self._classify(n)
        self._apply_marks(marks)

    # ------------------------------------------------------------------ build
    def _arms(self, n):
        """{neighbour node: (rank, unit vector pointing out of the junction)} for junction n."""
        g, arms = self.g, {}
        for eid in g.out[n]:
            e = g.edges[eid]
            arms[e.b] = (max(arms.get(e.b, (-1,))[0], RANK.get(e.rtype, 1)), (e.dx, e.dy))
        for eid in self.into[n]:
            e = g.edges[eid]
            arms[e.a] = (max(arms.get(e.a, (-1,))[0], RANK.get(e.rtype, 1)), (-e.dx, -e.dy))
        return arms

    def _classify(self, n):
        g = self.g
        half = max(g.edges[eid].width for eid in g.out[n] + self.into[n]) / 2.0
        self.box[n] = half + 1.0
        self.stop_at[n] = max(STOP_BACK, self.box[n]) + CAR_HALF
        arms = self._arms(n)
        top = max(r for r, _ in arms.values())
        major = [k for k, (r, _) in arms.items() if r == top]
        if len(major) > 2:
            # equal roads: the straightest pair is the through road, if there is one and it is the only one
            pairs = [(arms[a][1][0] * arms[b][1][0] + arms[a][1][1] * arms[b][1][1], a, b)
                     for i, a in enumerate(major) for b in major[i + 1:]]
            straight = [p for p in pairs if p[0] < -0.8]
            if len(straight) == 1:
                major = [straight[0][1], straight[0][2]]
            else:
                for eid in self.into[n]:
                    self.control[eid] = ALLWAY
                return
        for eid in self.into[n]:
            if g.edges[eid].a not in major:
                self.control[eid] = YIELD

    def _nearest_junction(self, x, y):
        best, best_d = None, MARK_SNAP
        nodes = self.g.nodes
        for n in self._nodes_near(x, y):
            if self.is_junction[n]:
                d = math.hypot(nodes[n][0] - x, nodes[n][1] - y)
                if d < best_d:
                    best, best_d = n, d
        return best, best_d

    def _nodes_near(self, x, y):
        g = self.g
        k = int(MARK_SNAP // 40.0) + 1
        cx, cy = int(x // 40.0), int(y // 40.0)
        for gx in range(cx - k, cx + k + 1):
            for gy in range(cy - k, cy + k + 1):
                yield from g._coarse.get((gx, gy), ())

    def _apply_marks(self, marks):
        g = self.g
        for m in marks:
            kind = m.get("kind")
            if kind not in ("signal", "stop"):
                continue
            x, y = float(m["x"]), float(m["y"])
            n, d = self._nearest_junction(x, y)
            if n is None:
                continue
            ins = self.into[n]
            if kind == "signal":
                for eid in ins:
                    e = g.edges[eid]
                    self.control[eid] = SIGNAL
                    self.phase[eid] = 0 if abs(e.dx) >= abs(e.dy) else 1     # same rule as streetdetail
                continue
            if d < 3.0:          # sign mapped on the junction itself: the lowest-ranked road(s) stop
                low = min(RANK.get(g.edges[eid].rtype, 1) for eid in ins)
                hit = [eid for eid in ins if RANK.get(g.edges[eid].rtype, 1) == low]
            else:                # sign mapped on one road before the junction: that approach stops
                nx, ny = g.nodes[n]
                hit = []
                for eid in ins:
                    e = g.edges[eid]
                    back = (nx - x) * e.dx + (ny - y) * e.dy               # metres before the node, along the approach
                    side = abs(-(x - nx) * e.dy + (y - ny) * e.dx)
                    if 0.0 < back <= MARK_SNAP and side < e.width / 2.0 + 2.5:
                        hit.append(eid)
            for eid in hit:
                if self.control.get(eid) != SIGNAL:
                    self.control[eid] = STOP

    # ---------------------------------------------------------------- queries
    def ahead(self, eid):
        """(junction node, metres from the end of edge eid to it, incoming edge) or None, following plain nodes."""
        if eid in self._ahead:
            return self._ahead[eid]
        g, extra, cur, res = self.g, 0.0, eid, None
        for _ in range(64):
            e = g.edges[cur]
            if self.is_junction[e.b]:
                res = (e.b, extra, cur)
                break
            fwd = [c for c in g.out[e.b] if g.edges[c].b != e.a]
            if len(fwd) != 1:
                break                                                       # dead end (or a one-way oddity)
            cur = fwd[0]
            extra += g.edges[cur].length
            if extra > LOOK_AHEAD:
                break
        self._ahead[eid] = res
        return res

    def light(self, eid, t):
        """0 red, 1 yellow, 2 green for a signalled approach at time t."""
        return signal_light(t, self.phase.get(eid, 0))

    def _traffic_at(self, car, n, approach, others):
        """(junction box busy?, seconds until the first car on another approach arrives)."""
        nx, ny = self.g.nodes[n]
        box = self.box[n]
        busy, first = False, 1e9
        for o in others:
            if o is car:
                continue
            dx, dy = nx - o.x, ny - o.y
            if abs(dx) > ACT_RANGE or abs(dy) > ACT_RANGE:
                continue
            d = math.hypot(dx, dy)
            if d < 0.5:
                busy = True
                continue
            ux, uy = dx / d, dy / d
            if ux * approach[0] + uy * approach[1] > 0.85:
                continue                          # same approach as us: ahead in the queue or behind us
            closing = o.vx * ux + o.vy * uy        # speed towards the junction centre
            if d < box:
                if closing > -1.0 or o.speed < 1.0:
                    busy = True                    # in the junction and not on its way out
                continue
            if closing > 1.5 and closing > 0.8 * o.speed:
                first = min(first, (d - box) / closing)
        return busy, first

    def _oncoming(self, car, n, approach, others):
        """True if a car coming the other way is in the junction or arrives within GAP seconds."""
        nx, ny = self.g.nodes[n]
        box = self.box[n]
        for o in others:
            if o is car:
                continue
            dx, dy = nx - o.x, ny - o.y
            if abs(dx) > ACT_RANGE or abs(dy) > ACT_RANGE:
                continue
            d = math.hypot(dx, dy)
            if d < 0.5:
                return True
            ux, uy = dx / d, dy / d
            if ux * approach[0] + uy * approach[1] > -0.85:
                continue                          # not coming from straight ahead of us
            closing = o.vx * ux + o.vy * uy
            if closing > 1.5 and (d < box or (d - box) / closing < GAP):
                return True
        return False

    def _exit_blocked(self, car, n, ie, others):
        """True if a stopped or crawling car sits just past the junction on our way out (don't block the box)."""
        if car.edge != ie or car.nxt is None:
            return False
        x = self.g.edges[car.nxt]
        nx, ny = self.g.nodes[n]
        reach = self.box[n] + 12.0                     # room for us past the junction plus a car length
        for o in others:
            if o is car or o.speed > 3.0:
                continue
            dx, dy = o.x - nx, o.y - ny
            along = dx * x.dx + dy * x.dy
            if 0.0 < along < reach and abs(-dx * x.dy + dy * x.dx) < 3.5:
                return True
        return False

    def _turns_left(self, car, ie):
        """True if the car's chosen exit from the junction at the end of edge ie is a left turn."""
        if car.edge != ie or car.nxt is None:
            return False
        a, b = self.g.edges[ie], self.g.edges[car.nxt]
        return a.dx * b.dy - a.dy * b.dx < -0.5   # y grows south, so a negative cross product turns left

    def limit(self, car, eid, s, others, t, dt):
        """Highest safe speed for traffic car `car` at distance s along edge eid (1e9 = no junction rule)."""
        car.jn_hold = False
        res = self.ahead(eid)
        if res is None:
            return 1e9
        n, extra, ie = res
        ctl = self.control.get(ie)
        if car.jn_pass == n:
            return 1e9
        if ctl is None:                                      # priority road: give way only when turning left
            d_line = self.g.edges[eid].length - s + extra - self.stop_at[n]
            if d_line > 15.0 or d_line < -1.0:
                return 1e9
            ie_e = self.g.edges[ie]
            left = self._turns_left(car, ie)
            jammed = self._exit_blocked(car, n, ie, others)
            if jammed or (left and self._oncoming(car, n, (ie_e.dx, ie_e.dy), others)):
                car.jn_hold = not jammed                     # a jammed exit counts as a jam (ai.py clears jams)
                return _stop_speed(d_line)
            if d_line < 2.0:
                car.jn_pass = n
            return math.sqrt(CREEP * CREEP + 2.0 * BRAKE * max(0.0, d_line)) if left else 1e9
        if car.jn_node != n:              # new junction: forget the last one's state
            car.jn_node, car.jn_stop_t, car.jn_wait, car.jn_stopped = n, 0.0, 0.0, False
        e = self.g.edges[eid]
        d_line = e.length - s + extra - self.stop_at[n]
        if d_line > ACT_RANGE:
            return 1e9
        v = car.speed
        if d_line < -1.0:                                    # already over the line (pushed, or late): carry on
            car.jn_pass = n
            return 1e9

        ie_e = self.g.edges[ie]
        approach = (ie_e.dx, ie_e.dy)
        go, slow = False, False
        waited = car.jn_wait
        if ctl == SIGNAL:
            lit = self.light(ie, t)
            if lit == 2:
                busy, _ = self._traffic_at(car, n, approach, others)
                go = not busy and not (self._turns_left(car, ie) and self._oncoming(car, n, approach, others))
            else:                                            # red or yellow: stop if we comfortably can
                go = v * v > 2.0 * 6.0 * max(0.0, d_line) and d_line < 12.0
        else:
            near_line = d_line < 1.5
            if ctl == STOP and not car.jn_stopped:
                if near_line and v < 0.8:
                    car.jn_stop_t += dt
                    if car.jn_stop_t >= STOP_HOLD:
                        car.jn_stopped = True
                go = False
            elif d_line < 15.0:
                busy, first = self._traffic_at(car, n, approach, others)
                if ctl == ALLWAY:
                    mine = d_line / max(v, 1.0)
                    go = not busy and first > mine + 0.3
                else:
                    go = not busy and first > GAP
                if not go and waited > IMPATIENT and not busy:
                    go = True                                # nobody is moving: someone has to go
                slow = go
            else:
                go, slow = True, True                        # far off: just ease off for the junction
        if v < 0.8 and d_line < 3.0:
            car.jn_wait += dt
        jammed = False
        if go and d_line < 4.0 and self._exit_blocked(car, n, ie, others):
            go, jammed = False, True                         # the way out is jammed: wait behind the line
        if go:
            if d_line < 2.0:
                car.jn_pass, car.jn_stopped = n, False
            if slow:
                return math.sqrt(CREEP * CREEP + 2.0 * BRAKE * max(0.0, d_line))
            return 1e9
        car.jn_hold = not jammed                             # a jammed exit counts as a jam (ai.py clears jams)
        return _stop_speed(d_line)
