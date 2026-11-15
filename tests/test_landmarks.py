"""Tests for real-world landmarks: matching, decoration and drawing.

Run from the project root:  python -m unittest discover -s tests -v
"""
import copy
import io
import json
import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

import fetch_osm  # noqa: E402
import landmarks as LM  # noqa: E402
import make_sample_map  # noqa: E402
import osm_to_map  # noqa: E402
from game import config as C  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World  # noqa: E402


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def tiny_map():
    return {
        "meta": {"bounds": [-300, -300, 300, 300]},
        "roads": [{"type": "main", "width": 11, "points": [[-300, 0], [300, 0]]}],
        "buildings": [
            {"points": rect(20, -40, 50, -15), "tags": {"name": "Old Court House"}},
            {"points": rect(-60, -40, -40, -15), "tags": {"name": "St Somebody", "amenity": "place_of_worship"}},
            {"points": rect(-120, -40, -100, -15), "tags": {"name": "Other Church", "amenity": "place_of_worship"}},
            {"points": rect(100, 15, 130, 40)},                                   # unnamed
            {"points": rect(200, 15, 230, 40), "tags": {"name": "Visitor Information Centre", "tourism": "information"}},
        ],
        "parks": [{"name": "Victoria Square", "points": rect(-30, 15, 10, 55)}],
        "memorials": [{"name": "War Memorial", "x": -5.0, "y": 30.0}],
    }


class MatchingTests(unittest.TestCase):
    def test_building_found_by_name(self):
        data = tiny_map()
        report = LM.apply_landmarks(data, {"landmarks": [
            {"id": "ch", "kind": "courthouse", "names": ["court house"], "near_xy": [0, 0], "search": 200,
             "material": "sandstone", "tower": False}]})
        b = data["buildings"][0]
        self.assertEqual((b["landmark"], b["material"], b["tower"]), ("courthouse", "sandstone", False))
        self.assertIn("by name/tags", report[0])

    def test_falls_back_to_nearest_building_then_gives_up(self):
        data = tiny_map()
        LM.apply_landmarks(data, {"landmarks": [{"id": "x", "kind": "civic", "names": ["nope"], "near_xy": [115, 30]}]})
        self.assertEqual(data["buildings"][3]["landmark"], "civic")
        data = tiny_map()
        report = LM.apply_landmarks(data, {"landmarks": [{"id": "x", "kind": "civic", "names": ["nope"],
                                                          "near_xy": [115, 200]}]})
        self.assertIn("NOT FOUND", report[0])
        self.assertFalse(any("landmark" in b for b in data["buildings"]))

    def test_fallback_hub_only_when_the_role_is_still_free(self):
        spec = {"landmarks": [
            {"id": "hub", "kind": "civic", "names": ["court house"], "near_xy": [0, 0], "search": 200, "role": "deliveries"},
            {"id": "any", "kind": "civic", "names": ["visitor"], "near_xy": [0, 0], "search": 500, "role": "deliveries",
             "only_if_no_role": True}]}
        data = tiny_map()
        report = LM.apply_landmarks(data, spec)
        self.assertEqual([b.get("role") for b in data["buildings"]].count("deliveries"), 1)
        self.assertIn("skipped", report[1])
        data = tiny_map()
        LM.apply_landmarks(data, {"landmarks": spec["landmarks"][1:]})                 # no hub found: the fallback steps in
        self.assertEqual(data["buildings"][4].get("role"), "deliveries")

    def test_no_fallback_when_disabled(self):
        data = tiny_map()
        report = LM.apply_landmarks(data, {"landmarks": [{"id": "x", "kind": "civic", "names": ["nope"],
                                                          "near_xy": [115, 30], "fallback_nearest": False}]})
        self.assertIn("NOT FOUND", report[0])

    def test_all_matches_by_tag(self):
        data = tiny_map()
        LM.apply_landmarks(data, {"landmarks": [{"id": "churches", "kind": "church", "tags": {"amenity": "place_of_worship"},
                                                 "near_xy": [0, 0], "search": 500, "all": True}]})
        self.assertEqual([b.get("landmark") for b in data["buildings"]].count("church"), 2)

    def test_square_gets_cenotaph_on_memorial_trees_and_spawn(self):
        data = tiny_map()
        LM.apply_landmarks(data, {"landmarks": [{"id": "sq", "kind": "square", "names": ["victoria square"],
                                                 "near_xy": [0, 0], "search": 300, "trees": 6, "spawn": True}]})
        cen = [p for p in data["landmarks"] if p["kind"] == "cenotaph"]
        self.assertEqual((cen[0]["x"], cen[0]["y"]), (-5.0, 30.0))       # on the mapped memorial
        trees = [p for p in data["props"] if p["kind"] == "tree"]
        self.assertTrue(4 <= len(trees) <= 6)
        for t in trees:
            self.assertTrue(-30 <= t["x"] <= 10 and 15 <= t["y"] <= 55)
        x, y, h = data["meta"]["spawn"]
        self.assertAlmostEqual(y, 0.0)                                   # on Main St
        self.assertEqual(data["parks"][0]["landmark"], "square")

    def test_visitor_centre_gets_a_lighthouse_outside_it(self):
        data = tiny_map()
        LM.apply_landmarks(data, {"landmarks": [{"id": "vc", "kind": "visitor_centre", "names": ["visitor information"],
                                                 "near_xy": [0, 0], "search": 500}]})
        lh = [p for p in data["landmarks"] if p["kind"] == "lighthouse"][0]
        self.assertFalse(200 <= lh["x"] <= 230 and 15 <= lh["y"] <= 40)
        self.assertLess(math.hypot(lh["x"] - 215, lh["y"] - 27.5), 30)

    def test_wind_farm_and_district(self):
        data = tiny_map()
        LM.apply_landmarks(data, {"district": {"near_xy": [0, 0], "radius": 100},
                                  "landmarks": [{"id": "wf", "kind": "wind_farm", "at_xy": [2000, 0], "count": 7}]})
        turbines = [p for p in data["landmarks"] if p["kind"] == "turbine"]
        self.assertEqual(len(turbines), 7)
        self.assertTrue(all(1700 < t["x"] < 2300 for t in turbines))
        with_mat = [b for b in data["buildings"] if b.get("material")]
        self.assertEqual(len(with_mat), 2)                                # court house (44 m) and St Somebody (57 m)
        again = tiny_map()
        LM.apply_landmarks(again, {"district": {"near_xy": [0, 0], "radius": 100}})
        self.assertEqual([b.get("material") for b in again["buildings"]], [b.get("material") for b in data["buildings"]])

    def test_amherst_spec_file_is_valid(self):
        spec = LM.load_spec()
        ids = [l["id"] for l in spec["landmarks"]]
        self.assertEqual(len(ids), len(set(ids)))
        kinds = set(LM.BUILDING_KINDS) | {"square", "wind_farm", "lighthouse"}
        for l in spec["landmarks"]:
            self.assertIn(l["kind"], kinds)
            point = l.get("near") or l.get("at")
            self.assertTrue(45.7 < point[0] < 45.9 and -64.3 < point[1] < -64.1, l["id"])


class ConverterLandmarkTests(unittest.TestCase):
    OSM = b"""<?xml version='1.0'?><osm version='0.6'>
    <bounds minlat='45.830' minlon='-64.218' maxlat='45.836' maxlon='-64.208'/>
    <node id='1' lat='45.8330' lon='-64.2134'/><node id='2' lat='45.8330' lon='-64.2129'/>
    <node id='3' lat='45.8333' lon='-64.2129'/><node id='4' lat='45.8333' lon='-64.2134'/>
    <node id='5' lat='45.8325' lon='-64.2134'/><node id='6' lat='45.8325' lon='-64.2124'/>
    <node id='7' lat='45.8321' lon='-64.2124'/><node id='8' lat='45.8321' lon='-64.2134'/>
    <node id='9' lat='45.8323' lon='-64.2129'><tag k='historic' v='memorial'/><tag k='name' v='World Wars Memorial'/></node>
    <node id='10' lat='45.8328' lon='-64.2160'/><node id='11' lat='45.8328' lon='-64.2100'/>
    <way id='20'><nd ref='1'/><nd ref='2'/><nd ref='3'/><nd ref='4'/><nd ref='1'/><tag k='building' v='yes'/>
      <tag k='name' v='Old Court House'/><tag k='architect' v='dropped'/></way>
    <way id='21'><nd ref='5'/><nd ref='6'/><nd ref='7'/><nd ref='8'/><nd ref='5'/><tag k='leisure' v='park'/><tag k='name' v='Victoria Square'/></way>
    <way id='22'><nd ref='10'/><nd ref='11'/><tag k='highway' v='primary'/></way>
    </osm>"""

    def test_converter_keeps_tags_parks_and_memorials(self):
        data = osm_to_map.convert(io.BytesIO(self.OSM))
        self.assertEqual(data["buildings"][0]["tags"], {"name": "Old Court House", "building": "yes"})
        self.assertEqual(data["parks"][0]["name"], "Victoria Square")
        self.assertEqual(data["memorials"][0]["name"], "World Wars Memorial")
        self.assertNotIn("landmarks", data)                                # only applied when asked

    def test_converter_applies_the_amherst_spec(self):
        data = osm_to_map.convert(io.BytesIO(self.OSM), landmarks=LM.load_spec())
        self.assertEqual(data["buildings"][0]["landmark"], "courthouse")
        self.assertIn("spawn", data["meta"])
        kinds = {p["kind"] for p in data["landmarks"]}
        self.assertTrue({"cenotaph", "turbine"} <= kinds)
        World(data)                                                         # loads cleanly

    def test_fetch_query_asks_for_parks_and_memorials(self):
        q = fetch_osm.build_query((45.80, -64.25, 45.84, -64.18))
        self.assertIn('way["leisure"="park"]', q)
        self.assertIn('node["historic"="memorial"]', q)


class LandmarkWorldAndRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.data = make_sample_map.build()
        cls.world = World(copy.deepcopy(cls.data))

    def test_sample_town_has_a_downtown(self):
        report = self.data["meta"]["landmark_report"]
        self.assertFalse(any("NOT FOUND" in line for line in report), report)
        kinds = {b.get("landmark") for b in self.world.buildings}
        self.assertTrue({"courthouse", "church", "civic"} <= kinds)
        self.assertGreater(len(self.world.horizon), 5)
        self.assertTrue(any(p["kind"] == "cenotaph" for p in self.world.props))
        self.assertTrue(any(p["kind"] == "lighthouse" for p in self.world.props))
        self.assertTrue(all("bbox" in p for p in self.world.parks))

    def render(self, world, car, t=0.0, style="street"):
        r = R.Renderer3D(world, style=style)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        r.render(surf, car, R.ChaseCamera(car, world), t=t)
        return r, surf

    def test_court_house_tower_adds_detail_and_its_clock_moves(self):
        car = Car(-60.0, -30.6, 0.0)                        # west of court house, looking east (clear sightline)
        r1, s1 = self.render(self.world, car, t=0.0)
        r2, s2 = self.render(self.world, car, t=900.0)     # 15 in-game minutes later
        self.assertGreater(r1.polys, 40)
        diff = sum(1 for x in range(C.INTERNAL_W) for y in range(C.INTERNAL_H) if s1.get_at((x, y)) != s2.get_at((x, y)))
        self.assertGreater(diff, 0)
        data = copy.deepcopy(self.data)
        for b in data["buildings"]:
            b.pop("tower", None)
        r3, _ = self.render(World(data), car)
        self.assertGreater(r1.polys, r3.polys)

    def test_turbines_appear_on_the_skyline(self):
        car = Car(-180.0, 0.0, 0.0)                         # spawn, facing east towards the eastern farm
        _r, with_t = self.render(self.world, car, t=1.0)
        empty = copy.deepcopy(self.data)
        empty["landmarks"] = [l for l in empty["landmarks"] if l["kind"] != "turbine"]
        _r, without = self.render(World(empty), car, t=1.0)
        diff = sum(1 for x in range(320) for y in range(0, 120) if with_t.get_at((x, y)) != without.get_at((x, y)))
        self.assertGreater(diff, 20)

    def test_sandstone_district_colours(self):
        r = R.Renderer3D(self.world, style="street")
        sand = set(R.STYLES["street"]["materials"]["sandstone"]) | set(R.STYLES["street"]["materials"]["brick"])
        used = {r.buildings[i][3] for i, b in enumerate(self.world.buildings) if b.get("material") in ("sandstone", "brick")}
        self.assertTrue(used and used <= sand)

    def test_retro_style_also_draws_landmarks(self):
        car = Car(45.0, 8.0, -math.pi / 2)
        r, _ = self.render(self.world, car, style="retro")
        self.assertGreater(r.polys, 20)

    def test_overview_map_labels(self):
        from game.main import Game
        g = Game(self.world, 1, deterministic=True, traffic=0)
        g.overview = True
        g.draw()
        pygame.quit()


if __name__ == "__main__":
    unittest.main()
