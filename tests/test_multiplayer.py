import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from game import config as C  # noqa: E402
from game.car import MODELS, PLAYER_MODELS, Car, player_car  # noqa: E402
from game.collision import collide_cars  # noqa: E402
from game.twoplayer import layout  # noqa: E402

DT = 1.0 / 60.0


class Layouts(unittest.TestCase):
    def test_three_players_first_gets_top_half(self):
        r = layout(3)
        self.assertEqual(r[0], (0, 0, C.INTERNAL_W, C.INTERNAL_H // 2))
        self.assertEqual(r[1][1], C.INTERNAL_H // 2)
        self.assertEqual(r[2][0], C.INTERNAL_W // 2)

    def test_four_quarters_cover_screen(self):
        area = sum(w * h for _x, _y, w, h in layout(4))
        self.assertEqual(area, C.INTERNAL_W * C.INTERNAL_H)

    def test_two_halves(self):
        self.assertEqual([r[2] for r in layout(2)], [C.INTERNAL_W // 2] * 2)


class Vehicles(unittest.TestCase):
    def test_four_models_with_sizes(self):
        cars = [player_car(i) for i in range(4)]
        self.assertEqual([c.model for c in cars], list(PLAYER_MODELS))
        self.assertGreater(cars[3].length, cars[0].length)           # the pickup is the longest
        self.assertGreater(cars[3].mass, cars[1].mass)
        for m in PLAYER_MODELS:
            self.assertIn(m, MODELS)

    def test_player_cars_crashing_does_not_need_kind(self):
        a, b = player_car(0, 0, 0, 0.0), player_car(3, 3.0, 0, 0.0)
        a.vx = 15.0
        self.assertGreater(collide_cars(a, b), 0.0)
        self.assertEqual(a.kind, "player")

    def test_town_handles_player_vs_player_crash(self):
        from game.world import World
        from game.town import Town
        w = World.load(os.path.join(os.path.dirname(__file__), "..", "data", "sample_map.json"))
        t = Town(w, seed=1, traffic=0, cops=False)
        a, b = player_car(0, 0, 0, 0.0), player_car(1, 2.5, 0, 0.0)
        a.vx = 20.0
        t.extra = [b]
        t.update(0.05, a, 0.0)                                         # used to raise AttributeError ('kind')


class HopAndDrift(unittest.TestCase):
    def cruise(self, car, seconds=4.0):
        for _ in range(int(seconds / DT)):
            car.update(DT, True, False, 0.0, False, True)

    def test_hop_lifts_the_car_and_lands(self):
        c = player_car(0)
        self.cruise(c)
        peak = 0.0
        for i in range(40):
            c.update(DT, True, False, 0.0, False, True, bumper=(i < 3))
            peak = max(peak, c.hop_z)
        self.assertGreater(peak, 0.2)
        self.assertEqual(c.hop_z, 0.0)

    def test_hop_steering_starts_drift_and_release_boosts(self):
        c = player_car(1)
        self.cruise(c)
        base = c.speed
        for _ in range(int(2.0 / DT)):                                 # hold bumper + steer right: charge the slide
            c.update(DT, True, False, 1.0, False, True, bumper=True)
        self.assertEqual(c.drift, 1)
        self.assertGreaterEqual(c.charge_level, 2)
        for _ in range(3):
            c.update(DT, True, False, 0.0, False, True, bumper=False)  # let go
        self.assertEqual(c.drift, 0)
        self.assertGreater(c.boost_t, 0.5)
        for _ in range(int(1.0 / DT)):
            c.update(DT, True, False, 0.0, False, True, bumper=False)
        self.assertGreater(c.speed, base * 1.05)                       # faster than normal top speed

    def test_slow_hop_makes_no_drift(self):
        c = player_car(2)
        c.vx = 5.0
        for _ in range(30):
            c.update(DT, False, False, 1.0, False, True, bumper=True)
        self.assertEqual(c.drift, 0)

    def test_drift_turns_sharper_than_plain_steering(self):
        a, b = player_car(0), player_car(0)
        self.cruise(a), self.cruise(b)
        for _ in range(90):
            a.update(DT, True, False, 1.0, False, True, bumper=True)
            b.update(DT, True, False, 1.0, False, True, bumper=False)
        self.assertGreater(abs(a.heading), abs(b.heading))


class Flow(unittest.TestCase):
    def test_modes_run_headless(self):
        from game.main import Game
        from game.world import World
        w = World.load(os.path.join(os.path.dirname(__file__), "..", "data", "sample_map.json"))
        for mode in ("2p", "3p", "4p"):
            g = Game(w, 1, deterministic=True, traffic=8, no_joy=True)
            g.run(frames=40, mode=mode)
            pygame.init()


if __name__ == "__main__":
    unittest.main()
