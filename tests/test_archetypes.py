"""Tests for Amherst house types (game/archetypes.py) and the house details the renderer draws for them.

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

import pygame  # noqa: E402

import make_sample_map  # noqa: E402
from game import archetypes as A  # noqa: E402
from game import config as C  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World  # noqa: E402


def rect(w, d, x=0.0, y=0.0):
    return [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]


def house(w=10, d=8, h=4.5, rh=3.0, roof="gable", zone="R", **extra):
    b = {"points": rect(w, d), "tags": {"building": "yes"}, "height": h, "zone": zone, "material": "clapboard"}
    if roof:
        b.update(roof=roof, roof_height=rh)
    b.update(extra)
    return b


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(A.classify(house(w=6, d=5, h=2.6, roof=None))["kind"], "garage")
        self.assertEqual(A.classify(house(w=20, d=5, h=3.2, roof=None))["kind"], "minihome")
        self.assertEqual(A.classify(house(h=3.4, rh=1.0))["kind"], "bungalow")
        self.assertEqual(A.classify(house(h=4.6, rh=2.0))["kind"], "cape")
        self.assertEqual(A.classify(house(h=3.6, rh=2.5))["kind"], "cape")         # low walls but a steep roof
        two = A.classify(house(h=6.8, rh=2.5))
        self.assertEqual((two["kind"], two["storeys"]), ("two_storey", 2))
        self.assertEqual(A.classify(house(w=30, d=14, h=9.0, roof=None))["kind"], "apartment")

    def test_mini_home_zone(self):
        self.assertEqual(A.classify(house(h=3.3, zone="T"))["kind"], "minihome")

    def test_non_houses_are_left_alone(self):
        self.assertIsNone(A.classify(house(zone="H", material="brick")))
        self.assertIsNone(A.classify(house(landmark="church")))
        self.assertIsNone(A.classify(house(custom=True)))
        self.assertIsNone(A.classify(dict(house(), tags={"building": "retail"})))
        self.assertIsNone(A.classify(dict(house(), tags={"building": "yes", "amenity": "bank"})))
        self.assertIsNone(A.classify(house(material="sandstone")))

    def test_hand_set_type_wins(self):
        self.assertEqual(A.classify(house(h=8.0, arch="cape")), {"kind": "cape", "storeys": 1, "porch": False, "wrap": False})
        self.assertTrue(A.classify(house(arch="bungalow+porch"))["porch"])
        self.assertIsNone(A.classify(house(arch="castle")))

    def test_porches_are_stable_and_about_half_of_two_storey_homes(self):
        flags = [A.classify(house(h=7.0), i)["porch"] for i in range(400)]
        self.assertEqual(flags, [A.classify(house(h=7.0), i)["porch"] for i in range(400)])
        self.assertTrue(0.4 < sum(flags) / 400 < 0.7)

    def test_front_wall_faces_the_road(self):
        # outward normals of a 10 x 8 box: south wall (y=8) faces +y; a road runs along y = 20
        walls = [(0, 0, 10, 0, 0, -1), (10, 0, 10, 8, 1, 0), (10, 8, 0, 8, 0, 1), (0, 8, 0, 0, -1, 0)]
        self.assertEqual(A.front_wall(walls, lambda x, y: abs(y - 20) < 4), 2)
        self.assertEqual(A.front_wall(walls, lambda x, y: abs(x - 25) < 4), 1)
        self.assertIsNone(A.front_wall(walls, lambda x, y: False))


class HouseRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        data = make_sample_map.build()
        data["roads"] = [{"type": "side", "width": 8, "name": "Elm St", "points": [[-200, 0], [200, 0]]}]
        data["buildings"] = [{"points": [[-5, 10], [5, 10], [5, 18], [-5, 18]], "tags": {"building": "house"},
                              "height": 6.5, "zone": "R", "material": "clapboard", "colour": [180, 200, 230],
                              "roof": "gable", "roof_height": 3.0, "arch": "two_storey+porch"}]
        cls.world = World(data)

    def frame(self, x, y, heading, style="street"):
        r = R.Renderer3D(self.world, style=style)
        car = Car(x, y, heading)
        cam = R.ChaseCamera(car, self.world)
        for _ in range(40):
            cam.update(car, 1 / 30)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        r.render(surf, car, cam)
        return r, surf

    def colours(self, surf):
        return {tuple(surf.get_at((x, y)))[:3] for x in range(0, surf.get_width(), 2) for y in range(0, surf.get_height(), 2)}

    def test_house_gets_door_windows_porch_up_close_and_not_far_away(self):
        r, near = self.frame(-14.0, -6.0, math.radians(35))                 # on the street, looking at the house front
        house = r._house(0)
        self.assertEqual(house["front"] is not None and r.buildings[0][4][house["front"]][1], 10)   # the street side
        hs = r.st["house"]
        door = r.col(hs["doors"][0], 3, 0)
        trim_colours = {r.col(hs["trim"], s, f) for s in range(4) for f in range(2)}
        door_colours = {r.col(hs["doors"][0], s, f) for s in range(4) for f in range(2)}
        got = self.colours(near)
        self.assertTrue(got & door_colours, "no front door")
        self.assertTrue(got & trim_colours, "no window trim")
        self.assertIsNotNone(door)
        _r, far = self.frame(-14.0, -90.0, math.radians(80))                 # ~100 m away: plain look
        self.assertFalse(self.colours(far) & door_colours)

    def test_gable_end_is_wall_coloured(self):
        from game.builder import face_normal, roof_faces
        r, _ = self.frame(-30.0, 14.0, 0.0)
        faces = roof_faces([(0, 0), (10, 0), (10, 8), (0, 8)], 5.0, "gable", 3.0)
        faces = [(f, face_normal(f, (5, 4, 5))) for f in faces]
        drawn = []
        r._poly = lambda surf, pts, rgb, ink=None: drawn.append((len(pts), rgb))
        r.cx, r.cy, r.cz = -30.0, -40.0, 30.0                                # high up to the north-west: west gable + a slope
        r._draw_roof(None, faces, (60, 60, 70), 0, None, wall=(180, 200, 230), attic=True)
        wall = {r.col((180, 200, 230), s, 0) for s in range(4)}
        roof = {r.col((60, 60, 70), s, 0) for s in range(4)}
        tri = [rgb for n, rgb in drawn if n == 3]
        quads = [rgb for n, rgb in drawn if n == 4]
        self.assertTrue(tri and all(c in wall for c in tri))                  # gable triangles: siding
        self.assertTrue(any(c in roof for c in quads))                        # slopes: roof
        trim = {r.col(r.st["house"]["trim"], s, 0) for s in range(4)}
        glass = {r.col(r.st["house"]["glass"], s, 0) for s in range(4)}
        self.assertTrue(any(c in trim for c in quads) and any(c in glass for c in quads))   # the attic window

    def test_both_styles_and_all_weather_render_houses(self):
        for style in R.STYLES:
            r, _ = self.frame(-14.0, -6.0, math.radians(35), style)
            for w in R.WEATHER:
                r.set_weather(w)
                r.render(pygame.Surface((C.INTERNAL_W, C.INTERNAL_H)), Car(-14.0, -6.0, 0.6), R.ChaseCamera(Car(-14.0, -6.0, 0.6), self.world))

    def test_no_graffiti_on_family_homes(self):
        r, _ = self.frame(-14.0, -6.0, 0.6)
        self.assertNotIn(0, r.graffiti)


if __name__ == "__main__":
    unittest.main()
