"""Elevation: terrain grid, heights in the world, hills in the renderer, the download tool."""
import io
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import fetch_elevation as FE  # noqa: E402

from game.car import Car  # noqa: E402
from game.collision import settle_height  # noqa: E402
from game.render3d import ChaseCamera, Renderer3D  # noqa: E402
from game.terrain import Terrain  # noqa: E402
from game.world import World  # noqa: E402

ROADS = [
    {"type": "main", "width": 9, "name": "Over St", "points": [[-200, 0], [-25, 0]]},
    {"type": "main", "width": 9, "name": "Over St", "points": [[-25, 0], [25, 0]], "bridge": True, "lift": 5.2},
    {"type": "main", "width": 9, "name": "Over St", "points": [[25, 0], [200, 0]]},
    {"type": "main", "width": 9, "name": "Under Rd", "points": [[0, -200], [0, 200]]},
]
BUILDING = {"points": [[40, 20], [60, 20], [60, 40], [40, 40]], "height": 8}


def slope_terrain(rise_per_m=0.1, scale=1.0):
    """Ground rising to the east: height = rise * x, on a 25 m grid from -300."""
    nx = ny = 25
    h = [rise_per_m * (-300 + i * 25.0) for j in range(ny) for i in range(nx)]
    return Terrain(-300.0, -300.0, 25.0, nx, ny, h, scale)


def world(terrain=None, buildings=()):
    return World({"meta": {"bounds": [-300, -300, 300, 300], "procedural_props": False},
                  "roads": json.loads(json.dumps(ROADS)), "buildings": [dict(b) for b in buildings]}, terrain)


class TerrainGrid(unittest.TestCase):
    def test_bilinear_and_edges(self):
        t = slope_terrain(0.1)
        self.assertAlmostEqual(t.height(0.0, 0.0), 0.0, places=6)
        self.assertAlmostEqual(t.height(100.0, 50.0), 10.0, places=6)
        self.assertAlmostEqual(t.height(12.5, 0.0), 1.25, places=6)        # between grid nodes
        self.assertAlmostEqual(t.height(5000.0, 0.0), t.height(300.0, 0.0), places=6)   # clamped, no cliff

    def test_normal_and_slope(self):
        t = slope_terrain(0.1)
        nx, ny, nz = t.normal(0.0, 0.0)
        self.assertLess(nx, 0)                                  # surface leans away from the uphill side (east)
        self.assertAlmostEqual(ny, 0.0, places=6)
        self.assertAlmostEqual(t.slope(0.0, 0.0), 0.1, places=3)

    def test_vertical_scale_and_dict_roundtrip(self):
        d = {"step": 25, "x0": 0, "y0": 0, "nx": 2, "ny": 2, "unit": 0.1, "h": [0, 100, 0, 100]}
        self.assertAlmostEqual(Terrain.from_dict(d, scale=1.0).height(25, 0), 10.0)
        self.assertAlmostEqual(Terrain.from_dict(d, scale=1.5).height(25, 0), 15.0)

    def test_bad_grid_size_rejected(self):
        with self.assertRaises(ValueError):
            Terrain(0, 0, 25, 3, 3, [0.0] * 8)

    def test_load_missing_or_broken_is_flat(self):
        self.assertIsNone(Terrain.load(None))
        self.assertIsNone(Terrain.load("/no/such/elevation.json"))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "elevation.json")
            open(p, "w").write("{not json")
            self.assertIsNone(Terrain.load(p))


class WorldHeights(unittest.TestCase):
    def test_flat_world_unchanged(self):
        w = world()
        self.assertEqual(w.ground(10, 10), 0.0)
        self.assertEqual(w.height_at(150, 0, 0.0), 0.0)

    def test_ground_and_deck_on_hill(self):
        w = world(slope_terrain(0.1))
        self.assertAlmostEqual(w.ground(100, 0), 10.0, places=6)
        self.assertAlmostEqual(w.height_at(100, 0, 10.0), 10.0, places=6)
        deck = w.height_at(0, 0, w.ground(0, 0) + 5.2)          # on the bridge: ground (0) + 5.2 above it
        self.assertAlmostEqual(deck, 5.2, places=2)
        self.assertGreater(w.height_at(0, 0, 0.0) + 5.0, 0.0)

    def test_road_found_on_hill_at_ground_level(self):
        w = world(slope_terrain(0.1))
        r = w.road_at(100.0, 0.0, w.ground(100.0, 0.0))
        self.assertIsNotNone(r)
        self.assertEqual(r["name"], "Over St")

    def test_car_follows_ground_and_rolls_downhill(self):
        w = world(slope_terrain(0.1))
        c = Car(100.0, 100.0, 0.0)
        c.z = 0.0
        for _ in range(60):
            settle_height(c, w, 1 / 30)
        self.assertAlmostEqual(c.z, w.ground(c.x, c.y), delta=0.05)
        self.assertLess(c.vx, 0.0)                              # ground rises to the east, so it pulls west

    def test_world_load_reads_elevation_beside_map(self):
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "m.json")
            json.dump({"meta": {"bounds": [-300, -300, 300, 300], "procedural_props": False},
                       "roads": ROADS, "buildings": []}, open(mp, "w"))
            self.assertIsNone(World.load(mp).terrain)
            json.dump({"step": 25, "x0": -300, "y0": -300, "nx": 2, "ny": 2, "unit": 0.1, "h": [0, 0, 0, 0]},
                      open(os.path.join(d, "elevation.json"), "w"))
            self.assertIsNotNone(World.load(mp).terrain)


class HillRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def frame(self, w, style="street", x=100.0, y=0.0):
        r = Renderer3D(w, style)
        surf = pygame.Surface((320, 224))
        c = Car(x, y, 0.0)
        c.z = w.ground(x, y)
        r.render(surf, c, ChaseCamera(c, w), [], 0.0, ())
        return r, surf

    def test_renders_both_styles_with_hills(self):
        for style in ("street", "retro"):
            r, surf = self.frame(world(slope_terrain(0.1), [BUILDING]), style)
            self.assertGreater(r.polys, 10)

    def test_building_sits_on_highest_corner_with_walls_down_to_the_land(self):
        w = world(slope_terrain(0.1, 1.0), [BUILDING])
        r, _ = self.frame(w)
        g, _drop = r._building_ground(0)
        self.assertAlmostEqual(g, 6.0, places=3)                # east wall at x=60 -> 6 m: nothing is buried
        self.assertGreater(r._building_ground(0)[1], 1.5)       # the west wall reaches 2 m further down the slope

    def test_camera_stays_above_ground(self):
        w = world(slope_terrain(0.4))                           # steep: camera behind the car is downhill, never under
        c = Car(150.0, 0.0, 0.0)
        c.z = w.ground(150.0, 0.0)
        cam = ChaseCamera(c, w)
        self.assertGreater(cam.z, w.ground(cam.x, cam.y) + 1.0)

    def test_flat_render_identical_with_zero_terrain(self):
        flat = Terrain(-300.0, -300.0, 25.0, 3, 3, [0.0] * 9)
        _r1, s1 = self.frame(world(None, [BUILDING]), x=0.0, y=-60.0)
        _r2, s2 = self.frame(world(flat, [BUILDING]), x=0.0, y=-60.0)
        # the terrain mesh paints the ground differently, but roads and walls must still be there
        self.assertEqual(pygame.image.tostring(s1, "RGB")[:3 * 320 * 20], pygame.image.tostring(s2, "RGB")[:3 * 320 * 20])


class DownloadTool(unittest.TestCase):
    @staticmethod
    def png(fn):
        """A 256 px Terrarium tile whose height at pixel (i, j) is fn(i, j) metres."""
        s = pygame.Surface((256, 256))
        for j in range(256):
            for i in range(256):
                v = fn(i, j) + 32768.0
                s.set_at((i, j), (int(v // 256), int(v) % 256, int((v - int(v)) * 256)))
        buf = io.BytesIO()
        pygame.image.save(s, buf, "x.png")
        return buf.getvalue()

    @classmethod
    def setUpClass(cls):
        pygame.init()

    def test_decode_terrarium(self):
        self.assertEqual(FE.decode_terrarium(128, 0, 0), 0.0)
        self.assertEqual(FE.decode_terrarium(128, 25, 128), 25.5)

    def test_projection_roundtrip_and_pixels(self):
        lat, lon = FE.xy_to_latlon(1000.0, -2000.0, 45.826, -64.218)
        self.assertGreater(lat, 45.826)                          # negative y = north
        self.assertGreater(lon, -64.218)
        px, py = FE.latlon_to_pixel(0.0, 0.0, 1)
        self.assertAlmostEqual(px, 256.0)
        self.assertAlmostEqual(py, 256.0)
        _, py2 = FE.latlon_to_pixel(46.0, -64.0, 13)
        _, py3 = FE.latlon_to_pixel(45.0, -64.0, 13)
        self.assertLess(py2, py3)                                # further north = smaller pixel y

    def test_tile_source_samples_a_gradient(self):
        data = self.png(lambda i, j: 10.0 + i * 0.5)             # 0.5 m per pixel to the east
        calls = []

        def fetch(url):
            calls.append(url)
            return data
        src = FE.TileSource(13, fetch)
        lat, lon = 45.826, -64.218
        h1, h2 = src.height(lat, lon), src.height(lat, lon + 0.001)
        self.assertGreater(h2, h1)                               # moving east climbs (unless crossing a tile edge)
        self.assertTrue(10.0 <= h1 <= 138.0)
        self.assertLessEqual(len(calls), 2)                      # tiles are cached

    def test_build_grid_and_step_limit(self):
        g = FE.build_grid(lambda la, lo: 12.34, 45.826, -64.218, (0, 0, 100, 50), 25.0)
        self.assertEqual((g["nx"], g["ny"]), (5, 3))
        self.assertEqual(set(g["h"]), {123})
        self.assertEqual(len(g["h"]), g["nx"] * g["ny"])
        self.assertGreater(FE.choose_step(40000, 40000, 25.0), 25.0)
        self.assertEqual(FE.choose_step(1000, 1000, 25.0), 25.0)

    def test_from_asc_and_projected_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "dem.asc")
            open(p, "w").write("ncols 2\nnrows 2\nxllcorner -64.3\nyllcorner 45.7\ncellsize 0.2\n"
                               "NODATA_value -9999\n10 10\n10 10\n")
            self.assertAlmostEqual(FE.asc_source(p)(45.826, -64.218), 10.0, places=3)
            q = os.path.join(d, "utm.asc")
            open(q, "w").write("ncols 1\nnrows 1\nxllcorner 400000\nyllcorner 5000000\ncellsize 10\n5\n")
            with self.assertRaises(ValueError):
                FE.asc_source(q)

    def test_main_writes_file_the_game_can_load(self):
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "m.json")
            json.dump({"meta": {"origin_lat": 45.826, "origin_lon": -64.218, "bounds": [-300, -300, 300, 300],
                                "spawn": [0, 0, 0], "procedural_props": False}, "roads": ROADS, "buildings": []},
                      open(mp, "w"))
            asc = os.path.join(d, "dem.asc")
            open(asc, "w").write("ncols 2\nnrows 2\nxllcorner -64.3\nyllcorner 45.7\ncellsize 0.2\n20 20\n20 20\n")
            self.assertEqual(FE.main(["--map", mp, "--from-asc", asc, "--radius", "200"]), 0)
            w = World.load(mp)
            self.assertIsNotNone(w.terrain)
            self.assertAlmostEqual(w.ground(0, 0), 20.0 * 1.5, places=1)   # arcade vertical stretch applies


if __name__ == "__main__":
    unittest.main()
