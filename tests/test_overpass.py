"""Highway overpasses: deck heights, cars riding up ramps, level-aware collisions, rendering."""
import json
import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game import config as C
from game.car import Car
from game.collision import collide_cars, settle_height
from game.render3d import ChaseCamera, Renderer3D
from game.world import World, build_spans

# A flat road crossing a bridge road at the origin: the bridge carries a lift.
CROSS = [
    {"type": "main", "width": 9, "name": "Over St", "points": [[-200, 0], [-25, 0]]},
    {"type": "main", "width": 9, "name": "Over St", "points": [[-25, 0], [25, 0]], "bridge": True, "lift": 5.2},
    {"type": "main", "width": 9, "name": "Over St", "points": [[25, 0], [200, 0]]},
    {"type": "main", "width": 9, "name": "Under Rd", "points": [[0, -200], [0, 200]]},
]


def small_world():
    return World({"meta": {"bounds": [-300, -300, 300, 300], "procedural_props": False},
                  "roads": json.loads(json.dumps(CROSS)), "buildings": []})


class Spans(unittest.TestCase):
    def test_ramps_rise_smoothly_to_deck(self):
        sp = build_spans(json.loads(json.dumps(CROSS)))[0]
        self.assertEqual(sp["h"][0], 0.0)
        self.assertAlmostEqual(max(sp["h"]), 5.2)
        steps = [abs(b - a) for a, b in zip(sp["h"], sp["h"][1:])]
        self.assertLess(max(steps), 1.2)                      # no cliffs: a car can drive up it

    def test_height_on_deck_ramp_and_ground(self):
        w = small_world()
        self.assertAlmostEqual(w.height_at(0, 0, 5.0), 5.2, places=3)     # on the deck
        self.assertEqual(w.height_at(0, 0, 0.0), 0.0)                      # under it
        mid = w.height_at(-50, 0, 2.0)
        self.assertTrue(0.2 < mid < 5.2)                                   # on the ramp
        self.assertEqual(w.height_at(0, 50, 0.0), 0.0)                     # beside the deck

    def test_street_name_follows_level(self):
        w = small_world()
        self.assertEqual(w.road_at(0, 0, 5.2)["name"], "Over St")
        self.assertEqual(w.road_at(0, 0, 0.0)["name"], "Under Rd")

    def test_car_drives_up_over_and_down(self):
        w = small_world()
        car = Car(-190.0, 0.0, 0.0)
        top = 0.0
        for _ in range(900):
            car.x += 12.0 / 30.0
            settle_height(car, w, 1 / 30.0)
            top = max(top, car.z)
            if car.x > 190:
                break
        self.assertGreater(top, 5.0)
        self.assertLess(car.z, 0.3)

    def test_cars_on_different_levels_do_not_collide(self):
        a, b = Car(0, 0, 0), Car(0.5, 0, 0)
        b.z = 5.2
        self.assertEqual(collide_cars(a, b), 0.0)
        b.z = 0.0
        a.vx = 8.0
        self.assertGreater(collide_cars(a, b), 0.0)

    def test_real_map_has_the_interchanges(self):
        w = World.load("data/amherst_map.json")
        names = sorted({sp["road"]["name"] for sp in w.spans})
        self.assertIn("Highway 104", names)
        self.assertGreaterEqual(len(w.spans), 4)               # Exit 3, Exit 4 and the MacDonald Rd crossing
        for sp in w.spans:
            self.assertFalse(w._near_span(*sp["points"][len(sp["points"]) // 2], 0.0) is False)
        self.assertTrue(all(not w._near_span(p["x"], p["y"], 0.0) for p in w.props))


class Rendering(unittest.TestCase):
    def test_raised_car_and_camera_render(self):
        pygame.init()
        w = World.load("data/amherst_map.json")
        sp = w.spans[1]
        (ax, ay), (bx, by) = sp["points"][8], sp["points"][9]
        car = Car(ax, ay, math.atan2(by - ay, bx - ax))
        car.z = sp["h"][8]
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        for style in ("street", "retro"):
            r = Renderer3D(w, style)
            cam = ChaseCamera(car, w)
            self.assertGreater(cam.z, 5.0)                      # camera rides up with the car
            r.render(surf, car, cam, others=[])
            self.assertGreater(r.polys, 20)


if __name__ == "__main__":
    unittest.main()
