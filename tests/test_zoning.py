"""Zoning: grid lookup, zone looks, and that real data / landmarks are never overwritten."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import zoning as Z  # noqa: E402

DOC = {"cell": 10.0, "x0": 0.0, "y0": 0.0, "zones": {}, "rows": ["RRMM", "RR--", "DDDD"]}


def sq(x, y, s=10.0):
    return [[x, y], [x + s, y], [x + s, y + s], [x, y + s]]


class Lookup(unittest.TestCase):
    def test_zone_at_cells_and_outside(self):
        z = Z.Zoning(DOC)
        self.assertEqual(z.zone_at(5, 5), "R")
        self.assertEqual(z.zone_at(25, 5), "M")
        self.assertEqual(z.zone_at(-50, 5), "-")
        self.assertEqual(z.zone_at(500, 500), "-")

    def test_unzoned_cell_surrounded_by_one_zone_takes_it(self):
        z = Z.Zoning({"cell": 10.0, "x0": 0.0, "y0": 0.0, "zones": {}, "rows": ["RRR", "R-R", "RRR"]})
        self.assertEqual(z.zone_at(15, 15), "R")


class Apply(unittest.TestCase):
    def data(self):
        return {"buildings": [
            {"points": sq(2, 2), "tags": {"building": "yes"}},                       # R house
            {"points": sq(22, -4), "tags": {"building": "yes"}},                  # M industrial
            {"points": sq(2, 22), "tags": {"building": "yes"}, "material": "granite"},   # D but already set
            {"points": sq(12, 22), "tags": {"building": "yes", "height": "12"}},     # D but real height
            {"points": sq(22, 22), "tags": {"building": "yes"}, "landmark": "church"},
            {"points": sq(32, 22), "tags": {"building": "yes"}},                     # D plain
            {"points": sq(2, 2, 3), "tags": {"building": "shed"}},                   # too small
        ]}

    def test_looks_follow_zone_and_protect_real_data(self):
        d = self.data()
        counts = Z.apply(d, Z.Zoning(DOC))
        b = d["buildings"]
        self.assertEqual(b[0]["material"], "clapboard")
        self.assertEqual(b[0]["zone"], "R")
        self.assertEqual(b[1]["material"], "corrugated")
        self.assertEqual(b[2]["material"], "granite")
        self.assertNotIn("zone", b[2])
        self.assertNotIn("material", b[3])
        self.assertNotIn("zone", b[4])
        self.assertIn(b[5]["material"], ("brick", "sandstone"))
        self.assertNotIn("material", b[6])
        self.assertEqual(counts, {"R": 1, "M": 1, "D": 1})

    def test_deterministic(self):
        a, b = self.data(), self.data()
        Z.apply(a, Z.Zoning(DOC))
        Z.apply(b, Z.Zoning(DOC))
        self.assertEqual(a, b)

    def test_only_four_cornered_houses_get_gable_roofs(self):
        six = [[0, 0], [10, 0], [10, 5], [5, 5], [5, 10], [0, 10]]
        d = {"buildings": [{"points": six, "tags": {}}]}
        Z.apply(d, Z.Zoning({"cell": 10.0, "x0": 0.0, "y0": 0.0, "zones": {}, "rows": ["R"]}))
        self.assertNotIn("roof", d["buildings"][0])


class RealData(unittest.TestCase):
    def test_shipped_zoning_matches_downtown_and_industrial(self):
        path = os.path.join(ROOT, "data", "zoning.json")
        if not os.path.exists(path):
            self.skipTest("no data/zoning.json")
        with open(path) as f:
            z = Z.Zoning(json.load(f))
        self.assertEqual(z.zone_at(394.6, -835.8), "D")     # Victoria Square is Downtown Commercial
        self.assertEqual(z.zone_at(-500, 1900), "M")        # the industrial park south west of town

    def test_world_load_applies_zoning_and_can_skip_it(self):
        from game.world import World
        path = os.path.join(ROOT, "data", "amherst_map.json")
        if not os.path.exists(path):
            self.skipTest("no map")
        w = World.load(path, custom=None)
        w0 = World.load(path, custom=None, zoning=False)
        self.assertGreater(sum(1 for b in w.buildings if b.get("zone")), 500)
        self.assertEqual(sum(1 for b in w0.buildings if b.get("zone")), 0)


if __name__ == "__main__":
    unittest.main()
