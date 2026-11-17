"""Tests for the heritage-building details: shop fronts, church tower types, a clock tower on any building, and the
hand-edit fields that set them (map_edits.json).

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import sys
import types
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

import make_sample_map  # noqa: E402
from game import config as C  # noqa: E402
from game import mapedits  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World  # noqa: E402


def block(x0, y0, w, d, **extra):
    b = {"points": [[x0, y0], [x0 + w, y0], [x0 + w, y0 + d], [x0, y0 + d]], "tags": {"building": "yes"}, "height": 11.0}
    b.update(extra)
    return b


class HeritageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        data = make_sample_map.build()
        data["roads"] = [{"type": "main", "width": 10, "name": "Victoria St E", "points": [[-300, 0], [300, 0]]}]
        data["buildings"] = [
            block(-10, 7, 20, 14, material="sandstone", storeys=3),                     # 0 downtown block on the street
            block(40, 40, 20, 14, material="sandstone"),                                 # 1 set back: no shop front
            block(-60, 7, 30, 18, material="sandstone", landmark="church", steeple="turret"),
            block(-110, 7, 30, 18, material="sandstone", landmark="church", steeple="twin"),
            block(-160, 7, 30, 18, material="brick", landmark="church", steeple="none"),
            block(80, 7, 24, 16, material="sandstone", landmark="civic", tower=True),   # 5 clock tower on a civic building
        ]
        cls.world = World(data)
        cls.r = R.Renderer3D(cls.world, style="street")

    def test_shop_front_only_on_the_street_side_of_downtown_blocks(self):
        walls = self.r.buildings[0][4]
        shops = self.r._shop_walls(0)
        self.assertEqual(len(shops), 1)
        k = next(iter(shops))
        self.assertAlmostEqual((walls[k][1] + walls[k][3]) / 2, 7.0)                   # the wall facing the road
        self.assertEqual(self.r._shop_walls(1), set())
        self.assertEqual(self.r._shop_walls(2), set())                                 # landmarks keep their look

    def test_shop_front_draws_glass_sign_and_three_storeys(self):
        drawn = []
        self.r._poly = lambda surf, pts, rgb, ink=None: drawn.append((pts, rgb))
        try:
            self.r.cx, self.r.cy, self.r.cz = 0.0, -30.0, 2.0
            ex = self.r.extras[0]
            self.r._draw_shop_front(None, 0, ex, 10.0, 7.0, -10.0, 7.0, 11.0, 3, 0, None)
        finally:
            del self.r._poly
        hs = self.r.st["house"]
        glass = self.r.col(hs["glass"], 3, 0)
        tops = sorted({round(max(p[2] for p in pts), 2) for pts, rgb in drawn if rgb == glass})
        self.assertIn(2.8, tops)                                                        # display windows
        self.assertTrue(any(t > 6.0 for t in tops) and any(4.0 < t < 6.5 for t in tops))   # two upper storeys
        signs = {self.r.col(c, 3, 0) for c in hs["signs"]}
        self.assertTrue(any(rgb in signs for _p, rgb in drawn))

    def test_tower_types_draw(self):
        counts = {}
        for idx, name in ((2, "turret"), (3, "twin"), (4, "none"), (5, "clock")):
            boxes = []
            orig = self.r._draw_box
            self.r._draw_box = lambda *a, **k: boxes.append(a)
            self.r._draw_frustum = lambda *a, **k: boxes.append(("cap",) + a)
            try:
                self.r._set_camera(types.SimpleNamespace(x=0.0, y=-80.0, z=40.0, yaw=math.pi / 2, pitch=0.35))
                self.r._draw_building_top(pygame.Surface((C.INTERNAL_W, C.INTERNAL_H)), idx, 50.0)
            finally:
                self.r._draw_box = orig
                del self.r._draw_frustum
            counts[name] = (len(boxes), sum(1 for b in boxes if b and b[0] == "cap"))
        self.assertEqual(counts["none"], (0, 0))
        self.assertEqual(counts["twin"][1], 2)                                         # two pointed caps
        self.assertGreaterEqual(counts["turret"][0], 9)                                 # tower + 8 merlons, no cap
        self.assertEqual(counts["turret"][1], 0)
        self.assertGreaterEqual(counts["clock"][0], 2)                                  # the clock tower, off the courthouse

    def test_whole_frames_render(self):
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        for x, h in ((0.0, math.pi / 2), (-90.0, math.pi / 2), (90.0, math.pi / 2)):
            car = Car(x, -30.0, h)
            cam = R.ChaseCamera(car, self.world)
            for _ in range(30):
                cam.update(car, 1 / 30)
            R.Renderer3D(self.world, style="retro").render(surf, car, cam)
            self.r.render(surf, car, cam)

    def test_hand_edit_fields(self):
        data = {"meta": {}, "roads": [], "buildings": [block(0, 0, 10, 10)]}
        mapedits.apply(data, {"buildings": {"replace": [{"at": [5, 5], "tower": True, "steeple": "twin", "storeys": 2,
                                                         "shopfront": True}]}})
        b = data["buildings"][0]
        self.assertEqual((b["tower"], b["steeple"], b["storeys"], b["shopfront"]), (True, "twin", 2, True))


if __name__ == "__main__":
    unittest.main()


class NewPartsTests(unittest.TestCase):
    """Towers, cone roofs, dormers, wrap-around verandas and plinths (used for the photographed buildings)."""

    def test_polygon_footprint_and_cone_roof(self):
        from game import builder as B
        b, warn = B.make_building({"x": 0, "y": 0, "facing": 0, "width": 4.0, "sides": 8, "height": 9.0, "roof": "cone",
                                   "roof_height": 4.0}, {"bounds": [-9, -9, 9, 9]}, [])
        self.assertEqual(len(b["points"]), 8)
        self.assertTrue(all(abs(math.hypot(*p) - 2.0) < 0.02 for p in b["points"]))
        faces = B.roof_faces([tuple(p) for p in b["points"]], 9.0, "cone", 4.0)
        self.assertEqual(len(faces), 8)
        self.assertTrue(all(f[2][2] == 13.0 for f in faces))
        self.assertEqual(warn, [])

    def test_pass_through_fields(self):
        from game import builder as B
        b, _ = B.make_building({"x": 0, "y": 0, "facing": 0, "dormers": 2, "plinth": [250, 250, 250], "arch": "cape",
                                "storeys": 3, "tower": True, "steeple": "twin"}, {"bounds": [-9, -9, 9, 9]}, [])
        self.assertEqual((b["dormers"], b["plinth"], b["arch"], b["storeys"], b["tower"], b["steeple"]),
                         (2, [250, 250, 250], "cape", 3, True, "twin"))
        data = {"meta": {}, "roads": [], "buildings": [block(0, 0, 10, 10)]}
        mapedits.apply(data, {"buildings": {"replace": [{"at": [5, 5], "dormers": 3, "plinth": [1, 2, 3]}]}})
        self.assertEqual((data["buildings"][0]["dormers"], data["buildings"][0]["plinth"]), (3, [1, 2, 3]))

    def test_wrap_veranda_type(self):
        from game import archetypes as A
        info = A.classify({"points": [[0, 0], [10, 0], [10, 8], [0, 8]], "arch": "two_storey+wrap"})
        self.assertTrue(info["porch"] and info["wrap"])
        self.assertFalse(A.classify({"points": [[0, 0], [10, 0], [10, 8], [0, 8]], "arch": "two_storey+porch"})["wrap"])

    def test_dormers_wrap_porch_and_plinth_draw(self):
        pygame.init()
        data = make_sample_map.build()
        data["roads"] = [{"type": "side", "width": 8, "name": "Elm St", "points": [[-200, 0], [200, 0]]}]
        data["buildings"] = [
            {"points": [[-6, 10], [6, 10], [6, 19], [-6, 19]], "tags": {"building": "house"}, "height": 5.0, "roof": "gable",
             "roof_height": 4.0, "colour": [200, 200, 220], "material": "clapboard", "dormers": 2, "arch": "two_storey+wrap"},
            {"points": [[30, 10], [60, 10], [60, 25], [30, 25]], "tags": {"building": "yes"}, "height": 9.0,
             "material": "brick", "landmark": "civic", "plinth": [240, 240, 236]},
        ]
        world = World(data)
        r = R.Renderer3D(world, style="street")
        house = r._house(0)
        self.assertIsNotNone(house["wrap_wall"])
        self.assertNotEqual(house["wrap_wall"], house["front"])
        fr = r._dormer_frame(0, r.buildings[0], r.extras[0])
        self.assertGreater(fr[5], 0.5)                                          # dormers on the street side (south = +y)
        drawn = []
        orig = r._poly
        r._poly = lambda surf, pts, rgb, ink=None: (drawn.append(rgb), orig(surf, pts, rgb, ink))
        car = Car(-2.0, -8.0, math.pi / 2 - 0.3)
        cam = R.ChaseCamera(car, world)
        for _ in range(40):
            cam.update(car, 1 / 30)
        r.render(pygame.Surface((C.INTERNAL_W, C.INTERNAL_H)), car, cam)
        glass = {r.col(r.st["house"]["glass"], s, f) for s in range(4) for f in range(3)}
        self.assertTrue(set(drawn) & glass)
        plinth = {r.col((240, 240, 236), s, f) for s in range(4) for f in range(4)}
        car2 = Car(45.0, -15.0, math.pi / 2)
        cam2 = R.ChaseCamera(car2, world)
        for _ in range(40):
            cam2.update(car2, 1 / 30)
        drawn.clear()
        r.render(pygame.Surface((C.INTERNAL_W, C.INTERNAL_H)), car2, cam2)
        self.assertTrue(set(drawn) & plinth, "no plinth band on the civic building")
