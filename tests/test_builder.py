"""Your own buildings: presets, placement maths, roofs, loading, build mode."""
import copy
import json
import math
import os
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

import make_sample_map  # noqa: E402
from game import builder  # noqa: E402
from game import config as C  # noqa: E402
from game.buildmode import BuildMode  # noqa: E402
from game.car import Car  # noqa: E402
from game.render3d import ChaseCamera, Renderer3D  # noqa: E402
from game.world import World  # noqa: E402

PRESET_ROOF = builder.PRESETS["house"]["roof"]
META = {"bounds": [-300, -300, 300, 300], "origin_lat": 45.8167, "origin_lon": -64.2167}
ROADS = [{"type": "side", "width": 8, "name": "Elm St", "points": [[-300, 0], [300, 0]]}]


class Placement(unittest.TestCase):
    def test_project_roundtrip(self):
        x, y = builder.project(META, 45.83, -64.21)
        lat, lon = builder.unproject(META, x, y)
        self.assertAlmostEqual(lat, 45.83, places=6)
        self.assertAlmostEqual(lon, -64.21, places=6)

    def test_footprint_front_faces_bearing(self):
        for bearing in (0, 90, 180, 270, 33):
            pts = builder.footprint(100, 100, bearing, 10, 6)
            fx, fy = builder.compass_vec(bearing)
            mx = (pts[2][0] + pts[3][0]) / 2 - 100                 # midpoint of the front edge, relative to the centre
            my = (pts[2][1] + pts[3][1]) / 2 - 100
            self.assertAlmostEqual(mx, fx * 3, places=1)
            self.assertAlmostEqual(my, fy * 3, places=1)
            self.assertAlmostEqual(math.dist(pts[0], pts[1]), 10, places=1)

    def test_default_facing_is_nearest_street(self):
        b, w = builder.make_building({"x": 50, "y": 40, "preset": "house"}, META, ROADS)     # south of Elm St
        cx, cy = builder.centroid(b)
        self.assertAlmostEqual(cx, 50, places=0)
        self.assertEqual(w, [])
        # front faces north (the street): the north edge is the front, so the front midpoint is the northern edge
        self.assertLess(min(p[1] for p in b["points"]), cy)

    def test_setback_puts_front_off_the_kerb(self):
        b, _ = builder.make_building({"x": 50, "y": 60, "preset": "house", "setback": 5}, META, ROADS)
        front_y = min(p[1] for p in b["points"])
        self.assertAlmostEqual(front_y, 4 + 5, delta=0.6)                 # kerb at y=4, plus 5 m

    def test_overlapping_a_road_is_reported(self):
        _b, w = builder.make_building({"x": 50, "y": 2, "preset": "shop"}, META, ROADS)
        self.assertTrue(any("road" in m for m in w))

    def test_bad_preset_and_missing_position(self):
        _b, w = builder.make_building({"x": 0, "y": 30, "preset": "castle"}, META, ROADS)
        self.assertTrue(any("preset" in m for m in w))
        with self.assertRaises(ValueError):
            builder.make_building({"preset": "house"}, META, ROADS)

    def test_every_preset_builds(self):
        for name in builder.PRESETS:
            b, w = builder.make_building({"x": 0, "y": 80, "preset": name}, META, ROADS)
            self.assertEqual(w, [], name)
            self.assertEqual(len(b["points"]), 4)


class Roofs(unittest.TestCase):
    PTS = [[0, 0], [12, 0], [12, 8], [0, 8]]

    def test_gable_and_hip_and_mansard_faces(self):
        for kind, n in (("gable", 4), ("hip", 4), ("mansard", 5)):
            faces = builder.roof_faces(self.PTS, 6.0, kind, 3.0)
            self.assertEqual(len(faces), n, kind)
            zs = [p[2] for f in faces for p in f]
            self.assertAlmostEqual(min(zs), 6.0)
            self.assertAlmostEqual(max(zs), 9.0)

    def test_roof_normals_point_out_and_up(self):
        faces = builder.roof_faces(self.PTS, 6.0, "gable", 3.0)
        for f in faces[:2]:                                            # the two slopes face up and out
            n = builder.face_normal(f, (6, 4, 6.0))
            self.assertGreater(n[2], 0.3)
        self.assertEqual(builder.roof_faces(self.PTS, 6.0, "flat", 3.0), [])
        self.assertEqual(builder.roof_faces([[0, 0], [1, 0], [1, 1]], 6.0, "gable", 3.0), [])


class Loading(unittest.TestCase):
    def test_apply_custom_adds_skips_and_replaces(self):
        data = {"meta": copy.deepcopy(META), "roads": copy.deepcopy(ROADS),
                "buildings": [{"points": [[48, 38], [52, 38], [52, 42], [48, 42]]}]}
        doc = {"buildings": [{"name": "A", "preset": "house", "x": 50, "y": 40, "replace_radius": 6},
                             {"name": "far", "preset": "house", "x": 5000, "y": 0},
                             {"name": "nopos", "preset": "house"}]}
        report = builder.apply_custom(data, doc)
        self.assertEqual(len(data["buildings"]), 1)                    # old one replaced by A
        self.assertTrue(data["buildings"][0]["custom"])
        self.assertTrue(any("outside the map" in r for r in report))
        self.assertTrue(any("SKIPPED nopos" in r for r in report))

    def test_world_load_applies_custom_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mp = os.path.join(tmp, "m.json")
            data = make_sample_map.build()
            with open(mp, "w") as f:
                json.dump(data, f)
            n0 = len(World.load(mp).buildings)
            with open(os.path.join(tmp, "custom_buildings.json"), "w") as f:
                json.dump({"buildings": [{"preset": "house", "x": 0, "y": 200}]}, f)
            self.assertEqual(len(World.load(mp).buildings), n0 + 1)
            self.assertEqual(len(World.load(mp, custom=None).buildings), n0)

    def test_shipped_files_are_valid(self):
        for name in ("custom_buildings.json", "custom_buildings.example.json"):
            with open(os.path.join(ROOT, "data", name)) as f:
                doc = json.load(f)
            with open(os.path.join(ROOT, "data", "amherst_map.json")) as f:
                data = json.load(f)
            report = builder.apply_custom(data, doc)
            self.assertFalse(any(r.startswith("SKIPPED") for r in report), report)


class Styles(unittest.TestCase):
    def test_shipped_styles_are_all_valid(self):
        self.assertGreaterEqual(len(builder.STYLES), 20)
        for name in builder.STYLES:
            s, problems = builder.resolve({"style": name})
            self.assertEqual(problems, [], name)
            b, warns = builder.make_building({"style": name, "x": 0, "y": 40, "facing": 0}, META, [])
            self.assertEqual(warns, [], name)
            self.assertEqual(len(b["points"]), 4)

    def test_mall_styles_are_wide_and_corrugated(self):
        s, problems = builder.resolve({"style": "ribbed_shopping_mall"})
        self.assertEqual(problems, [])
        self.assertEqual(s["width"], 175)
        self.assertEqual(s["material"], "corrugated")
        s, problems = builder.resolve({"preset": "shop", "width": 250})
        self.assertTrue(problems)

    def test_style_overrides_preset_and_spec_overrides_style(self):
        builder.STYLES["_t"] = {"preset": "house", "width": 11, "height": 7.0, "roof": "hip", "roof_height": 3.0,
                                "roof_colour": [10, 20, 30], "colour": [200, 190, 180], "material": "clapboard"}
        try:
            b, _ = builder.make_building({"style": "_t", "x": 0, "y": 40, "facing": 0}, META, [])
            self.assertEqual(b["roof"], "hip")
            self.assertEqual(b["roof_colour"], [10, 20, 30])
            self.assertEqual(b["colour"], [200, 190, 180])
            self.assertAlmostEqual(b["height"], 7.0)
            b2, _ = builder.make_building({"style": "_t", "height": 9.0, "x": 0, "y": 40, "facing": 0}, META, [])
            self.assertAlmostEqual(b2["height"], 9.0)
        finally:
            del builder.STYLES["_t"]

    def test_unknown_style_is_reported_not_fatal(self):
        s, problems = builder.resolve({"style": "no_such_style"})
        self.assertTrue(any("unknown style" in p for p in problems))
        self.assertEqual(s["roof"], PRESET_ROOF)

    def test_missing_styles_file_gives_empty(self):
        self.assertEqual(builder.load_styles("/no/such/file.json"), {})

    def test_build_mode_cycles_into_styles_and_saves_style_name(self):
        from game import buildmode
        names = [k for kind, k in buildmode.ORDER if kind == "style"]
        self.assertTrue(names)
        w = World({"meta": dict(META, procedural_props=False), "roads": ROADS, "buildings": []})
        r = Renderer3D(w, "street")
        with tempfile.TemporaryDirectory() as d:
            bm = BuildMode(w, r, os.path.join(d, "c.json"))
            bm.toggle()
            bm.preset_i = buildmode.ORDER.index(("style", names[0]))
            car = Car(0.0, 0.0, 0.0)
            bm.update(car)
            self.assertTrue(bm.place(car))
            saved = json.load(open(os.path.join(d, "c.json")))["buildings"][0]
            self.assertEqual(saved["style"], names[0])
            self.assertNotIn("preset", saved)


class BuildingMode(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.world = World(make_sample_map.build())
        self.r3d = Renderer3D(self.world, "street")
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "custom.json")
        self.bm = BuildMode(self.world, self.r3d, self.path)
        road = max((r for r in self.world.roads if r["type"] != "lane"),
                   key=lambda r: abs(r["points"][-1][0] - r["points"][0][0]) + abs(r["points"][-1][1] - r["points"][0][1]))
        (ax, ay), (bx, by) = road["points"][0], road["points"][1]
        self.car = Car((ax + bx) / 2, (ay + by) / 2, math.atan2(by - ay, bx - ax))

    def tearDown(self):
        self.tmp.cleanup()

    def test_ghost_place_undo(self):
        self.bm.toggle()
        n0 = len(self.world.buildings)
        self.bm.update(self.car)
        self.assertEqual(len(self.world.buildings), n0 + 1)            # the ghost
        for _ in range(5):                                             # moving does not pile up ghosts
            self.bm.update(self.car)
        self.assertEqual(len(self.world.buildings), n0 + 1)
        ok = self.bm.place(self.car)
        if ok:
            with open(self.path) as f:
                saved = json.load(f)
            self.assertEqual(len(saved["buildings"]), 1)
            self.assertIn("lat", saved["buildings"][0])
            gi = self.bm.placed[-1][0]
            cx, cy = builder.centroid(self.world.buildings[gi])
            self.assertTrue(self.world.in_building(cx, cy))
            self.assertTrue(self.bm.undo())
            self.assertFalse(self.world.in_building(cx, cy))
            with open(self.path) as f:
                self.assertEqual(json.load(f)["buildings"], [])
        else:
            self.assertIn("Can't place", self.bm.message)              # refuses spots that overlap a road

    def test_toggle_off_removes_ghost(self):
        self.bm.toggle()
        self.bm.update(self.car)
        gi = self.bm.ghost
        self.bm.toggle()
        self.assertIsNone(self.bm.ghost)
        cx, cy = builder.centroid(self.world.buildings[gi])
        self.assertFalse(self.world.in_building(cx, cy))

    def test_cycle_flip_turn(self):
        first = self.bm.preset
        self.bm.cycle(1)
        self.assertNotEqual(self.bm.preset, first)
        self.bm.cycle(-1)
        self.assertEqual(self.bm.preset, first)
        self.bm.flip()
        self.assertEqual(self.bm.side, -1)
        self.bm.rotate(15)
        self.assertEqual(self.bm.turn, 15)
        self.assertGreaterEqual(len(self.bm.hud_lines()), 2)


class Drawing(unittest.TestCase):
    def test_roofed_buildings_render_in_both_styles(self):
        pygame.init()
        data = make_sample_map.build()
        builder.apply_custom(data, {"buildings": [{"preset": p, "x": 20 + 14 * i, "y": 30} for i, p in
                                                  enumerate(("house", "cottage", "victorian", "church"))]})
        w = World(data)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        car = Car(30, 0, 0.0)
        for style in ("street", "retro"):
            r = Renderer3D(w, style)
            r.render(surf, car, ChaseCamera(car, w), others=[])
            self.assertTrue(any(ex.get("roof") for ex in r.extras.values()))



class ChimneyAndLowBuildings(unittest.TestCase):
    def test_low_deck_is_allowed(self):
        b, warn = builder.make_building({"preset": "garage", "x": 0, "y": 40, "facing": 0, "height": 1.0,
                                         "roof": "flat"}, META, [])
        self.assertAlmostEqual(b["height"], 1.0)
        self.assertFalse([w for w in warn if "height" in w])

    def test_chimney_only_on_pitched_roofs(self):
        b, _ = builder.make_building({"preset": "house", "x": 0, "y": 40, "facing": 0, "chimney": 0.4}, META, [])
        self.assertAlmostEqual(b["chimney"], 0.4)
        b, _ = builder.make_building({"preset": "house", "x": 0, "y": 40, "facing": 0, "chimney": True}, META, [])
        self.assertAlmostEqual(b["chimney"], 0.3)
        b, _ = builder.make_building({"preset": "shop", "x": 0, "y": 40, "facing": 0, "chimney": 0.4}, META, [])
        self.assertNotIn("chimney", b)                                   # flat roof: nowhere to put it

    def test_chimney_sits_on_the_ridge_inside_the_footprint(self):
        from game import render3d as R
        from game.world import point_in_polygon
        pts = [(0, 0), (10, 0), (10, 6), (0, 6)]
        corners, z0, z1 = R._chimney(pts, 4.4, 3.6, 0.4)
        cx = sum(p[0] for p in corners) / 4
        cy = sum(p[1] for p in corners) / 4
        self.assertAlmostEqual(cy, 3.0)                                  # on the ridge (middle of the short side)
        self.assertGreater(cx, 5.0)                                      # towards one end
        self.assertTrue(all(point_in_polygon(x, y, pts) for x, y in corners))
        self.assertLess(z0, 8.0)
        self.assertGreater(z1, 8.0)


if __name__ == "__main__":
    unittest.main()
