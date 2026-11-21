"""Tests for growing the map (tools/extend_map.py), finding rural homes in LiDAR (tools/find_homes.py), parked cars
and hand-set house details (map_edits.json "cars", "front", "shutters"...).

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

import numpy as np  # noqa: E402
import pygame  # noqa: E402

import extend_map as E  # noqa: E402
import find_homes as F  # noqa: E402
import make_sample_map  # noqa: E402
from game import collision  # noqa: E402
from game import config as C  # noqa: E402
from game import mapedits  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World  # noqa: E402


class NewRoadPieces(unittest.TestCase):
    def test_only_the_new_part_is_kept_and_it_touches_the_old_road(self):
        old = E.Lines([[[0, 0], [100, 0]]])                          # an existing road along y = 0
        pieces = E.new_pieces([[50, 0], [100, 0], [100, 60]], old)  # runs along it, then turns off north... south
        self.assertEqual(len(pieces), 1)
        p = pieces[0]
        self.assertLessEqual(old.dist(*p[0]), E.COVERED)             # starts on the old road: the graph joins them
        self.assertEqual(p[-1], [100, 60])

    def test_a_road_already_on_the_map_adds_nothing(self):
        old = E.Lines([[[0, 0], [100, 0]]])
        self.assertEqual(E.new_pieces([[10, 0.5], [90, 0.4]], old), [])

    def test_merge_skips_buildings_already_there_and_grows_bounds(self):
        sq = lambda x, y: [[x, y], [x + 10, y], [x + 10, y + 8], [x, y + 8]]      # noqa: E731
        data = {"meta": {"bounds": [0, 0, 100, 100]}, "roads": [{"points": [[0, 0], [100, 0]]}],
                "buildings": [{"points": sq(10, 10)}]}
        ext = {"roads": [{"name": "Far Rd", "points": [[100, 0], [400, 0]]}],
               "buildings": [{"points": sq(10.5, 10.2)}, {"points": sq(300, 20)}]}
        counts = E.merge(data, ext)
        self.assertEqual((counts["roads"], counts["buildings"]), (1, 1))
        self.assertGreaterEqual(data["meta"]["bounds"][2], 400)

    def test_upper_case_headers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "n.csv")
            E.upper_csv(['"the_geom","roadclass","street"', '"MULTILINESTRING ((1 2, 3 4))","LO","X"'], path)
            with open(path) as f:
                self.assertEqual(f.readline().strip(), "the_geom,ROADCLASS,STREET")


class LidarHomes(unittest.TestCase):
    def ground_with_house(self):
        """A 60 m window: a 12 x 8 m gable roof (eaves 3 m, ridge 4.5 m) and a rough 'tree'."""
        gx, gy = np.meshgrid(np.arange(-30, 30, 1.0), np.arange(-30, 30, 1.0))
        h = np.zeros(gx.shape)
        house = (np.abs(gx - 5) <= 6) & (np.abs(gy + 4) <= 4)
        h[house] = 4.5 - 1.5 * np.abs(gy[house] + 4) / 4
        rng = np.random.RandomState(1)
        tree = np.hypot(gx + 15, gy - 12) < 5
        h[tree] = 6 + rng.rand(tree.sum()) * 5
        return gx, gy, h

    def test_roof_is_found_and_the_tree_is_not(self):
        gx, gy, h = self.ground_with_house()
        found = [c for c in F.blobs(F.roof_mask(h)) if len(c) >= F.SHED_AREA]
        self.assertEqual(len(found), 1)
        rr, cc = np.array(found[0]).T
        centre, ang, length, width, fill = F.rectangle(gx[rr, cc], gy[rr, cc])
        self.assertAlmostEqual(centre[0], 5, delta=1.0)
        self.assertAlmostEqual(centre[1], -4, delta=1.0)
        self.assertAlmostEqual(length, 13, delta=1.5)
        self.assertAlmostEqual(width, 9, delta=1.5)
        self.assertGreater(fill, F.MIN_FILL)

    def test_corners_make_the_rectangle(self):
        pts = F.corners((10, 20), math.radians(30), 12, 8)
        self.assertAlmostEqual(math.dist(pts[0], pts[1]), 12, delta=0.2)
        self.assertAlmostEqual(math.dist(pts[1], pts[2]), 8, delta=0.2)

    def test_only_addresses_without_a_building_are_searched(self):
        data = {"buildings": [{"points": [[0, 0], [10, 0], [10, 8], [0, 8]]}]}
        todo = F.empty_addresses(data, [[5, 4, "1", "A St"], [200, 0, "2", "A St"], [900, 0, "3", "A St"]], (-50, -50, 500, 50))
        self.assertEqual([a[2] for a in todo], ["2"])


class ParkedCarsAndHouseDetails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        data = make_sample_map.build()
        data["roads"] = [{"type": "side", "width": 8, "name": "Elm St", "points": [[-200, 0], [200, 0]]}]
        data["buildings"] = [{"points": [[-5, 10], [5, 10], [5, 18], [-5, 18]], "tags": {"building": "house"},
                              "height": 3.8, "zone": "R", "material": "clapboard", "colour": [240, 240, 236],
                              "roof": "gable", "roof_height": 3.8, "roof_colour": [84, 112, 72], "arch": "cape",
                              "dormers": 2, "front": 180.0, "door_at": 0.5, "door": [10, 200, 10],
                              "sidelights": True, "shutters": [200, 10, 200]}]
        meta = data["meta"]
        meta.update(origin_lat=45.83, origin_lon=-64.2)
        lat, lon = meta["origin_lat"], meta["origin_lon"]
        mapedits.apply(data, {"cars": {"add": [{"lat": lat, "lon": lon, "bearing": 90.0, "model": "crv",
                                                "colour": [70, 74, 82]}]}})
        cls.world = World(data)

    def test_parked_car_is_placed_heading_east(self):
        p = self.world.parked[0]
        self.assertAlmostEqual(p["x"], 0.0, delta=0.5)
        self.assertAlmostEqual(math.cos(p["heading"]), 1.0, places=3)        # bearing 90 = east = +x

    def test_parked_car_is_solid(self):
        car = Car(0.0, 1.6, 0.0)                                             # alongside, overlapping by ~0.2 m
        car.vy = -5.0
        hit = collision._push_out_props(car, self.world)
        self.assertGreater(hit, 0.0)
        self.assertGreater(car.y, 1.6)                                       # pushed away

    def frame(self, x, y, heading):
        r = R.Renderer3D(self.world, style="street")
        car = Car(x, y, heading)
        cam = R.ChaseCamera(car, self.world)
        for _ in range(40):
            cam.update(car, 1 / 30)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        r.render(surf, car, cam)
        return r, surf

    def colours(self, surf):
        return {tuple(surf.get_at((x, y)))[:3] for x in range(0, surf.get_width(), 2) for y in range(0, surf.get_height(), 2)}

    def test_hand_set_front_door_and_shutters_are_drawn(self):
        # "front": 180 = the south wall (y = 18), although the street is on the north side: the hand value wins
        r, surf = self.frame(-3.0, 34.0, math.radians(-75))                 # south of the house, looking at that wall
        house = r._house(0)
        wall = r.buildings[0][4][house["front"]]
        self.assertGreater(wall[5], 0.9)                                     # outward normal points south (+y)
        got = self.colours(surf)
        self.assertTrue(got & {r.col((10, 200, 10), s, f) for s in range(4) for f in range(3)}, "no green door")
        self.assertTrue(got & {r.col((200, 10, 200), s, f) for s in range(4) for f in range(3)}, "no shutters")

    def test_parked_car_drawn_in_the_frame(self):
        r, surf = self.frame(-14.0, -4.0, 0.0)
        self.assertEqual(len(r.parked_cars()), 1)
        body = {r.col((70, 74, 82), s, f) for s in range(4) for f in range(3)}
        self.assertTrue(self.colours(surf) & body)


if __name__ == "__main__":
    unittest.main()


class Scenery(unittest.TestCase):
    """Hand-placed horse, gravestones and fences (map_edits.json props), and hand-placed tree sizes."""

    def test_fence_is_cut_into_pieces_along_its_line(self):
        from game import props as PR
        pieces = PR._scenery({"kind": "fence", "x": 0.0, "y": 0.0, "x2": 10.0, "y2": 0.0})
        self.assertEqual(len(pieces), 3)
        self.assertEqual(pieces[0]["a"], [0.0, 0.0])
        self.assertEqual(pieces[-1]["b"], [10.0, 0.0])
        self.assertTrue(pieces[-1]["last"] and not pieces[0]["last"])
        self.assertEqual(pieces[0]["cr"], 0.0)                               # drive through it

    def test_bearing_becomes_heading_and_horse_is_solid(self):
        from game import props as PR
        horse = PR._scenery({"kind": "horse", "x": 1.0, "y": 2.0, "bearing": 90.0})[0]
        self.assertAlmostEqual(math.cos(horse["heading"]), 1.0, places=3)   # east = +x
        self.assertGreater(horse["cr"], 0.5)

    def test_hand_tree_keeps_its_size(self):
        from game import props as PR
        data = make_sample_map.build()
        data["buildings"] = []
        data["roads"] = [{"type": "side", "width": 8, "name": "Elm St", "points": [[-200, 0], [200, 0]]}]
        got = PR.build_props(World(data), [{"kind": "tree", "x": 0.0, "y": 30.0, "h": 14.0, "r": 4.5}], procedural=False)
        self.assertEqual((got[0]["h"], got[0]["r"]), (14.0, 4.5))

    def test_scenery_draws_in_both_styles(self):
        pygame.init()
        data = make_sample_map.build()
        data["roads"] = [{"type": "side", "width": 8, "name": "Elm St", "points": [[-200, 0], [200, 0]]}]
        data["props"] = [{"kind": "horse", "x": 0.0, "y": 12.0, "heading": 0.0, "lift": 0.3},
                         {"kind": "gravestone", "x": 4.0, "y": 14.0, "h": 0.9},
                         {"kind": "fence", "x": -10.0, "y": 8.0, "x2": 10.0, "y2": 8.0}]
        world = World(data)
        kinds = {p["kind"] for p in world.props_near(0.0, 12.0, 30.0)}
        self.assertTrue({"horse", "gravestone", "fence"} <= kinds)
        for style in R.STYLES:
            r = R.Renderer3D(world, style=style)
            car = Car(-6.0, 2.0, 0.6)
            cam = R.ChaseCamera(car, world)
            surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
            r.render(surf, car, cam)
            dark = {r.col((30, 28, 34), s, f) for s in range(4) for f in range(3)}
            got = {tuple(surf.get_at((x, y)))[:3] for x in range(0, surf.get_width(), 2) for y in range(0, surf.get_height(), 2)}
            self.assertTrue(got & dark, "no horse in the %s style" % style)

    def test_no_graffiti_on_clapboard_or_hand_modelled_homes(self):
        self.assertFalse(R.graffiti_ok({"material": "clapboard"}, 500))
        self.assertFalse(R.graffiti_ok({"material": "brick", "arch": "two_storey"}, 500))
        self.assertTrue(R.graffiti_ok({"material": "brick"}, 500))
