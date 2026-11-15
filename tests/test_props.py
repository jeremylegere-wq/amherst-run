"""Tests for street props (trees, lamps), graffiti tags and cartoon cars.

Run from the project root:  python -m unittest discover -s tests -v
"""
import io
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
import make_sample_map  # noqa: E402
import osm_to_map  # noqa: E402
from game import props as P  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import Car  # noqa: E402
from game.collision import car_hits_world, move_and_slide  # noqa: E402
from game.world import World  # noqa: E402


def colours(surf):
    return {tuple(surf.get_at((x, y)))[:3] for x in range(surf.get_width()) for y in range(surf.get_height())}


def free_spot(world):
    """A point well away from roads, buildings, water and rail."""
    for x in range(-260, 260, 3):
        for y in range(-260, 260, 3):
            if P._site_ok(world, x, y, 4.0, 2.0):
                return float(x), float(y)
    raise AssertionError("no free spot in the sample town")


class PropPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(make_sample_map.build())

    def test_town_gets_trees_and_lamps(self):
        kinds = [p["kind"] for p in self.world.props]
        self.assertGreater(kinds.count("tree"), 100)
        self.assertGreater(kinds.count("lamp"), 3)

    def test_props_keep_off_roads_and_out_of_buildings(self):
        for p in self.world.props:
            clear = P.TREE_CLEAR if p["kind"] == "tree" else P.LAMP_CLEAR
            self.assertGreaterEqual(self.world.road_clearance(p["x"], p["y"]), clear - 0.01)
            self.assertFalse(self.world.in_building(p["x"], p["y"]))

    def test_props_are_spaced_out(self):
        pts = [(p["x"], p["y"]) for p in self.world.props]
        for x, y in pts:
            near =[q for q in self.world.props_near(x, y, P.MIN_GAP) if (q["x"], q["y"]) != (x, y)]
            for q in near:
                self.assertGreaterEqual(math.hypot(q["x"] - x, q["y"] - y), P.MIN_GAP - 0.05)

    def test_same_map_same_props(self):
        again = World(make_sample_map.build())
        self.assertEqual(self.world.props, again.props)

    def test_procedural_props_can_be_turned_off(self):
        data = make_sample_map.build(demo=False)
        data["meta"]["procedural_props"] = False
        self.assertEqual(World(data).props, [])

    def test_osm_trees_are_kept_and_bad_ones_dropped(self):
        data = make_sample_map.build(demo=False)
        data["meta"]["procedural_props"] = False
        x, y = free_spot(World(data))
        data["props"] = [{"kind": "tree", "x": x, "y": y},
                         {"kind": "tree", "x": 0.0, "y": 0.0},           # in the middle of Main St
                         {"kind": "bench", "x": x + 10, "y": y}]         # unknown kind
        w = World(data)
        self.assertEqual(len(w.props), 1)
        self.assertAlmostEqual(w.props[0]["x"], x)
        self.assertEqual(w.props[0]["kind"], "tree")

    def test_road_clearance_sign(self):
        self.assertLess(self.world.road_clearance(0.0, 0.0), 0)      # on a road
        x, y = free_spot(self.world)
        self.assertGreater(self.world.road_clearance(x, y), 0)


class PropCollisionTests(unittest.TestCase):
    def setUp(self):
        data = make_sample_map.build(demo=False)
        data["meta"]["procedural_props"] = False
        w = World(data)
        self.x, self.y = free_spot(w)
        data["props"] = [{"kind": "tree", "x": self.x, "y": self.y}]
        self.world = World(data)

    def test_car_overlapping_a_trunk_hits_it(self):
        self.assertTrue(car_hits_world(Car(self.x - 2.3, self.y, 0.0), self.world))   # front bumper at the trunk
        self.assertFalse(car_hits_world(Car(self.x - 3.5, self.y, 0.0), self.world))
        self.assertFalse(car_hits_world(Car(self.x, self.y + 2.0, 0.0), self.world))  # passing beside it

    def test_driving_into_a_tree_stops_the_car(self):
        car = Car(self.x - 6.0, self.y, 0.0)
        car.vx = 15.0
        hit = 0.0
        for _ in range(60):
            px, py = car.x, car.y
            car.update(1 / 60, True, False, 0.0, False, False)
            hit = max(hit, move_and_slide(car, self.world, px, py, thorough=True))
        self.assertGreater(hit, 3.0)
        self.assertLess(car.x, self.x - 2.0)            # never passed through the trunk


class ConverterPropTests(unittest.TestCase):
    def test_tree_and_lamp_nodes_become_props(self):
        osm = b"""<?xml version='1.0'?>
        <osm version='0.6'>
          <bounds minlat='45.80' minlon='-64.22' maxlat='45.82' maxlon='-64.20'/>
          <node id='1' lat='45.810' lon='-64.210'/><node id='2' lat='45.810' lon='-64.205'/>
          <node id='7' lat='45.8105' lon='-64.207'><tag k='natural' v='tree'/></node>
          <node id='8' lat='45.8102' lon='-64.208'><tag k='highway' v='street_lamp'/></node>
          <node id='9' lat='45.8103' lon='-64.209'><tag k='amenity' v='bench'/></node>
          <way id='10'><nd ref='1'/><nd ref='2'/><tag k='highway' v='residential'/></way>
        </osm>"""
        data = osm_to_map.convert(io.BytesIO(osm))
        self.assertEqual(sorted(p["kind"] for p in data["props"]), ["lamp", "tree"])

    def test_fetch_query_asks_for_trees_and_lamps(self):
        q = fetch_osm.build_query((45.80, -64.25, 45.84, -64.18))
        self.assertIn('node["natural"="tree"]', q)
        self.assertIn('node["highway"="street_lamp"]', q)


class StreetCharmRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.world = World(make_sample_map.build())

    def test_graffiti_only_in_street_style_and_deterministic(self):
        street = R.Renderer3D(self.world, style="street")
        self.assertGreater(sum(len(v) for v in street.graffiti.values()), 20)
        self.assertEqual(R.Renderer3D(self.world, style="retro").graffiti, {})
        again = R.Renderer3D(self.world, style="street")
        self.assertEqual(street.graffiti, again.graffiti)
        for tags in street.graffiti.values():
            for shapes in tags.values():
                self.assertTrue(4 <= len(shapes) <= 6)              # back plate + 3-5 letters
                self.assertNotEqual(shapes[0][0], shapes[1][0])     # letters contrast with the plate

    def test_tags_fit_on_their_wall(self):
        r = R.Renderer3D(self.world, style="street")
        for i, tags in r.graffiti.items():
            walls, h = r.buildings[i][4], r.buildings[i][2]
            for wi, shapes in tags.items():
                x0, y0, x1, y1 = walls[wi][:4]
                L = math.hypot(x1 - x0, y1 - y0)
                for _c, pts in shapes:
                    for u, v in pts:
                        self.assertTrue(-0.5 <= u <= L + 0.5)
                        self.assertLess(v, h)

    def test_trees_are_drawn(self):
        x, y, h = self.world.spawn()
        car = Car(x, y, h)
        cam = R.ChaseCamera(car, self.world)
        r = R.Renderer3D(self.world, style="street")
        surf = pygame.Surface((320, 224))
        r.render(surf, car, cam)
        lit = {c[0] for c in R.STYLES["street"]["tree_cols"]}
        self.assertTrue(lit & colours(surf))

    def test_cartoon_car_has_wheels_retro_car_does_not(self):
        car = Car(0.0, 0.0, 0.3)
        cam = R.ChaseCamera(car, self.world)
        cam.x, cam.y, cam.yaw = -6.5, -5.0, 0.62           # rear three-quarter view
        wheel = (26, 24, 34)
        shades = {tuple(int(v * m) for v in wheel) for m in set(R.STYLES["street"]["shade"])}
        for style, expect in (("street", True), ("retro", False)):
            r = R.Renderer3D(self.world, style=style)
            surf = pygame.Surface((320, 224))
            r.render(surf, car, cam)
            self.assertEqual(bool(shades & colours(surf)), expect, style)

    def test_frustum_cabin_visible_from_every_side(self):
        r = R.Renderer3D(self.world, style="street")
        surf = pygame.Surface((320, 224))
        car = Car(0.0, 0.0, 0.0)
        for k in range(8):
            cam = R.ChaseCamera(Car(0.0, 0.0, k * math.pi / 4), None)
            cam.x, cam.y = -math.cos(k * math.pi / 4) * 8, -math.sin(k * math.pi / 4) * 8
            r.render(surf, car, cam)
            self.assertGreater(r.polys, 10)


if __name__ == "__main__":
    unittest.main()
