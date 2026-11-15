"""Traffic obeys posted limits (NSRN-derived) with small per-driver variation."""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from game.roadgraph import RoadGraph


def road(speed=None, rtype="side", name="Main St"):
    r = {"type": rtype, "width": 8, "name": name, "points": [[0, 0], [100, 0]]}
    if speed:
        r["speed"] = speed
    return r


class SpeedLimits(unittest.TestCase):
    def test_edge_uses_posted_limit(self):
        g = RoadGraph([road(50)])
        e = g.edges[0]
        self.assertEqual(e.kmh, 50)
        self.assertAlmostEqual(e.cruise, 50 / 3.6, places=3)
        self.assertEqual(e.name, "Main St")

    def test_fallback_without_speed(self):
        g = RoadGraph([road(None, "main")])
        self.assertGreater(g.edges[0].kmh, 0)

    def test_traffic_stays_near_limit(self):
        from game.world import World
        from game.town import Town, PACE_MAX
        import json
        with open("data/amherst_map.json") as f:
            data = json.load(f)
        w = World(data)
        town = Town(w, seed=3, traffic=30)
        from game.car import Car
        p = Car(*w.spawn())
        for _ in range(900):
            town.update(1 / 30.0, p)
        over = 0
        n = 0
        for c in town.cars:
            if c.kind != "traffic" or c.edge is None:
                continue
            e = town.graph.edges[c.edge]
            n += 1
            if c.speed > e.cruise * PACE_MAX + 4.0:      # grace for hills of lag, braking, collisions
                over += 1
        self.assertGreater(n, 5)
        self.assertLessEqual(over, max(1, n // 10))


if __name__ == "__main__":
    unittest.main()
