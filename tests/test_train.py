"""The train: rail stitching, schedule, positions, collision and rendering."""
import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

from game import config as C  # noqa: E402
from game import render3d as R  # noqa: E402
from game import train as T  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World  # noqa: E402


def world_with_rails(rails):
    import make_sample_map
    data = make_sample_map.build()
    data["rails"] = rails
    return World(data)


LINE = [{"points": [[-1500.0, 300.0], [0.0, 300.0]]}, {"points": [[0.0, 300.0], [1500.0, 300.0]]},
        {"points": [[0.0, 300.0], [0.0, 900.0]]}]           # a branch that turns 90 degrees: not followed


class Stitch(unittest.TestCase):
    def test_ways_join_into_one_straight_chain(self):
        chain = T.stitch(LINE)
        xs = [p[0] for p in chain]
        self.assertAlmostEqual(abs(xs[-1] - xs[0]), 3000.0, delta=1.0)
        self.assertTrue(all(abs(p[1] - 300.0) < 1e-6 for p in chain))

    def test_no_rails_gives_no_train(self):
        w = world_with_rails([])
        t = T.Train(w)
        t.update(1000.0)
        self.assertFalse(t.active)
        self.assertEqual(t.units(), [])


class Running(unittest.TestCase):
    def setUp(self):
        self.t = T.Train(world_with_rails(LINE), seed=2)

    def test_first_train_comes_after_the_delay_then_clears_and_waits(self):
        t = self.t
        self.assertFalse(t.active)
        for _ in range(int(T.FIRST_DELAY[1] / 0.5) + 2):
            t.update(0.5)
        self.assertTrue(t.active)
        for _ in range(80):
            t.update(0.5)
        self.assertGreater(len(t.units()), 8)
        for _ in range(int(400 / 0.5)):
            t.update(0.5)
            if not t.active:
                break
        else:
            self.fail("the train never cleared the stretch")
        self.assertGreaterEqual(t.wait, T.GAP[0])          # a long gap before the next one

    def test_units_sit_on_the_track_and_face_along_it(self):
        t = self.t
        t.active, t.cars, t.dir, t.s = True, 6, 1, 600.0
        t._cache = None
        for u in t.units():
            self.assertAlmostEqual(u.y, 300.0, delta=0.5)
            self.assertAlmostEqual(math.cos(u.heading), 1.0, delta=0.01)

    def test_reverse_direction_faces_the_other_way(self):
        t = self.t
        t.active, t.cars, t.dir, t.s = True, 6, -1, 600.0
        t._cache = None
        self.assertAlmostEqual(math.cos(t.units()[0].heading), -1.0, delta=0.01)

    def test_a_car_inside_the_train_is_pushed_out_and_slowed(self):
        t = self.t
        t.active, t.cars, t.dir, t.s = True, 6, 1, 600.0
        t._cache = None
        u = t.units()[3]
        car = Car(u.x, u.y + 0.3, 0.0)
        car.vx = 15.0
        hit = t.push_out(car)
        self.assertAlmostEqual(hit, 15.0)
        self.assertGreater(abs(car.y - 300.0), T.HALF_W)
        self.assertLess(car.speed, 5.0)

    def test_a_car_beside_the_train_is_left_alone(self):
        t = self.t
        t.active, t.cars, t.dir, t.s = True, 6, 1, 600.0
        t._cache = None
        u = t.units()[3]
        car = Car(u.x, u.y + 12.0, 0.0)
        car.vx = 10.0
        self.assertEqual(t.push_out(car), 0.0)
        self.assertEqual(car.speed, 10.0)


class Drawing(unittest.TestCase):
    def test_renderer_draws_train_blocks(self):
        pygame.init()
        w = world_with_rails(LINE)
        t = T.Train(w, seed=2)
        t.active, t.cars, t.dir, t.s = True, 6, 1, 1560.0
        t._cache = None
        r = R.Renderer3D(w)
        car = Car(30.0, 280.0, 0.0)
        cam = R.ChaseCamera(car, w)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        r.render(surf, car, cam)
        without = r.polys
        r.render(surf, car, cam, trains=t.units())
        self.assertGreater(r.polys, without)


if __name__ == "__main__":
    unittest.main()
