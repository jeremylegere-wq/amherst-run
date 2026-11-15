"""Unit tests (stdlib unittest, no extra dependencies).

Run from the project root:  python -m unittest discover -s tests -v
"""
import io
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import osm_to_map  # noqa: E402
import make_sample_map  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World, point_in_polygon  # noqa: E402

SAMPLE_OSM = b"""<?xml version='1.0'?>
<osm version='0.6'>
  <bounds minlat='45.80' minlon='-64.22' maxlat='45.82' maxlon='-64.20'/>
  <node id='1' lat='45.810' lon='-64.210'/>
  <node id='2' lat='45.810' lon='-64.205'/>
  <node id='3' lat='45.811' lon='-64.205'/>
  <node id='4' lat='45.811' lon='-64.210'/>
  <node id='5' lat='45.812' lon='-64.215'/>
  <way id='10'><nd ref='1'/><nd ref='2'/><tag k='highway' v='primary'/><tag k='name' v='Test Rd'/></way>
  <way id='11'><nd ref='1'/><nd ref='2'/><nd ref='3'/><nd ref='4'/><nd ref='1'/><tag k='building' v='yes'/></way>
  <way id='12'><nd ref='1'/><nd ref='5'/><tag k='highway' v='footway'/></way>
  <way id='13'><nd ref='1'/><nd ref='5'/><tag k='railway' v='rail'/></way>
</osm>
"""


class OsmConverterTests(unittest.TestCase):
    def test_projection_scale(self):
        # 0.001 deg of latitude is about 111 m, and north is negative y
        x, y = osm_to_map.project(45.801, -64.21, 45.80, -64.21)
        self.assertAlmostEqual(x, 0.0, places=3)
        self.assertAlmostEqual(y, -111.2, delta=0.5)

    def test_simplify_drops_collinear_points(self):
        pts = [(0, 0), (5, 0.1), (10, 0)]
        self.assertEqual(len(osm_to_map.simplify(pts, 1.0)), 2)
        self.assertEqual(len(osm_to_map.simplify([(0, 0), (5, 5), (10, 0)], 1.0)), 3)

    def test_convert_classifies_features(self):
        data = osm_to_map.convert(io.BytesIO(SAMPLE_OSM))
        self.assertEqual(len(data["roads"]), 1)          # footway skipped
        self.assertEqual(data["roads"][0]["type"], "main")
        self.assertEqual(data["roads"][0]["name"], "Test Rd")
        self.assertEqual(len(data["buildings"]), 1)
        self.assertEqual(len(data["rails"]), 1)
        self.assertIn("OpenStreetMap", data["meta"]["attribution"])


class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(make_sample_map.build())

    def test_main_street_is_road(self):
        self.assertTrue(self.world.on_road(0, 0))
        self.assertFalse(self.world.on_road(40, 40))  # inside a block, off the streets

    def test_building_query(self):
        b = self.world.buildings[0]
        cx = sum(p[0] for p in b["points"]) / 4
        cy = sum(p[1] for p in b["points"]) / 4
        self.assertTrue(self.world.in_building(cx, cy))
        self.assertFalse(self.world.in_building(0, 0))

    def test_spawn_is_on_road(self):
        x, y, _ = self.world.spawn()
        self.assertTrue(self.world.on_road(x, y))

    def test_point_in_polygon(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertTrue(point_in_polygon(5, 5, sq))
        self.assertFalse(point_in_polygon(15, 5, sq))


class CarTests(unittest.TestCase):
    def test_accelerates_and_caps(self):
        car = Car()
        for _ in range(60 * 20):
            car.update(1 / 60, True, False, 0.0, False, True)
        self.assertGreater(car.speed, 30)
        self.assertLess(car.speed, 40)

    def test_brakes_to_stop(self):
        car = Car()
        for _ in range(60 * 5):
            car.update(1 / 60, True, False, 0.0, False, True)
        for _ in range(60 * 5):
            car.update(1 / 60, False, True, 0.0, False, True)
        self.assertLess(abs(car.forward_speed()), 12)  # braking then easing into reverse

    def test_no_steering_when_stationary(self):
        car = Car()
        for _ in range(60):
            car.update(1 / 60, False, False, 1.0, False, True)
        self.assertEqual(car.heading, 0.0)

    def test_steering_turns_clockwise_on_screen(self):
        car = Car()
        for _ in range(60 * 3):
            car.update(1 / 60, True, False, 1.0, False, True)
        self.assertGreater(car.heading, 0.5)
        self.assertGreater(car.y, 0)  # heading east + turning right means moving south (+y)

    def test_handbrake_creates_slide(self):
        grip, slide = Car(), Car()
        for c in (grip, slide):
            for _ in range(60 * 3):
                c.update(1 / 60, True, False, 0.0, False, True)
        for _ in range(30):
            grip.update(1 / 60, False, False, 1.0, False, True)
            slide.update(1 / 60, False, False, 1.0, True, True)
        def lateral(c):
            rx, ry = c.right
            return abs(c.vx * rx + c.vy * ry)
        self.assertGreater(lateral(slide), lateral(grip))

    def test_grass_is_slower(self):
        road, grass = Car(), Car()
        for _ in range(60 * 15):
            road.update(1 / 60, True, False, 0.0, False, True)
            grass.update(1 / 60, True, False, 0.0, False, False)
        self.assertGreater(road.speed, grass.speed * 1.8)


if __name__ == "__main__":
    unittest.main()
