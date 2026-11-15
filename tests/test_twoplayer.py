"""Start screen and two player split screen."""
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
from game import menu as M  # noqa: E402
from game import render3d as R  # noqa: E402
from game.main import Game  # noqa: E402
from game.world import World  # noqa: E402

WORLD = World(make_sample_map.build())


def key(k):
    return pygame.event.Event(pygame.KEYDOWN, key=k)


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(WORLD, 2, deterministic=True, traffic=0)
        self.menu = M.Menu(self.game)

    def test_starts_on_one_player(self):
        self.assertEqual(self.menu.handle_event(key(pygame.K_RETURN)), ("choose", "1p"))

    def test_down_then_enter_picks_two_player(self):
        self.menu.handle_event(key(pygame.K_DOWN))
        self.assertEqual(self.menu.handle_event(key(pygame.K_RETURN)), ("choose", "2p"))

    def test_number_keys_and_wrap_to_quit(self):
        self.assertEqual(self.menu.handle_event(key(pygame.K_2)), ("choose", "2p"))
        self.menu.handle_event(key(pygame.K_UP))                     # wraps to QUIT
        self.assertEqual(self.menu.handle_event(key(pygame.K_RETURN)), ("quit",))

    def test_gamepad_dpad_and_a_button(self):
        self.menu.handle_event(pygame.event.Event(pygame.JOYHATMOTION, value=(0, -1), hat=0, joy=0, instance_id=0))
        self.assertEqual(self.menu.handle_event(pygame.event.Event(pygame.JOYBUTTONDOWN, button=0, joy=0, instance_id=0)),
                         ("choose", "2p"))

    def test_escape_quits(self):
        self.assertEqual(self.menu.handle_event(key(pygame.K_ESCAPE)), ("quit",))

    def test_mouse_click_on_an_option(self):
        ww, wh = self.game.window.get_size()
        k = min(ww / C.INTERNAL_W, wh / C.INTERNAL_H)
        r = M.rect_of(1)
        pos = (int(((ww - C.INTERNAL_W * k) / 2) + r.centerx * k), int(((wh - C.INTERNAL_H * k) / 2) + r.centery * k))
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)
        self.assertEqual(self.menu.handle_event(ev), ("choose", "2p"))

    def test_menu_draws(self):
        self.menu.draw(1 / 30)
        self.assertEqual((R.W, R.H), (C.INTERNAL_W, C.INTERNAL_H))


class TwoPlayerTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(WORLD, 2, deterministic=True, traffic=6, cops=True)
        self.game._begin("2p")
        self.two = self.game.two

    def test_two_cars_side_by_side_and_no_police(self):
        a, b = self.two.cars
        self.assertGreater(((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5, 3.0)
        self.assertFalse(self.game.town.cops)
        self.game.town.add_heat(4.0)
        for _ in range(300):
            self.two.step(1 / 60, [(True, False, 0.0, False), (False, False, 0.0, False)])
        self.assertEqual(self.game.town.stars, 0)
        self.assertEqual(self.game.town.police, [])
        self.assertEqual(self.game.town.damage, 0.0)
        self.assertGreater(a.speed, 3.0)            # player 1 accelerated, player 2 did not
        self.assertLess(b.speed, 0.5)

    def test_players_are_independent(self):
        a, b = self.two.cars
        bx = b.x
        for _ in range(120):
            self.two.step(1 / 60, [(True, False, 0.0, False), (False, False, 0.0, False)])
        self.assertAlmostEqual(b.x, bx, delta=0.5)

    def test_respawn_puts_a_car_back(self):
        a, _b = self.two.cars
        a.x += 200.0
        a.vx = 10.0
        self.two.respawn(0)
        self.assertLess(abs(a.x - self.two._spawn(-1).x), 1.0)
        self.assertEqual(a.speed, 0.0)

    def test_traffic_is_kept_around_both_players(self):
        a, b = self.two.cars
        self.assertEqual(self.game.town.extra, [b])
        for _ in range(60):
            self.two.step(1 / 30, [(False, False, 0.0, False)] * 2)
        self.assertGreater(len(self.game.town.cars), 0)

    def test_draw_splits_the_screen_and_restores_the_viewport(self):
        self.two.draw()
        self.assertEqual((R.W, R.H), (C.INTERNAL_W, C.INTERNAL_H))
        s = self.game.screen
        left = {tuple(s.get_at((x, y)))[:3] for x in range(0, 150, 10) for y in range(0, C.INTERNAL_H, 10)}
        right = {tuple(s.get_at((x, y)))[:3] for x in range(170, 320, 10) for y in range(0, C.INTERNAL_H, 10)}
        self.assertGreater(len(left), 5)
        self.assertGreater(len(right), 5)

    def test_one_player_game_still_has_cops(self):
        g = Game(WORLD, 2, deterministic=True, traffic=0, cops=True)
        g._begin("1p")
        self.assertTrue(g.town.cops)
        self.assertIsNone(g.two)


class FlowTests(unittest.TestCase):
    def test_menu_to_two_player_and_back_then_quit(self):
        g = Game(WORLD, 2, deterministic=True, traffic=0)
        modes, plays = [], iter(["menu", "menu", "quit"])
        choices = iter(["2p", "1p", "2p", None])
        original = g._begin
        g._begin = lambda mode: (modes.append(mode), original(mode))
        g.menu_loop = lambda: next(choices)
        g._play = lambda *a, **k: next(plays)
        g.run(menu=True)                       # menu -> 2P -> menu -> 1P -> menu -> 2P -> quit
        self.assertEqual(modes, ["2p", "1p", "2p"])

    def test_play_loop_returns_to_menu_on_escape(self):
        g = Game(WORLD, 2, deterministic=True, traffic=0)
        g.interactive = True
        g._begin("2p")
        pygame.event.post(key(pygame.K_ESCAPE))
        self.assertEqual(g._play(), "menu")
        g.interactive = False
        pygame.event.post(key(pygame.K_ESCAPE))
        self.assertEqual(g._play(), "quit")


if __name__ == "__main__":
    unittest.main()
