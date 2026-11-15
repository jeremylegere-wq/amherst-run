"""Tests for missions (M5): hubs, parcel runs, getaway, heritage tour, fines, HUD and markers.

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import sys
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

import autopilot  # noqa: E402
import make_sample_map  # noqa: E402
from game import missions as M  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import Car  # noqa: E402
from game.town import Town  # noqa: E402
from game.world import World  # noqa: E402

WORLD = World(make_sample_map.build())


def setup(seed=3, traffic=0):
    town = Town(WORLD, seed=seed, traffic=traffic)
    town._filled = True
    return town, M.MissionManager(WORLD, town, seed=seed)


def hub(ms, role):
    return next(h for h in ms.hubs if h.role == role)


def park_at(ms, x, y, steps=2):
    car = Car(x, y, 0.0)
    for _ in range(steps):
        ms.update(1 / 60, car)
    return car


class HubTests(unittest.TestCase):
    def test_demo_town_has_all_four_hubs_on_roads(self):
        _t, ms = setup()
        self.assertEqual(sorted(h.role for h in ms.hubs), ["courthouse", "deliveries", "getaway", "tour"])
        for h in ms.hubs:
            self.assertTrue(WORLD.on_road(h.x, h.y), h.label)
        for a in ms.hubs:
            for b in ms.hubs:
                if a is not b:
                    self.assertGreater(math.hypot(a.x - b.x, a.y - b.y), 2 * M.HUB_RADIUS)   # markers don't overlap

    def test_driving_past_does_not_start_a_job(self):
        _t, ms = setup()
        h = hub(ms, "deliveries")
        car = Car(h.x, h.y, 0.0)
        car.vx = 15.0
        ms.update(1 / 60, car)
        self.assertIsNone(ms.mission)

    def test_no_jobs_while_wanted(self):
        town, ms = setup()
        town.add_heat(1.0)
        h = hub(ms, "deliveries")
        park_at(ms, h.x, h.y)
        self.assertIsNone(ms.mission)
        self.assertIn("COPS", ms.banner[0])

    def test_hub_does_not_retrigger_until_you_leave(self):
        _t, ms = setup()
        h = hub(ms, "deliveries")
        park_at(ms, h.x, h.y)
        self.assertIsNotNone(ms.mission)
        ms.mission = None                      # e.g. the job finished while parked in the hub
        park_at(ms, h.x, h.y, steps=30)
        self.assertIsNone(ms.mission)
        park_at(ms, h.x + 40, h.y)             # drive away...
        park_at(ms, h.x, h.y)                  # ...and come back
        self.assertIsNotNone(ms.mission)

    def test_markers_show_hubs_then_only_the_target(self):
        _t, ms = setup()
        self.assertEqual(len(ms.markers()), len(ms.hubs))
        h = hub(ms, "deliveries")
        park_at(ms, h.x, h.y)
        mk = ms.markers()
        self.assertEqual(len(mk), 1)
        self.assertEqual(mk[0]["kind"], "target")


class CourtHouseTests(unittest.TestCase):
    def test_pay_fine_clears_heat(self):
        town, ms = setup()
        town.add_heat(1.5)                     # two stars
        ms.cash = 500
        h = hub(ms, "courthouse")
        park_at(ms, h.x, h.y)
        self.assertEqual(town.heat, 0.0)
        self.assertEqual(ms.cash, 300)

    def test_cannot_pay_without_cash(self):
        town, ms = setup()
        town.add_heat(1.0)
        h = hub(ms, "courthouse")
        park_at(ms, h.x, h.y)
        self.assertGreater(town.heat, 0.0)
        self.assertIn("FINE IS $100", ms.banner[0])

    def test_nothing_to_pay_when_clean(self):
        _t, ms = setup()
        h = hub(ms, "courthouse")
        park_at(ms, h.x, h.y)
        self.assertIn("NO FINES", ms.banner[0])


class DeliveryTests(unittest.TestCase):
    def start(self, seed=3):
        town, ms = setup(seed)
        h = hub(ms, "deliveries")
        park_at(ms, h.x, h.y)
        self.assertEqual(ms.mission.kind, "delivery")
        return town, ms

    def test_targets_are_on_roads_with_street_names(self):
        for seed in range(1, 8):
            _t, ms = self.start(seed)
            m = ms.mission
            self.assertTrue(1 <= len(m.targets) <= 3)
            for t in m.targets:
                self.assertTrue(WORLD.on_road(t.x, t.y))
                self.assertTrue(t.stop)
                self.assertTrue(t.label)
            self.assertGreater(m.time_limit, 15.0)

    def test_must_stop_at_the_address_then_get_paid(self):
        _t, ms = self.start()
        m = ms.mission
        for i, t in enumerate(m.targets):
            fast = Car(t.x, t.y, 0.0)
            fast.vx = 12.0
            ms.update(1 / 60, fast)
            self.assertEqual(m.stage, i)                 # rolling through doesn't count
            park_at(ms, t.x, t.y, steps=1)
        self.assertIsNone(ms.mission)
        self.assertGreaterEqual(ms.cash, m.reward)
        self.assertEqual(ms.completed, 1)

    def test_out_of_time_fails(self):
        _t, ms = self.start()
        car = Car(-250.0, 200.0, 0.0)
        for _ in range(int((ms.mission.time_limit + 1) * 60)):
            ms.update(1 / 60, car)
        self.assertIsNone(ms.mission)
        self.assertEqual(ms.cash, 0)
        self.assertEqual(ms.banner[0], "OUT OF TIME")

    def test_fragile_parcel_breaks(self):
        town, ms = self.start()
        ms.mission.fragile = True
        town.damage += M.FRAGILE_DAMAGE + 1
        ms.update(1 / 60, Car(-250.0, 200.0, 0.0))
        self.assertEqual(ms.banner[0], "PARCEL SMASHED")

    def test_busted_fails_the_job_and_costs_money(self):
        town, ms = self.start()
        ms.cash = 250
        town.state = "busted"
        ms.update(1 / 60, Car(0.0, 0.0, 0.0))
        self.assertIsNone(ms.mission)
        self.assertEqual(ms.cash, 150)
        for _ in range(60 * 10):                       # the message waits through the BUSTED screen...
            ms.update(1 / 60, Car(0.0, 0.0, 0.0))
        self.assertEqual(ms.banner[0], "JOB LOST  FINED -$100")
        town.state = "playing"                         # ...and shows once play resumes
        ms.update(1 / 60, Car(0.0, 0.0, 0.0))
        self.assertIsNotNone(ms.banner)


class GetawayAndTourTests(unittest.TestCase):
    def test_getaway_gives_three_stars_and_pays_when_you_lose_them(self):
        town, ms = setup()
        h = hub(ms, "getaway")
        car = park_at(ms, h.x, h.y)
        self.assertEqual(ms.mission.kind, "getaway")
        self.assertEqual(town.stars, 3)
        self.assertEqual(ms.markers(), [])
        town.heat = 0.0
        for _ in range(60 * 3):
            ms.update(1 / 60, car)
        self.assertIsNone(ms.mission)
        self.assertGreaterEqual(ms.cash, 450)

    def test_tour_visits_landmarks_and_counts_checkpoints_at_speed(self):
        _t, ms = setup()
        h = hub(ms, "tour")
        park_at(ms, h.x, h.y)
        m = ms.mission
        self.assertEqual(m.kind, "tour")
        labels = [t.label for t in m.targets]
        self.assertGreaterEqual(len(labels), 3)
        self.assertTrue({"Court House", "Post Office"} & set(labels))
        for t in m.targets:
            fast = Car(t.x, t.y, 0.0)
            fast.vx = 25.0                               # checkpoints don't need a stop
            ms.update(1 / 60, fast)
        self.assertIsNone(ms.mission)
        self.assertGreaterEqual(ms.cash, m.reward)


class FairnessTests(unittest.TestCase):
    """A careful autopilot with real physics and traffic must be able to finish jobs in time."""

    def run_job(self, role, seed):
        town = Town(WORLD, seed=seed, traffic=10)
        g = SimpleNamespace(world=WORLD, town=town, car=Car(*WORLD.spawn()))
        g.missions = M.MissionManager(WORLD, town, seed=seed)
        return autopilot.play_job(g, role)

    def test_parcel_runs_are_doable(self):
        for seed in (1, 4):
            result, used, limit = self.run_job("deliveries", seed)
            self.assertTrue(result.startswith("JOB DONE"), (seed, result, used, limit))

    def test_heritage_tour_is_doable(self):
        result, used, limit = self.run_job("tour", 2)
        self.assertTrue(result.startswith("JOB DONE"), (result, used, limit))


class MissionDrawingTests(unittest.TestCase):
    def test_beacon_is_drawn(self):
        pygame.init()
        _t, ms = setup()
        car = Car(-180.0, 0.0, 0.0)
        cam = R.ChaseCamera(car, WORLD)
        r = R.Renderer3D(WORLD, style="street")
        s1, s2 = pygame.Surface((320, 224)), pygame.Surface((320, 224))
        r.render(s1, car, cam, markers=[])
        r.render(s2, car, cam, markers=[{"x": -150.0, "y": 2.0, "colour": (255, 150, 30), "radius": 7.0,
                                         "kind": "target"}])
        diff = sum(1 for x in range(0, 320, 2) for y in range(0, 224, 2) if s1.get_at((x, y)) != s2.get_at((x, y)))
        self.assertGreater(diff, 30)

    def test_hud_draws_mission_state_in_both_styles(self):
        from game.main import Game
        for style in ("street", "retro"):
            game = Game(WORLD, 1, deterministic=True, traffic=0, style=style)
            h = next(x for x in game.missions.hubs if x.role == "deliveries")
            game.car = Car(h.x, h.y, 0.0)
            game.missions.update(1 / 60, game.car)
            self.assertIsNotNone(game.missions.mission)
            game.draw()
            game.view3d = False
            game.draw()
            game.missions.mission.time_left = 5.0
            game.draw()
        pygame.quit()


if __name__ == "__main__":
    unittest.main()
