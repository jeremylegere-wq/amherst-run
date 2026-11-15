"""GTA-style minimap, street names, speed-limit lookup."""
import json
import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game import config as C
from game.car import Car
from game.minimap import SIZE, Minimap, StreetTracker, road_limit, rotation_degrees, street_labels
from game.world import World

ROADS = [
    {"type": "side", "width": 8, "name": "Elm St", "speed": 50, "points": [[-200, 0], [200, 0]]},
    {"type": "main", "width": 9, "name": "Highway 104", "speed": 100, "points": [[0, -200], [0, 200]]},
    {"type": "lane", "width": 4, "name": "", "points": [[50, 0], [50, 60]]},
]


def world():
    return World({"meta": {"bounds": [-300, -300, 300, 300], "procedural_props": False},
                  "roads": json.loads(json.dumps(ROADS)), "buildings": []})


class Streets(unittest.TestCase):
    def test_name_and_limit_under_car(self):
        w = world()
        t = StreetTracker()
        t.update(w, Car(-100, 0, 0), 0.1)
        self.assertEqual((t.name, t.limit), ("Elm St", 50))
        t.update(w, Car(0, 100, 0), 0.1)
        self.assertEqual((t.name, t.limit), ("Highway 104", 100))

    def test_name_held_briefly_when_road_is_unnamed_then_cleared(self):
        w = world()
        t = StreetTracker()
        t.update(w, Car(-100, 0, 0), 0.1)
        t.update(w, Car(-100, 100, 0), 0.5)                   # off every road
        self.assertEqual(t.name, "Elm St")
        t.update(w, Car(-100, 100, 0), 2.0)
        self.assertEqual(t.name, "")
        self.assertIsNone(t.limit)

    def test_limit_fallback_by_class(self):
        self.assertEqual(road_limit({"type": "lane"}), 30)
        self.assertEqual(road_limit({"type": "main", "speed": 80}), 80)


class MinimapDraw(unittest.TestCase):
    def test_rotation_points_heading_up(self):
        self.assertAlmostEqual(rotation_degrees(0.0), 90.0)                 # facing east -> east becomes up
        self.assertAlmostEqual(rotation_degrees(math.pi / 2), 180.0)        # facing south -> south becomes up

    def test_draws_roads_in_a_circle(self):
        pygame.init()
        w = world()
        mm = Minimap(w, pygame.font.Font(None, 13))
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        surf.fill((0, 255, 0))

        class Town:
            time = 0.0
            cars = []
        mm.draw(surf, (10, 10), Car(0, 0, 0), Town(), [])
        self.assertEqual(surf.get_at((10, 10))[:3], (0, 255, 0))             # corner of the square is outside the circle
        inside = {tuple(surf.get_at((10 + x, 10 + y))[:3]) for x in range(8, SIZE - 8) for y in range(8, SIZE - 8)}
        self.assertTrue(any(c[0] > 200 and c[1] > 200 and c[2] > 200 for c in inside))   # a road ribbon is drawn

    def test_overview_labels_do_not_overlap(self):
        pygame.init()
        w = world()
        taken = []
        font = pygame.font.Font(None, 13)
        labels = street_labels(w, lambda p: (p[0] * 0.5 + 160, p[1] * 0.4 + 90), font, taken, pygame.Rect(0, 0, 320, 180))
        self.assertEqual([n for n, _ in labels], ["Highway 104"])           # both centre on (0, 0): the bigger road wins
        rects = [pygame.Rect(pos, font.size(n)) for n, pos in labels]
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertFalse(a.colliderect(b))

    def test_real_map_names_most_main_streets(self):
        w = World.load("data/amherst_map.json")
        named = sum(1 for r in w.roads if r["type"] in ("main", "side") and r["name"])
        total = sum(1 for r in w.roads if r["type"] in ("main", "side"))
        self.assertGreater(named / total, 0.8)


if __name__ == "__main__":
    unittest.main()
