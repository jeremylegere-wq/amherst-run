"""Tests for fixes found on the first real Amherst download, plus checks that run on the real map
whenever data/amherst_map.json exists (skipped otherwise).

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import fetch_osm  # noqa: E402
import landmarks as LM  # noqa: E402
import make_sample_map  # noqa: E402
from game import render3d as R  # noqa: E402
from game.missions import TOUR_RADIUS, MissionManager  # noqa: E402
from game.roadgraph import RoadGraph  # noqa: E402
from game.town import Town  # noqa: E402
from game.world import World  # noqa: E402

REAL_MAP = os.path.join(ROOT, "data", "amherst_map.json")


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class FetchAreaTests(unittest.TestCase):
    def test_default_area_includes_downtown_and_highway(self):
        s, w, n, e = fetch_osm.bbox_from_center(*fetch_osm.DEFAULT_CENTER, fetch_osm.DEFAULT_RADIUS_M)
        court_house = (45.83315, -64.21318)
        self.assertTrue(s < court_house[0] < n and w < court_house[1] < e)
        self.assertLess(s, 45.805)               # reaches Highway 104 on the south side

    def test_fetch_asks_for_point_banks_and_post_offices(self):
        q = fetch_osm.build_query((45.80, -64.25, 45.84, -64.18))
        self.assertIn("bank|post_office", q)
        self.assertIn('node["tourism"~"^(museum|information)$"]', q)


class LandmarkAreaTests(unittest.TestCase):
    def base(self):
        return {"meta": {"bounds": [-300, -300, 300, 300]},
                "roads": [{"type": "main", "width": 11, "points": [[-300, 0], [300, 0]]}],
                "buildings": [{"points": rect(20, -40, 50, -15)}, {"points": rect(-60, -40, -40, -15)}]}

    def test_landmark_outside_download_is_reported_not_guessed(self):
        data = self.base()
        report = LM.apply_landmarks(data, {"landmarks": [
            {"id": "ch", "kind": "courthouse", "names": ["court"], "near_xy": [40, -350], "search": 150}]},
            area=(-300, -300, 300, 300))
        self.assertIn("OUTSIDE", report[0])
        self.assertFalse(any("landmark" in b for b in data["buildings"]))

    def test_point_of_interest_tags_move_onto_their_building(self):
        data = self.base()
        data["pois"] = [{"x": 35, "y": -30, "tags": {"amenity": "bank", "name": "Some Bank"}}]
        LM.apply_landmarks(data, {"landmarks": [
            {"id": "b", "kind": "civic", "label": "Bank", "tags": {"amenity": "bank"}, "near_xy": [0, 0],
             "search": 500, "all": True, "fallback_nearest": False, "role": "getaway"}]})
        b = data["buildings"][0]
        self.assertEqual((b["landmark"], b["label"], b["role"]), ("civic", "Bank", "getaway"))   # generic label

    def test_unnamed_church_gets_a_readable_label(self):
        data = self.base()
        data["buildings"][1]["tags"] = {"amenity": "place_of_worship"}
        LM.apply_landmarks(data, {"landmarks": [{"id": "churches", "kind": "church", "tags": {"amenity": "place_of_worship"},
                                                 "near_xy": [0, 0], "search": 500, "all": True}]})
        self.assertEqual(data["buildings"][1]["label"], "Church")

    def test_spawn_falls_back_to_town_centre_road(self):
        data = self.base()
        LM.apply_landmarks(data, {"district": {"near_xy": [0, -30], "radius": 100}})
        x, y, h = data["meta"]["spawn"]
        self.assertAlmostEqual(y, 0.0)


class HeightAndGraffitiTests(unittest.TestCase):
    def test_houses_are_low_and_apartments_tall(self):
        house = R.default_height({"tags": {"building": "house"}}, 3, 120)
        shed = R.default_height({"tags": {"building": "garage"}}, 3, 30)
        flats = R.default_height({"tags": {"building": "apartments"}}, 3, 600)
        plain_house = R.default_height({}, 3, 150)
        big_box = R.default_height({}, 3, 5000)
        self.assertTrue(5 <= house <= 8.5 and 5 <= plain_house <= 8.5)
        self.assertLess(shed, 4)
        self.assertGreater(flats, 9)
        self.assertLess(big_box, 11)
        self.assertEqual(R.default_height({"landmark": "heritage_house"}, 3, 300), 8.5)

    def test_osm_height_wins(self):
        w = World(make_sample_map.build(demo=False))
        data = make_sample_map.build(demo=False)
        data["buildings"][0]["height"] = 30.0
        r = R.Renderer3D(World(data))
        self.assertEqual(r.buildings[0][2], 30.0)
        self.assertTrue(w)

    def test_no_graffiti_on_family_homes(self):
        self.assertFalse(R.graffiti_ok({"tags": {"building": "house"}}, 400))
        self.assertFalse(R.graffiti_ok({}, 120))
        self.assertTrue(R.graffiti_ok({"material": "brick"}, 120))
        self.assertTrue(R.graffiti_ok({"tags": {"building": "retail"}}, 900))
        self.assertFalse(R.graffiti_ok({"landmark": "church", "material": "sandstone"}, 900))


class TourRadiusTests(unittest.TestCase):
    def test_tour_checkpoints_stay_near_the_start(self):
        w = World(make_sample_map.build())
        town = Town(w, traffic=0)
        ms = MissionManager(w, town, seed=2)
        hub = next(h for h in ms.hubs if h.role == "tour")
        m = ms._make_tour(hub)
        for t in m.targets:
            if t.label != "Checkpoint":
                self.assertLess(math.hypot(t.x - hub.x, t.y - hub.y), TOUR_RADIUS + 1)
        self.assertLessEqual(len(m.targets), 5)


@unittest.skipUnless(os.path.exists(REAL_MAP), "no data/amherst_map.json yet (run tools/fetch_osm.py --convert)")
class RealAmherstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World.load(REAL_MAP)
        cls.graph = RoadGraph(cls.world.roads)

    def test_highlanders_mural_is_at_ratchford_and_havelock(self):
        """The North Nova Scotia Highlanders mural is on the wall facing the corner of Ratchford and Havelock Streets
        (Veterans Affairs Canada's memorial inventory, GPS 45.8341327, -64.21131), not on the Dominion Building."""
        import json
        from game import mapedits
        with open(REAL_MAP) as f:
            px, py = mapedits._project(json.load(f)["meta"], 45.8341327, -64.21131)
        found = [b for b in self.world.buildings if (b.get("mural") or {}).get("design") == "highlanders"]
        self.assertEqual(len(found), 1)
        b = found[0]
        self.assertNotEqual(b.get("label"), "Dominion Building")
        m, pts = b["mural"], [tuple(p) for p in b["points"]]
        area = sum(pts[k][0] * pts[k - 1][1] - pts[k - 1][0] * pts[k][1] for k in range(len(pts)))
        fx, fy = math.sin(math.radians(m["facing"])), -math.cos(math.radians(m["facing"]))
        walls = []
        for a, c in zip(pts, pts[1:] + pts[:1]):   # outward normals (render3d's rule), as the renderer picks the wall
            L = math.hypot(c[0] - a[0], c[1] - a[1]) or 1.0
            nx, ny = ((c[1] - a[1]) / L, -(c[0] - a[0]) / L) if area < 0 else (-(c[1] - a[1]) / L, (c[0] - a[0]) / L)
            walls.append((a, c, nx, ny))
        a, c, nx, ny = max(walls, key=lambda w: w[2] * fx + w[3] * fy)
        mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
        self.assertGreater((px - mx) * nx + (py - my) * ny, 0, "the listed spot is not in front of the painted wall")
        self.assertLess(math.hypot(px - mx, py - my), 20.0, "the painted wall is not at the listed corner")

    def test_spawn_is_on_a_road(self):
        x, y, _h = self.world.spawn()
        self.assertTrue(self.world.on_road(x, y))

    def test_most_of_town_is_reachable(self):
        g = self.graph
        x, y, _h = self.world.spawn()
        seen, stack = set(), [g.nearest_node(x, y, 80.0)]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(g.edges[e].b for e in g.out[n])
        self.assertGreater(len(seen) / len(g.nodes), 0.8)

    def test_hubs_are_on_proper_streets(self):
        ms = MissionManager(self.world, Town(self.world, graph=self.graph, traffic=0))
        self.assertTrue(ms.hubs, "no job hubs on the real map - check the converter's landmark report")
        for h in ms.hubs:
            n = self.graph.nearest_node(h.x, h.y, 200.0)
            self.assertLess(math.hypot(self.graph.nodes[n][0] - h.x, self.graph.nodes[n][1] - h.y), 40.0, h.label)

    def test_houses_mostly_low(self):
        r = R.Renderer3D(self.world, style="street")
        heights = [b[2] for b in r.buildings.values()]
        low = sum(1 for h in heights if h <= 9.0) / len(heights)
        self.assertGreater(low, 0.7)


if __name__ == "__main__":
    unittest.main()
