"""Battle and VS race (game/battle.py) and their items (game/items.py).

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import random
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

import make_sample_map  # noqa: E402
from game import battle as B  # noqa: E402
from game import items as I  # noqa: E402
from game import menu as MENU  # noqa: E402
from game.car import Car  # noqa: E402
from game.main import Game  # noqa: E402
from game.world import World  # noqa: E402

WORLD = World(make_sample_map.build())
IDLE = (False, False, 0.0, False, False, False)


class WallWorld:
    """A world that is open except for a wall x >= 10 (for bounce tests)."""

    def in_building(self, x, y):
        return x >= 10.0

    def in_bounds(self, x, y, margin=0.0):
        return abs(x) < 500 and abs(y) < 500


class ItemTests(unittest.TestCase):
    def test_pick_item_covers_every_item(self):
        rng = random.Random(1)
        self.assertEqual({I.pick_item(rng) for _ in range(500)}, set(I.ITEMS))

    def test_puck_bounces_off_a_wall_and_wears_out(self):
        shot = I.Shot("puck", 0.0, 0.0, 0.0, owner=0)              # heading +x, into the wall
        for _ in range(30):
            if I.step_shot(shot, WallWorld(), 1 / 60, []) != "fly":
                break
        self.assertLess(shot.vx, 0.0)                               # bounced back
        self.assertEqual(shot.bounces, 1)
        shot.bounces = I.PUCK_BOUNCES
        shot.x, shot.vx = 9.5, 30.0
        self.assertEqual(I.step_shot(shot, WallWorld(), 1 / 60, []), "gone")

    def test_seeker_turns_towards_its_target_and_hits(self):
        shot = I.Shot("seeker", 0.0, 0.0, 0.0, owner=0)
        target = Car(0.0, -30.0, 0.0)                               # north of it, while it flies east
        res = "fly"
        for _ in range(240):
            res = I.step_shot(shot, WallWorld(), 1 / 60, [(1, target)])
            if res != "fly":
                break
        self.assertEqual(res, ("hit", 1))

    def test_box_sites_are_spread_out_junctions(self):
        g = Game(WORLD, 2, deterministic=True, traffic=0).town.graph
        boxes = I.box_sites(g, (0.0, 0.0), 2000.0)
        self.assertGreater(len(boxes), 3)
        for a in boxes:
            for b in boxes:
                if a is not b:
                    self.assertGreaterEqual(math.hypot(a.x - b.x, a.y - b.y), I.BOX_SPACING - 1e-6)


class BattleTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(WORLD, 2, deterministic=True, traffic=0)
        self.game._begin("battle")
        self.b = self.game.two

    def step(self, n=1, inputs=None):
        for _ in range(n):
            self.b.step(1 / 60, inputs or [IDLE, IDLE])

    def face_off(self, gap=12.0):
        """Player 2 parked `gap` m in front of player 1, both stopped."""
        a, b = self.b.cars
        b.x, b.y = a.x + math.cos(a.heading) * gap, a.y + math.sin(a.heading) * gap
        for c in (a, b):
            c.vx = c.vy = 0.0

    def test_battle_starts_with_balloons_and_boxes(self):
        self.assertIsInstance(self.b, B.Battle)
        self.assertEqual([r.balloons for r in self.b.racers], [3, 3])
        self.assertTrue(self.b.boxes)
        self.assertEqual(len(self.b.rects), 2)
        self.assertEqual(self.b.rects[0][2], 320)                   # top/bottom split by default

    def test_tab_switches_the_split(self):
        self.b.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
        self.assertEqual(self.b.rects[0][3], 180)

    def test_box_gives_an_item_after_the_roulette(self):
        box = self.b.boxes[0]
        a = self.b.cars[0]
        a.x, a.y, a.vx, a.vy = box.x, box.y, 0.0, 0.0
        self.step()
        self.assertFalse(box.present)
        self.assertGreater(self.b.racers[0].roulette, 0.0)
        self.step(int(I.ROULETTE_TIME * 60) + 2)
        self.assertIn(self.b.racers[0].item, I.ITEMS)

    def test_puck_pops_a_balloon_and_spins_the_rival(self):
        self.face_off()
        self.b.racers[0].item = "puck"
        self.step(1, [(False, False, 0.0, False, False, True), IDLE])
        self.step(60)
        r = self.b.racers[1]
        self.assertEqual(r.balloons, 2)
        self.assertGreater(r.safe, 0.0)

    def test_slick_spins_out_whoever_drives_over_it(self):
        self.face_off()
        a, b = self.b.cars
        self.b.slicks.append(I.Slick(b.x, b.y, owner=0))
        self.step()
        self.assertGreater(self.b.racers[1].spin, 0.0)
        self.assertEqual(self.b.racers[1].balloons, 2)

    def test_ghost_is_untouchable_and_turbo_boosts(self):
        r = self.b.racers[1]
        r.ghost = 3.0
        self.assertFalse(self.b._hurt(1))
        self.b.racers[0].item = "turbo"
        self.step(1, [(False, False, 0.0, False, False, True), IDLE])
        self.assertGreater(self.b.cars[0].boost_t, 1.0)

    def test_triple_puck_blocks_a_shot(self):
        self.face_off(20.0)
        self.b.racers[1].item, self.b.racers[1].orbit = "triple", 3
        self.b.racers[0].item = "puck"
        self.step(1, [(False, False, 0.0, False, False, True), IDLE])
        self.step(90)
        self.assertEqual(self.b.racers[1].balloons, 3)
        self.assertEqual(self.b.racers[1].orbit, 2)

    def test_last_car_with_balloons_wins_and_rematch(self):
        for _ in range(3):
            self.b.racers[1].safe = 0.0
            self.b._hurt(1)
        self.step()
        self.assertTrue(self.b.racers[1].out)
        self.assertEqual(self.b.winner, 0)
        self.b.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertIsNot(self.game.two, self.b)
        self.assertIsNone(self.game.two.winner)

    def test_draws_both_views_with_balloons(self):
        self.face_off(8.0)
        self.b.racers[0].item = "seeker"
        self.b.draw()
        kinds = {e["kind"] for e in self.b.extras()}
        self.assertTrue({"balloon", "box"} <= kinds)


class SprintTests(unittest.TestCase):
    def test_reaching_the_beacon_wins(self):
        game = Game(WORLD, 2, deterministic=True, traffic=0)
        game._begin("sprint")
        b = game.two
        self.assertEqual(b.mode, "sprint")
        self.assertEqual(len(b.markers()), 1)
        _l, tx, ty = b.target
        car = b.cars[1]
        car.x, car.y, car.vx, car.vy = tx + 3.0, ty, 0.0, 0.0
        b.step(1 / 60, [IDLE, IDLE])
        self.assertEqual(b.winner, 1)
        b.draw()

    def test_real_map_targets(self):
        real = World.load(os.path.join(ROOT, "data", "amherst_map.json"))
        names = {t[0] for t in B.sprint_targets(real)}
        self.assertTrue({"VICTORIA SQUARE", "PUMPING STATION DAM", "BORDER LIGHTHOUSE"} <= names, names)


class MenuTests(unittest.TestCase):
    def test_battle_and_race_are_on_the_start_screen(self):
        modes = [o[1] for o in MENU.OPTIONS]
        self.assertIn("battle", modes)
        self.assertIn("sprint", modes)
        bottom = MENU.rect_of(len(MENU.OPTIONS) - 1)
        self.assertLessEqual(bottom.bottom, 180)


if __name__ == "__main__":
    unittest.main()
