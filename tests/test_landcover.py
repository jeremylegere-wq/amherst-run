"""Land cover: GeoJSON conversion and woods filling with trees."""
import json
import math
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import fetch_landcover as F  # noqa: E402
from game import landcover as L  # noqa: E402

META = {"origin_lat": 45.826, "origin_lon": -64.218}


def square_ll(lat, lon, d=0.001):
    return [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]


class Convert(unittest.TestCase):
    def test_geojson_multipolygon_with_hole_and_a_speck(self):
        big = square_ll(45.826, -64.218, 0.002)
        hole = square_ll(45.8265, -64.2175, 0.0005)
        speck = square_ll(45.84, -64.2, 0.00001)
        doc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": [[big, hole], [speck]]}}]}
        woods = F.convert(doc, META)
        self.assertEqual(len(woods), 1)                      # the speck is dropped
        self.assertEqual(len(woods[0]["rings"]), 2)
        x, y = woods[0]["rings"][0][0]
        self.assertAlmostEqual(x, 0.0, delta=1.0)
        self.assertAlmostEqual(y, 0.0, delta=1.0)

    def test_soda_rows(self):
        doc = [{"the_geom": {"type": "Polygon", "coordinates": [square_ll(45.826, -64.218, 0.003)]}, "feat_code": "x"}]
        self.assertEqual(len(F.convert(doc, META)), 1)


class Sites(unittest.TestCase):
    def wood(self):
        w = {"rings": [[[0, 0], [100, 0], [100, 100], [0, 100]], [[40, 40], [60, 40], [60, 60], [40, 60]]]}
        w["bbox"] = (0, 0, 100, 100)
        return w

    def test_sites_are_inside_and_avoid_holes(self):
        pts = L.sites([self.wood()], random.Random(1))
        self.assertGreater(len(pts), 100)
        for x, y in pts:
            self.assertTrue(0 <= x <= 100 and 0 <= y <= 100)
            self.assertFalse(40 < x < 60 and 40 < y < 60)

    def test_limit(self):
        self.assertEqual(len(L.sites([self.wood()], random.Random(1), limit=10)), 10)

    def test_world_gets_woods_trees(self):
        import make_sample_map
        from game.world import World
        data = make_sample_map.build()
        base = len(World(data).props)
        w = self.wood()
        w["bbox"] = (-200, -200, -100, -100)
        w["rings"] = [[[-200, -200], [-100, -200], [-100, -100], [-200, -100]]]
        data["woods"] = [w]
        world = World(data)
        self.assertEqual(len(world.props), base)              # woods trees are streamed, not planted up front
        self.assertTrue(any(p["kind"] == "tree" for p in world.props_near(-150, -150, 50)))


def woods_world(extra_props=(), seed=1):
    """The sample town with one square wood (-200..-100 on both axes) and optional hand props."""
    import make_sample_map
    from game.world import World
    data = make_sample_map.build()
    data["woods"] = [{"rings": [[[-200, -200], [-100, -200], [-100, -100], [-200, -100]]],
                      "bbox": (-200, -200, -100, -100)}]
    data["props"] = list(data.get("props", [])) + list(extra_props)
    data["meta"]["seed"] = seed
    return World(data)


def streamed(world):
    """All streamed woods trees in memory, as sorted (x, y, h, r, c) tuples."""
    out = []
    for c, n in world._woods_made.items():
        out += [(p["x"], p["y"], p["h"], p["r"], p["c"]) for p in world._prop_grid.get(c, [])[n:]]
    return sorted(out)


class Streaming(unittest.TestCase):
    def test_thinning_is_the_same_in_any_block_and_keeps_the_gap(self):
        a = {(round(x, 6), round(y, 6)) for x, y, _p, _h in L.thinned(0, 0, 10)}
        b = set()
        for i0 in (0, 5):
            for j0 in (0, 5):
                b |= {(round(x, 6), round(y, 6)) for x, y, _p, _h in L.thinned(i0, j0, 5)}
        self.assertEqual(a, b)
        pts = sorted(a)
        for i, (x, y) in enumerate(pts):
            for x2, y2 in pts[i + 1:]:
                self.assertGreaterEqual((x - x2) ** 2 + (y - y2) ** 2, L.MIN_GAP ** 2)
        self.assertGreater(len(a), 40)                        # ~1 tree per 100-130 m2 survives

    def test_same_trees_whatever_order_cells_are_made_in(self):
        from game.world import CELL
        cells = [(gx, gy) for gx in range(int(-200 // CELL), int(-100 // CELL) + 1)
                 for gy in range(int(-200 // CELL), int(-100 // CELL) + 1)]
        w1, w2 = woods_world(), woods_world()
        for gx, gy in cells:
            w1.props_near((gx + 0.5) * CELL, (gy + 0.5) * CELL, 1.0)
        for gx, gy in reversed(cells):
            w2.props_near((gx + 0.5) * CELL, (gy + 0.5) * CELL, 1.0)
        self.assertGreater(len(streamed(w1)), 30)
        self.assertEqual(streamed(w1), streamed(w2))
        w3 = woods_world()
        w3.warm_woods(-150, -150, 60)
        self.assertEqual(streamed(w1), streamed(w3))
        self.assertNotEqual(streamed(w1), streamed(woods_world(seed=2)))   # the map seed changes the woods

    def test_trees_stay_inside_the_wood_and_off_roads(self):
        w = woods_world()
        w.warm_woods(-150, -150, 60)
        for x, y, *_ in streamed(w):
            self.assertTrue(-200 <= x <= -100 and -200 <= y <= -100)
            self.assertGreaterEqual(w.road_clearance(x, y), 1.5)
            self.assertFalse(w.in_building(x, y))

    def test_no_woods_tree_stacked_on_a_hand_tree(self):
        w = woods_world()
        w.warm_woods(-150, -150, 60)
        x, y = streamed(w)[len(streamed(w)) // 2][:2]
        hand = {"kind": "tree", "x": x + 1.0, "y": y + 0.5}       # a hand-placed tree right next to a woods site
        w = woods_world([hand])
        self.assertTrue(any(abs(p["x"] - hand["x"]) < 0.01 and abs(p["y"] - hand["y"]) < 0.01 for p in w.props))
        w.warm_woods(-150, -150, 60)
        near = [p for p in w.props_near(hand["x"], hand["y"], 6.0)
                if math.hypot(p["x"] - hand["x"], p["y"] - hand["y"]) < 5.0]
        self.assertEqual(len(near), 1)                         # only the hand tree itself
        trees = streamed(w)
        for i, (ax, ay, *_r) in enumerate(trees):
            for bx, by, *_s in trees[i + 1:]:
                self.assertGreaterEqual(math.hypot(ax - bx, ay - by), 5.0 - 1e-6)

    def test_car_collides_with_a_streamed_tree_on_first_contact(self):
        from game.car import Car
        from game.collision import car_hits_world
        w = woods_world()
        w.warm_woods(-150, -150, 60)
        x, y = streamed(w)[0][:2]
        fresh = woods_world()                                   # nothing streamed yet: collision must make the cell
        self.assertEqual(len(fresh._woods_made), 0)
        self.assertTrue(car_hits_world(Car(x - 2.3, y, 0.0), fresh))   # front bumper at the trunk
        self.assertTrue(any(p["kind"] == "tree" and (p["x"], p["y"]) == (x, y) for p in fresh.props_near(x, y, 0.1)))

    def test_far_cells_are_spread_over_calls(self):
        from game import world as Wm
        w = woods_world()
        w.props_near(-150, -150, 130.0)
        first = len(w._woods_made)
        w.props_near(-150, -150, 100.0, far=0)                # the frame's shadow pass: no far cells
        self.assertEqual(len(w._woods_made), first)
        w.props_near(-150, -150, 130.0)                       # next frame, same spot: one more
        self.assertEqual(len(w._woods_made), first + Wm.WOODS_PER_CALL)
        total = (int((-150 + 130) // Wm.CELL) - int((-150 - 130) // Wm.CELL) + 1) ** 2
        self.assertLess(first, total)
        for _ in range(total):                                # a standing camera fills its whole view in time
            w.props_near(-150, -150, 130.0)
        self.assertEqual(len(w._woods_made), total)

    def test_forgotten_cells_come_back_the_same(self):
        from game import world as Wm
        ref = woods_world()
        ref.warm_woods(-150, -150, 60)
        keep = Wm.WOODS_CELLS_KEPT
        try:
            Wm.WOODS_CELLS_KEPT = 3
            w = woods_world()
            w.warm_woods(-150, -150, 60)
            self.assertLessEqual(len(w._woods_made), 3)
            w.warm_woods(-150, -150, 60)                       # remakes the forgotten ones
            for c in list(w._woods_made):
                self.assertEqual(w._prop_grid.get(c, []), ref._prop_grid.get(c, []))
            self.assertFalse(any(len(v) > 25 for v in w._prop_grid.values()))
        finally:
            Wm.WOODS_CELLS_KEPT = keep


if __name__ == "__main__":
    unittest.main()
