"""Tests for the 0.2.1 fixes: hills hide what is behind them, buildings sit on their highest corner, buildings are
trimmed off roads when they cannot be pushed, driveways stop at buildings, and sign poles stay off roads.

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import sys
import tempfile
import types
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

from game import mapedits as M  # noqa: E402
from game import render3d as R  # noqa: E402
from game import streetdetail as SD  # noqa: E402
from game.terrain import Terrain  # noqa: E402
from game.world import World  # noqa: E402


def ridge_world():
    """Flat land with a 12 m ridge running north-south at x = 60..80, and one building behind it at x = 120."""
    nx, ny, step = 41, 41, 5.0
    heights = []
    for j in range(ny):
        for i in range(nx):
            x = -100 + i * step
            heights.append(12.0 / 1.5 if 60 <= x <= 80 else 0.0)        # Terrain scales heights by 1.5
    data = {"meta": {"bounds": [-100, -100, 100, 100]}, "roads": [{"type": "side", "width": 8, "points": [[-100, 0], [100, 0]]}],
            "buildings": [{"points": [[110, -10], [130, -10], [130, 10], [110, 10]], "tags": {"building": "yes"}, "height": 6.0},
                          {"points": [[20, 10], [30, 10], [30, 20], [20, 20]], "tags": {"building": "yes"}, "height": 6.0}]}
    data["meta"]["bounds"] = [-100, -100, 160, 100]
    return World(data, terrain=Terrain(-100, -100, step, nx, ny, heights))


class HorizonTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.w = ridge_world()
        self.r = R.Renderer3D(self.w, style="street")
        self.r._set_camera(types.SimpleNamespace(x=0.0, y=0.0, z=3.0, yaw=0.0, pitch=0.05))
        self.r._compute_horizon()

    def test_something_behind_the_ridge_is_cut(self):
        row = self.r._occ_row(120.0, 0.0, 0.0, 110.0)
        base = self.r.project(120.0, 0.0, 0.0)
        self.assertLess(row, base[1], "the ridge should hide the foot of the building behind it")

    def test_something_in_front_of_the_ridge_is_not(self):
        row = self.r._occ_row(25.0, 0.0, 0.0, 22.0)                      # flat ground in front: only below its foot
        self.assertGreaterEqual(row, self.r.project(25.0, 0.0, 0.0)[1] - 0.5)

    def test_flat_world_has_no_horizon(self):
        flat = World({"meta": {"bounds": [-50, -50, 50, 50]}, "roads": [], "buildings": []})
        r = R.Renderer3D(flat, style="street")
        r._set_camera(types.SimpleNamespace(x=0.0, y=0.0, z=3.0, yaw=0.0, pitch=0.05))
        r._compute_horizon()
        self.assertIsNone(r._occ)
        self.assertEqual(r._occ_row(30.0, 0.0, 0.0, 30.0), R.H)

    def test_frames_render_with_hills(self):
        from game.car import Car
        car = Car(0.0, 0.0, 0.0)
        cam = R.ChaseCamera(car, self.w)
        for _ in range(20):
            cam.update(car, 1 / 30)
        self.r.render(pygame.Surface((320, 180)), car, cam)

    def test_buildings_sit_on_their_highest_corner(self):
        w = self.w
        r = R.Renderer3D(w, style="street")
        b = r.buildings[1]
        hs = [w.ground(p[0], p[1]) for p in b[5]]
        self.assertAlmostEqual(r._building_ground(1)[0], max(hs + [w.ground(b[0], b[1])]))


class TrimAndCutTests(unittest.TestCase):
    ROAD = {"type": "side", "width": 8.0, "points": [[-50, 0], [50, 0]]}

    def test_trim_cuts_a_building_back_to_the_road_edge(self):
        b = {"points": [[-5, 2], [5, 2], [5, 14], [-5, 14]], "tags": {}}
        idx = M.Index([b], [dict(self.ROAD)], skip_lanes=False)
        self.assertTrue(M.trim_clear(idx, 0))
        self.assertTrue(all(p[1] >= 4.29 for p in b["points"]))           # 4 m half width + 0.3 m margin
        self.assertGreater(M.poly_area(b["points"]), 90)

    def test_trim_refuses_to_eat_most_of_a_building(self):
        b = {"points": [[-5, -3], [5, -3], [5, 6], [-5, 6]], "tags": {}}
        before = [list(p) for p in b["points"]]
        idx = M.Index([b], [dict(self.ROAD)], skip_lanes=False)
        self.assertFalse(M.trim_clear(idx, 0))
        self.assertEqual(b["points"], before)

    def test_driveway_stops_at_the_building(self):
        garage = [[0, 10], [6, 10], [6, 16], [0, 16]]
        cut = M.cut_road_outside([[3, 0], [3, 13]], [garage])
        self.assertIsNotNone(cut)
        self.assertLess(max(p[1] for p in cut), 10.3)
        self.assertIsNone(M.cut_road_outside([[3, 11], [3, 15]], [garage]))  # wholly inside: the driveway goes

    def test_swallowed(self):
        big = [[0, 0], [20, 0], [20, 20], [0, 20]]
        self.assertTrue(M.swallowed([[5, 5], [8, 5], [8, 8], [5, 8]], big))
        self.assertFalse(M.swallowed([[15, 15], [25, 15], [25, 25], [15, 25]], big))


class SignTests(unittest.TestCase):
    def test_sign_is_moved_off_a_road(self):
        w = World({"meta": {"bounds": [-60, -60, 60, 60]}, "buildings": [],
                   "roads": [{"type": "side", "width": 8, "points": [[-50, 0], [50, 0]]},
                             {"type": "main", "width": 12, "points": [[10, -50], [10, 50]]}]})
        spot = SD._off_road(w, 12.0, 5.0, (1.0, 0.0), (0.0, 1.0))          # starts 4.6 m inside the main road
        self.assertIsNotNone(spot)
        self.assertFalse(w.on_road(*spot))
        self.assertEqual(SD._off_road(w, 30.0, 20.0, (1.0, 0.0), (0.0, 1.0)), (30.0, 20.0))   # already clear: unchanged

    def test_real_map_has_no_poles_on_roads(self):
        w = World.load(os.path.join(ROOT, "data", "amherst_map.json"))
        poles = [p for p in w.props if p["kind"] in ("stopsign", "signal", "crossbuck")]
        self.assertGreater(len(poles), 30)
        self.assertEqual([p for p in poles if w.on_road(p["x"], p["y"])], [])


class EditorNotesTests(unittest.TestCase):
    def test_notes_survive_an_editor_save(self):
        import io
        import shutil
        from contextlib import redirect_stdout
        import map_editor
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(os.path.join(ROOT, "data", "sample_map.json"), d)
            import json
            data = json.load(open(os.path.join(d, "sample_map.json")))
            b = data["buildings"][0]
            at = [round(v, 2) for v in M.centre(b["points"])]
            M.save(os.path.join(d, "map_edits.json"), dict(M.empty(), buildings={"delete": [], "replace": [
                {"at": at, "height": 9.5, "_note": "from the heritage register"}]}))
            with redirect_stdout(io.StringIO()):
                ed = map_editor.Editor(os.path.join(d, "sample_map.json"), os.path.join(d, "map_edits.json"),
                                       os.path.join(d, "custom_buildings.json"))
                ed.save()
            doc = M.load(os.path.join(d, "map_edits.json"))
            self.assertEqual(doc["buildings"]["replace"][0]["_note"], "from the heritage register")


if __name__ == "__main__":
    unittest.main()
