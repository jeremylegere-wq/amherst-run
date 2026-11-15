"""Touch control tests: button hit-testing, one-shot taps, and a full window frame with the overlay."""
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
from game.main import Game  # noqa: E402
from game.touch import TouchControls  # noqa: E402
from game.world import World  # noqa: E402

SIZE = (2400, 1080)


def finger(kind, fid, rect):
    cx, cy = rect.center
    return pygame.event.Event(kind, finger_id=fid, x=cx / SIZE[0], y=cy / SIZE[1])


class TouchTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.t = TouchControls()
        self.t.update(SIZE)

    def test_gas_and_steer_together_then_release(self):
        r = self.t.rects
        self.t.handle_event(finger(pygame.FINGERDOWN, 1, r["gas"]), SIZE)
        self.t.handle_event(finger(pygame.FINGERDOWN, 2, r["left"]), SIZE)
        self.t.update(SIZE)
        self.assertTrue(self.t.throttle())
        self.assertEqual(self.t.steer(), -1.0)
        self.t.handle_event(finger(pygame.FINGERUP, 1, r["gas"]), SIZE)
        self.t.update(SIZE)
        self.assertFalse(self.t.throttle())

    def test_sliding_thumb_from_left_to_right(self):
        r = self.t.rects
        self.t.handle_event(finger(pygame.FINGERDOWN, 1, r["left"]), SIZE)
        self.t.update(SIZE)
        self.t.handle_event(finger(pygame.FINGERMOTION, 1, r["right"]), SIZE)
        self.t.update(SIZE)
        self.assertEqual(self.t.steer(), 1.0)

    def test_oneshot_fires_once_per_tap(self):
        r = self.t.rects
        self.t.handle_event(finger(pygame.FINGERDOWN, 1, r["map"]), SIZE)
        self.assertEqual(self.t.update(SIZE), ["map"])
        self.assertEqual(self.t.update(SIZE), [])            # still held: no repeat

    def test_synthesised_mouse_events_are_ignored(self):
        r = self.t.rects
        e = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=r["gas"].center, button=1, touch=True)
        self.t.handle_event(e, SIZE)
        self.t.update(SIZE)
        self.assertFalse(self.t.throttle())

    def test_real_mouse_works_for_desktop_testing(self):
        e = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=self.t.rects["gas"].center, button=1)
        self.t.handle_event(e, SIZE)
        self.t.update(SIZE)
        self.assertTrue(self.t.throttle())

    def test_mouse_ignored_once_fingers_are_seen_and_focus_loss_clears(self):
        r = self.t.rects
        self.t.handle_event(finger(pygame.FINGERDOWN, 1, r["left"]), SIZE)
        self.t.handle_event(finger(pygame.FINGERUP, 1, r["left"]), SIZE)
        self.t.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=r["brake"].center, button=1), SIZE)
        self.t.update(SIZE)
        self.assertFalse(self.t.brake())                      # emulated mouse must not leave brake stuck
        self.t.handle_event(finger(pygame.FINGERDOWN, 2, r["brake"]), SIZE)
        self.t.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST), SIZE)
        self.t.update(SIZE)
        self.assertFalse(self.t.brake())

    def test_game_drives_from_touch_and_letterboxes(self):
        g = Game(World(make_sample_map.build()), 1, deterministic=True, traffic=0, touch=True)
        g.window = pygame.display.set_mode((1200, 540))        # phone-ish, wider than 16:9
        g.touch.layout(1200, 540)
        g.touch.pointers[("m", 0)] = g.touch.rects["gas"].center
        g.touch.update((1200, 540))
        self.assertTrue(g.read_input(False)[0])
        g.draw()
        g.present()
        self.assertEqual(tuple(g.window.get_at((2, 270)))[:3], (0, 0, 0))   # black bar beside the picture


if __name__ == "__main__":
    unittest.main()
