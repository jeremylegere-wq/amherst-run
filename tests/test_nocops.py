"""Cop-free mode: no police, no heat, no busting, no getaway/fine hubs."""
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import make_sample_map  # noqa: E402
from game import missions as M  # noqa: E402
from game.car import Car  # noqa: E402
from game.town import Town  # noqa: E402
from game.world import World  # noqa: E402

WORLD = World(make_sample_map.build())


class NoCops(unittest.TestCase):
    def test_heat_is_ignored_and_no_police_spawn(self):
        town = Town(WORLD, seed=2, traffic=6, cops=False)
        car = Car(*WORLD.spawn())
        town.add_heat(4.0)
        for _ in range(600):
            town.update(1 / 30, car)
        self.assertEqual(town.stars, 0)
        self.assertEqual(town.police, [])
        self.assertEqual(town.state, "playing")

    def test_turning_cops_off_clears_existing_police(self):
        town = Town(WORLD, seed=2, traffic=0)
        car = Car(*WORLD.spawn())
        town.add_heat(3.0)
        for _ in range(300):
            town.update(1 / 30, car)
        self.assertTrue(town.police)
        town.set_cops(False)
        self.assertEqual(town.police, [])
        self.assertEqual(town.stars, 0)

    def test_no_getaway_or_courthouse_hubs(self):
        town = Town(WORLD, seed=3, traffic=0, cops=False)
        ms = M.MissionManager(WORLD, town, seed=3)
        self.assertEqual(sorted(h.role for h in ms.hubs), ["deliveries", "tour"])
        town.set_cops(True)
        self.assertEqual(len(ms.hubs), 4)


if __name__ == "__main__":
    unittest.main()


class Addresses(unittest.TestCase):
    def test_delivery_addresses_have_a_house_number_and_a_street(self):
        town = Town(WORLD, seed=3, traffic=0)
        ms = M.MissionManager(WORLD, town, seed=3)
        named = next(r for r in WORLD.roads if r.get("name"))
        x, y = named["points"][0]
        text = ms.address(x, y)
        number, _, street = text.partition(" ")
        self.assertTrue(number.isdigit(), text)
        self.assertEqual(street, named["name"])
        self.assertEqual(ms.address(1e7, 1e7), "the address")
