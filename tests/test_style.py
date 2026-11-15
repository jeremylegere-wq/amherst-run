"""Tests for the render styles (retro / street) and the street HUD.

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
from game import config as C  # noqa: E402
from game import render3d as R  # noqa: E402
from game.ai import AICar, PAL_POLICE  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World  # noqa: E402


def colours(surf, y0=0, y1=None):
    y1 = y1 or surf.get_height()
    return {tuple(surf.get_at((x, y)))[:3] for x in range(0, surf.get_width()) for y in range(y0, y1)}


class StyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.world = World(make_sample_map.build())
        x, y, h = cls.world.spawn()
        cls.car = Car(x, y, h)
        cls.cam = R.ChaseCamera(cls.car, cls.world)
        cls.cop = AICar("police", PAL_POLICE, x + 15, y + 2.5, h + math.pi)

    def render(self, style, car=None, cam=None):
        r = R.Renderer3D(self.world, style=style)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        r.render(surf, car or self.car, cam or self.cam, others=[self.cop], t=0.0)
        return r, surf

    def test_unknown_style_is_rejected(self):
        with self.assertRaises(ValueError):
            R.Renderer3D(self.world, style="vaporwave")

    def test_retro_is_the_default_and_has_no_outlines(self):
        r = R.Renderer3D(self.world)
        self.assertEqual(r.style, "retro")
        _r, surf = self.render("retro")
        self.assertNotIn(R.STYLES["street"]["ink"], colours(surf))

    def test_street_draws_ink_outlines_and_more_detail(self):
        r_retro, _ = self.render("retro")
        r_street, surf = self.render("street")
        self.assertIn(R.STYLES["street"]["ink"], colours(surf))
        self.assertGreater(r_street.polys, r_retro.polys)       # window ribbons

    def test_street_has_clouds_whichever_way_you_look(self):
        for k in range(8):
            car = Car(0.0, 0.0, k * math.pi / 4)
            cam = R.ChaseCamera(car, None)
            _r, surf = self.render("street", car, cam)
            self.assertIn((255, 255, 255), colours(surf, 0, 100), f"no cloud at heading {k * 45} deg")

    def test_street_casts_see_through_shadows(self):
        r, _surf = self.render("street")
        self.assertIsNotNone(r._layer)
        self.assertGreater(pygame.mask.from_surface(r._layer, 1).count(), 50)   # alpha is ~120, so threshold 1

    def test_street_shading_is_two_tone(self):
        levels = set(R.STYLES["street"]["shade"])
        self.assertEqual(len(levels), 2)

    def test_style_does_not_change_projection_maths_for_retro(self):
        r = R.Renderer3D(self.world)
        self.assertAlmostEqual(r.focal, C.INTERNAL_W / 2 / math.tan(math.radians(R.FOV_DEG / 2)))

    def test_hull(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        moved = [(x + 5, y - 5) for x, y in sq]
        hull = R._hull(sq + moved)
        self.assertEqual(len(hull), 6)                            # square + its shifted copy -> hexagon
        self.assertEqual(sorted(R._hull(sq + [(5, 5)])), sorted(sq))  # inner point dropped

    def test_ink_fades_out_with_distance(self):
        r = R.Renderer3D(self.world, style="street")
        self.assertIsNotNone(r.ink(0))
        self.assertIsNone(r.ink(R.FOG_BANDS - 1))


class HudStyleTests(unittest.TestCase):
    def test_both_huds_draw_every_state(self):
        from game.main import Game
        world = World(make_sample_map.build())
        for style in ("street", "retro"):
            game = Game(world, 1, deterministic=True, traffic=4, seed=2, style=style)
            game.town.add_heat(3.0)
            game.town.damage = 80.0
            for state in ("playing", "busted", "wrecked"):
                game.town.state = state
                game.draw()
            game.view3d = False
            game.draw()
            game.overview = True
            game.draw()
        pygame.quit()


class WeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.world = World(make_sample_map.build())
        x, y, h = cls.world.spawn()
        cls.car = Car(x, y, h)
        cls.cam = R.ChaseCamera(cls.car, cls.world)
        cls.r = R.Renderer3D(cls.world, style="street")

    def shot(self, weather, t=0.0):
        self.r.set_weather(weather)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        self.r.render(surf, self.car, self.cam, t=t)
        return surf

    def test_unknown_weather_is_rejected(self):
        with self.assertRaises(ValueError):
            R.Renderer3D(self.world, style="street", weather="hurricane")

    def test_clear_is_the_plain_style(self):
        for style in R.STYLES:
            self.assertEqual(R.make_style(style, "clear"), R.STYLES[style])

    def test_every_preset_works_with_both_styles(self):
        for style in R.STYLES:
            for w in R.WEATHER:
                R.make_style(style, w)
        for w in R.WEATHER:
            self.assertGreater(len(colours(self.shot(w))), 8, w)

    def test_switching_matches_a_fresh_renderer(self):
        for w in ("snow", "golden", "clear"):
            self.r.set_weather(w)
            fresh = R.Renderer3D(self.world, style="street", weather=w)
            self.assertEqual(self.r.st, fresh.st)
            self.assertEqual(len(self.r.clouds), len(fresh.clouds))
            for i, ex in fresh.extras.items():
                self.assertEqual(self.r.extras[i].get("roof_colour"), ex.get("roof_colour"))

    def test_grade_tints_and_desaturates(self):
        self.assertEqual(R.grade_rgb((10, 20, 30), None), (10, 20, 30))
        grey = R.grade_rgb((200, 40, 40), ((1.0, 1.0, 1.0), 1.0))
        self.assertEqual(grey[0], grey[1])
        self.assertEqual(grey[1], grey[2])
        warm = R.grade_rgb((100, 100, 100), ((1.1, 0.95, 0.78), 0.0))
        self.assertGreater(warm[0], warm[2])

    def test_snow_whitens_the_grass_and_falls(self):
        a, b = self.shot("snow", t=0.0), self.shot("snow", t=1.0)
        snowy = {self.r.col(R.WEATHER["snow"]["grass"], 3, k) for k in range(R.FOG_BANDS)}
        self.assertTrue(snowy & colours(a), "no snow-covered ground on screen")
        self.assertNotEqual(pygame.image.tostring(a, "RGB"), pygame.image.tostring(b, "RGB"), "flakes did not move")

    def test_fog_hides_the_horizon(self):
        self.r.set_weather("fog")
        called = []
        orig = self.r._draw_horizon
        self.r._draw_horizon = lambda surf: called.append(1)
        try:
            self.shot("fog")
        finally:
            self.r._draw_horizon = orig
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
