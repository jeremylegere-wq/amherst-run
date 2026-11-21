"""Road fixes for v1: graded road profiles, overpass decks, poles kept off roads, cul-de-sacs and highway U-turns."""
import json
import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np

from game import grading, turnarounds
from game.extras import _RoadClear
from game.roadgraph import RoadGraph
from game.terrain import Terrain
from game.world import _deck_chains, build_spans, lift_long_bridges


def terrain(fn, size=400.0, step=12.5):
    n = int(size * 2 / step) + 1
    h = [fn(-size + i * step, -size + j * step) for j in range(n) for i in range(n)]
    return Terrain(-size, -size, step, n, n, h, scale=1.0)


class Profiles(unittest.TestCase):
    def test_narrow_dip_is_filled(self):
        g = np.full(60, 10.0)
        g[28:33] = 6.0                                          # a 20 m stream gully
        p = grading.profile(g)
        self.assertGreater(p[30], 9.5)

    def test_wide_valley_is_followed(self):
        g = np.full(80, 10.0)
        g[20:60] = 4.0                                          # 160 m wide valley
        self.assertLess(grading.profile(g)[40], 4.5)

    def test_fill_is_capped(self):
        g = np.full(60, 20.0)
        g[28:33] = 0.0                                          # a deep, narrow ravine: no 20 m causeway
        self.assertLess(grading.profile(g)[30], 12.0)

    def test_ends_meet_the_ground(self):
        g = np.linspace(0.0, 12.0, 40)
        p = grading.profile(g)
        self.assertEqual((p[0], p[-1]), (g[0], g[-1]))


class Grading(unittest.TestCase):
    def test_road_is_smoothed_into_the_ground(self):
        t = terrain(lambda x, y: 10.0 - (4.0 if abs(x) < 10 else 0.0))   # a ditch across the road
        roads = [{"type": "side", "width": 7, "points": [[-300, 0], [300, 0]]}]
        grading.grade(t, roads)
        self.assertGreater(t.height(0, 0), 9.0)
        self.assertAlmostEqual(t.height(0, 300), 6.0, places=3)   # the ditch far from the road: untouched

    def test_overpass_deck_clears_the_road_below(self):
        t = terrain(lambda x, y: 10.0)
        roads = [{"type": "main", "width": 9, "points": [[-300, 0], [-25, 0]]},
                 {"type": "main", "width": 9, "points": [[-25, 0], [25, 0]], "bridge": True, "lift": 5.2},
                 {"type": "main", "width": 9, "points": [[25, 0], [300, 0]]},
                 {"type": "main", "width": 9, "points": [[0, -300], [0, 300]]}]
        spans = build_spans(roads)
        grading.grade(t, roads, spans)
        sp = spans[0]
        mid = min(range(len(sp["points"])), key=lambda k: math.hypot(*sp["points"][k]))
        self.assertGreaterEqual(sp["h"][mid], 5.2 - 1e-6)
        self.assertEqual((sp["h"][0], sp["h"][-1]), (0.0, 0.0))
        steps = [abs(b - a) for a, b in zip(sp["h"], sp["h"][1:])]
        self.assertLess(max(steps), 0.8)                        # 4 m samples, smooth ramps
        self.assertAlmostEqual(t.height(0, 0), 10.0, places=3)  # the road below keeps its level


class Decks(unittest.TestCase):
    def test_touching_deck_pieces_make_one_span(self):
        roads = [{"type": "side", "width": 7, "points": [[-200, 0], [-30, 0]]},
                 {"type": "side", "width": 7, "points": [[-30, 0], [0, 0]], "bridge": True, "lift": 5.2},
                 {"type": "side", "width": 7, "points": [[0, 0], [30, 0]], "bridge": True, "lift": 5.2},
                 {"type": "side", "width": 7, "points": [[30, 0], [200, 0]]},
                 {"type": "main", "width": 9, "points": [[-10, -200], [-10, 200]]}]
        self.assertEqual(len(_deck_chains(roads)), 1)
        self.assertEqual(len(build_spans(roads)), 1)

    def test_long_bridge_over_a_road_gets_a_deck(self):
        roads = [{"type": "main", "width": 9, "points": [[0, -300], [0, 300]], "bridge": True},   # 600 m long
                 {"type": "main", "width": 9, "points": [[-200, 0], [200, 0]]},
                 {"type": "main", "width": 9, "points": [[300, -300], [300, 300]], "bridge": True}]  # over nothing
        self.assertEqual(lift_long_bridges(roads), 1)
        self.assertTrue(roads[0].get("lift"))
        self.assertFalse(roads[2].get("lift"))


class Poles(unittest.TestCase):
    def test_pole_in_the_road_is_moved_to_the_verge(self):
        clear = _RoadClear([{"type": "side", "width": 8, "points": [[0, 0], [100, 0]]}])
        for y in (0.0, 1.5, -3.0):
            x, y2 = clear.off_road(50.0, y)
            self.assertGreaterEqual(abs(y2), 4.0 + 0.5)
            self.assertAlmostEqual(x, 50.0, places=3)


def _map(roads, buildings=(), bounds=(-500, -500, 500, 500)):
    return {"meta": {"bounds": list(bounds)}, "roads": json.loads(json.dumps(roads)), "buildings": list(buildings)}


class Turnarounds(unittest.TestCase):
    def test_dead_end_street_gets_a_cul_de_sac(self):
        data = _map([{"type": "main", "width": 9, "points": [[-400, 0], [400, 0]]},
                     {"type": "side", "width": 7, "points": [[0, 0], [0, 150]]}])
        turnarounds.add(data)
        bulb = [r for r in data["roads"] if r.get("turnaround") == "bulb" and r["type"] == "side"][0]
        self.assertLess(math.dist(bulb["points"][0], [0, 150]), 0.1)
        self.assertLess(math.dist(bulb["points"][-1], [0, 150]), 0.1)
        self.assertTrue(all(lot["bulb"] for lot in data["lots"]))
        g = RoadGraph(data["roads"])                            # traffic can now turn round at the end
        end = g.nearest_node(0, 150)
        self.assertGreaterEqual(len(g.out[end]), 3)          # back up the street, and both ways round

    def test_no_bulb_into_a_building(self):
        house = {"points": [[-6, 158], [6, 158], [6, 168], [-6, 168]]}
        data = _map([{"type": "main", "width": 9, "points": [[-400, 0], [400, 0]]},
                     {"type": "side", "width": 7, "points": [[0, 0], [0, 150]]}], [house])
        turnarounds.add(data)
        self.assertFalse([r for r in data["roads"] if r.get("turnaround") == "bulb" and r["type"] == "side"])

    def test_road_at_the_map_edge_is_cut_back_to_fit(self):
        data = _map([{"type": "main", "width": 9, "points": [[-400, 0], [400, 0]]},
                     {"type": "side", "width": 7, "points": [[0, 0], [0, 498]]}])
        turnarounds.add(data)
        bulb = [r for r in data["roads"] if r.get("turnaround") == "bulb" and r["type"] == "side"][0]
        self.assertLess(max(p[1] for p in bulb["points"]), 500.0)

    def test_divided_highway_end_gets_a_u_turn(self):
        out = {"type": "main", "width": 9, "oneway": 1, "points": [[-400, -15], [300, -15]]}
        back = {"type": "main", "width": 9, "oneway": 1, "points": [[300, 15], [-400, 15]]}
        data = _map([out, back, {"type": "side", "width": 7, "points": [[-400, -15], [-400, 15]]}])
        turnarounds.add(data)
        u = [r for r in data["roads"] if r.get("turnaround") == "uturn"]
        self.assertEqual(len(u), 1)
        self.assertEqual(u[0]["points"][0], [300, -15])
        self.assertEqual(u[0]["points"][-1], [300, 15])
        self.assertGreater(max(p[0] for p in u[0]["points"]), 300)  # it swings round past the end
        g = RoadGraph(data["roads"])
        a, b = g.nearest_node(0, -15), g.nearest_node(0, 15)
        self.assertIsNotNone(g.shortest_path(a, b))            # you can drive out and come back


if __name__ == "__main__":
    unittest.main()
