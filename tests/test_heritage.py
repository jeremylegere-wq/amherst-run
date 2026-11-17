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
