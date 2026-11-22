"""Tests for junction rules: traffic lights, stop signs and right of way (game/junctions.py).

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import random
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import ai  # noqa: E402
from game import junctions as J  # noqa: E402
from game.ai import AICar, PAL_TRAFFIC  # noqa: E402
from game.roadgraph import RoadGraph  # noqa: E402
from game.streetdetail import signal_light  # noqa: E402


def road(points, rtype="side", width=8):
    return {"type": rtype, "width": width, "points": [list(p) for p in points]}


def crossroads(ew="main", ns="side"):
    """An east-west road and a north-south road crossing at (0, 0)."""
    return RoadGraph([road([(-200, 0), (200, 0)], ew), road([(0, -200), (0, 200)], ns)])


def node_at(g, x, y):
    return min(range(len(g.nodes)), key=lambda n: math.hypot(g.nodes[n][0] - x, g.nodes[n][1] - y))


def incoming(g, jn, n, dx, dy):
    """The edge into junction n travelling in direction (dx, dy)."""
    return next(e for e in jn.into[n] if g.edges[e].dx * dx + g.edges[e].dy * dy > 0.9)


def traffic_on(g, eid, s, speed):
    x, y, h = g.lane_point(eid, s)
    c = AICar("traffic", PAL_TRAFFIC[0], x, y, h)
    c.edge = eid
    c.nxt = g.choose_next(eid, random.Random(1))
    c.vx, c.vy = math.cos(h) * speed, math.sin(h) * speed
    return c


class SignalPhaseTests(unittest.TestCase):
    def test_cycle_matches_the_original_renderer_timing(self):
        for ph in (0, 1):
            for k in range(160):
                t = k * 0.1 + 0.05
                old = (t + 8.0 * ph) % 16.0
                want = 0 if old >= 8.0 else (2 if old < 7.0 else 1)
                self.assertEqual(signal_light(t, ph), want)

    def test_the_two_directions_are_never_green_together(self):
        for k in range(320):
            t = k * 0.05
            self.assertFalse(signal_light(t, 0) == 2 and signal_light(t, 1) == 2)


class ClassifyTests(unittest.TestCase):
    def test_side_road_yields_to_main_road(self):
        g = crossroads()
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        self.assertTrue(jn.is_junction[n])
        self.assertIsNone(jn.control.get(incoming(g, jn, n, 1, 0)))
        self.assertIsNone(jn.control.get(incoming(g, jn, n, -1, 0)))
        self.assertEqual(jn.control[incoming(g, jn, n, 0, 1)], J.YIELD)
        self.assertEqual(jn.control[incoming(g, jn, n, 0, -1)], J.YIELD)

    def test_equal_four_way_is_first_come_first_served(self):
        g = crossroads("side", "side")
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        self.assertEqual({jn.control.get(e) for e in jn.into[n]}, {J.ALLWAY})

    def test_stem_of_an_equal_t_junction_yields(self):
        g = RoadGraph([road([(-200, 0), (200, 0)]), road([(0, 0), (0, 200)])])
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        self.assertEqual(jn.control[incoming(g, jn, n, 0, -1)], J.YIELD)       # coming up the stem, northwards
        self.assertIsNone(jn.control.get(incoming(g, jn, n, 1, 0)))

    def test_plain_bend_is_not_a_junction(self):
        g = RoadGraph([road([(-100, 0), (0, 0), (0, 100)])])
        jn = J.Junctions(g)
        self.assertFalse(any(jn.is_junction))

    def test_osm_signal_gives_east_west_and_north_south_phases(self):
        g = crossroads()
        jn = J.Junctions(g, [{"kind": "signal", "x": 1.0, "y": -1.0}])
        n = node_at(g, 0, 0)
        for dx, dy, ph in ((1, 0, 0), (-1, 0, 0), (0, 1, 1), (0, -1, 1)):
            e = incoming(g, jn, n, dx, dy)
            self.assertEqual(jn.control[e], J.SIGNAL)
            self.assertEqual(jn.phase[e], ph)

    def test_osm_stop_sign_before_the_junction_only_stops_that_approach(self):
        g = crossroads("side", "side")
        jn = J.Junctions(g, [{"kind": "stop", "x": 2.0, "y": 8.0}])          # on the south arm, 8 m out
        n = node_at(g, 0, 0)
        self.assertEqual(jn.control[incoming(g, jn, n, 0, -1)], J.STOP)       # northbound, coming from the south
        self.assertNotEqual(jn.control.get(incoming(g, jn, n, 0, 1)), J.STOP)

    def test_junction_is_seen_through_plain_nodes(self):
        g = RoadGraph([road([(-200, 0), (-100, 0), (-60, 0), (0, 0), (200, 0)], "main"),
                       road([(0, -200), (0, 200)])])
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        start = next(i for i, e in enumerate(g.edges) if abs(e.ax + 100) < 1 and e.dx > 0)    # ends at x = -60
        res = jn.ahead(start)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], n)
        self.assertAlmostEqual(res[1], 60.0, delta=0.5)
        far = next(i for i, e in enumerate(g.edges) if abs(e.ax + 200) < 1 and e.dx > 0)
        self.assertIsNone(jn.ahead(far), "looks further than LOOK_AHEAD")


class BehaviourTests(unittest.TestCase):
    def test_side_road_car_waits_for_main_road_car(self):
        g = crossroads()
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        side = incoming(g, jn, n, 0, 1)
        main = incoming(g, jn, n, 1, 0)
        e = g.edges[side]
        me = traffic_on(g, side, e.length - jn.stop_at[n] - 1.0, 2.0)
        cross = traffic_on(g, main, g.edges[main].length - 20.0, 14.0)
        self.assertLess(jn.limit(me, side, e.length - jn.stop_at[n] - 1.0, [me, cross], 0.0, 0.05), 3.0)
        self.assertTrue(me.jn_hold)
        # with the main road empty it may go
        me2 = traffic_on(g, side, e.length - jn.stop_at[n] - 1.0, 2.0)
        self.assertGreater(jn.limit(me2, side, e.length - jn.stop_at[n] - 1.0, [me2], 0.0, 0.05), 4.0)

    def test_main_road_car_does_not_stop(self):
        g = crossroads()
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        main = incoming(g, jn, n, 1, 0)
        c = traffic_on(g, main, g.edges[main].length - 15.0, 14.0)
        c.nxt = next(e for e in g.out[n] if g.edges[e].dx > 0.9)                 # straight on
        self.assertGreater(jn.limit(c, main, g.edges[main].length - 15.0, [c], 0.0, 0.05), 1e8)

    def test_car_stops_at_a_red_light_and_goes_on_green(self):
        g = crossroads()
        jn = J.Junctions(g, [{"kind": "signal", "x": 0.0, "y": 0.0}])
        n = node_at(g, 0, 0)
        east = incoming(g, jn, n, 1, 0)                                          # phase 0: red from t = 8 to 16
        c = traffic_on(g, east, 5.0, 12.0)
        c.nxt = next(e for e in g.out[n] if g.edges[e].dx > 0.9)
        rng, dt, t = random.Random(3), 1.0 / 60.0, 8.0
        nx = g.nodes[n][0]
        for i in range(60 * 7):                                                  # 7 s of red
            if i % 3 == 0:
                ai.drive_traffic(c, g, [c], rng, 3 * dt, jn, t)
            c.update(dt, c.throttle, c.brake, c.steer, False, True)
            t += dt
            self.assertLess(c.x, nx - jn.box[n], "ran the red light")
        self.assertLess(c.speed, 0.5)
        self.assertGreater(c.x, nx - jn.stop_at[n] - 4.0, "stopped far short of the line")
        for i in range(60 * 6):                                                  # green from t = 16
            if i % 3 == 0:
                ai.drive_traffic(c, g, [c], rng, 3 * dt, jn, t)
            c.update(dt, c.throttle, c.brake, c.steer, False, True)
            t += dt
        self.assertGreater(c.x, nx + 5.0, "did not go on green")

    def test_stop_sign_means_a_full_stop_even_when_clear(self):
        g = crossroads("side", "side")
        jn = J.Junctions(g, [{"kind": "stop", "x": -1.0, "y": 0.0}])           # on the junction: all approaches stop
        n = node_at(g, 0, 0)
        east = incoming(g, jn, n, 1, 0)
        c = traffic_on(g, east, g.edges[east].length - 45.0, 10.0)
        rng, dt, t, slowest = random.Random(3), 1.0 / 60.0, 0.0, 99.0
        nx = g.nodes[n][0]
        for i in range(60 * 14):
            if i % 3 == 0:
                ai.drive_traffic(c, g, [c], rng, 3 * dt, jn, t)
            c.update(dt, c.throttle, c.brake, c.steer, False, True)
            t += dt
            if c.x < nx - 2.0:
                slowest = min(slowest, c.speed)
        self.assertLess(slowest, 0.8, "rolled the stop sign")
        self.assertGreater(math.hypot(c.x - g.nodes[n][0], c.y - g.nodes[n][1]), 8.0, "never left the stop sign")

    def test_left_turn_gives_way_to_oncoming_traffic(self):
        g = crossroads()
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        east = incoming(g, jn, n, 1, 0)
        west = incoming(g, jn, n, -1, 0)
        c = traffic_on(g, east, g.edges[east].length - jn.stop_at[n] - 2.0, 4.0)
        c.nxt = next(e for e in g.out[n] if g.edges[e].dy < -0.9)               # left = north when heading east
        onc = traffic_on(g, west, g.edges[west].length - 20.0, 14.0)
        s = g.edges[east].length - jn.stop_at[n] - 2.0
        held = jn.limit(c, east, s, [c, onc], 0.0, 0.05)
        self.assertTrue(c.jn_hold)
        self.assertLess(held, jn.limit(c, east, s, [c], 0.0, 0.05))
        self.assertFalse(c.jn_hold)

    def test_do_not_enter_when_the_exit_is_blocked(self):
        g = crossroads()
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        east = incoming(g, jn, n, 1, 0)
        c = traffic_on(g, east, g.edges[east].length - jn.stop_at[n] - 1.0, 3.0)
        c.nxt = next(e for e in g.out[n] if g.edges[e].dx > 0.9)
        parked = AICar("traffic", PAL_TRAFFIC[1], jn.box[n] + 4.0, 2.0, 0.0)  # stopped just past the junction
        s = g.edges[east].length - jn.stop_at[n] - 1.0
        self.assertLess(jn.limit(c, east, s, [c, parked], 0.0, 0.05), 3.0)
        self.assertFalse(c.jn_hold, "a blocked exit is a jam, not a wait at a sign")

    def test_a_car_waiting_at_its_own_line_does_not_block_the_exit(self):
        """Two cars waiting at an all-way stop used to count each other as blocking their way out (the one on the
        far side of the junction stands on our exit road, facing us) and waited for each other forever."""
        g = crossroads("side", "side")
        jn = J.Junctions(g)
        n = node_at(g, 0, 0)
        east = incoming(g, jn, n, 1, 0)
        c = traffic_on(g, east, g.edges[east].length - jn.stop_at[n] - 1.0, 0.5)
        c.nxt = next(e for e in g.out[n] if g.edges[e].dx > 0.9)
        waiting = AICar("traffic", PAL_TRAFFIC[1], jn.stop_at[n], -2.0, math.pi)   # across the junction, facing us
        self.assertFalse(jn._exit_blocked(c, n, east, [c, waiting]))
        parked = AICar("traffic", PAL_TRAFFIC[1], jn.box[n] + 4.0, 2.0, 0.0)       # facing out, in our lane
        self.assertTrue(jn._exit_blocked(c, n, east, [c, parked]))


if __name__ == "__main__":
    unittest.main()
