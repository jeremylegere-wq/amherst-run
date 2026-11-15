"""Land cover: GeoJSON conversion and woods filling with trees."""
import json
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
        self.assertGreater(len(World(data).props), base)


if __name__ == "__main__":
    unittest.main()
