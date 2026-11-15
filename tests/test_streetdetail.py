"""Street detail: paint rules, sidewalks, marks -> stop bars/crosswalks/signs, furniture, rendering."""
import copy
import json
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

import landmarks as LM  # noqa: E402
import nsrn  # noqa: E402
import osm_to_map  # noqa: E402
from game import streetdetail as SD  # noqa: E402
from game.car import Car  # noqa: E402
from game.render3d import ChaseCamera, Renderer3D  # noqa: E402
from game.world import World  # noqa: E402


def rd(rtype="side", **kw):
    r = {"type": rtype, "width": 8.0, "name": "Elm St", "points": [[0, 0], [100, 0]], "speed": 50}
    r.update(kw)
    return r


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def world(roads, marks=(), buildings=(), procedural=False):
    return World({"meta": {"bounds": [-400, -400, 400, 400], "procedural_props": procedural},
                  "roads": copy.deepcopy(roads), "buildings": list(buildings), "marks": list(marks)})


class PaintRules(unittest.TestCase):
    def test_marking_by_class(self):
        self.assertEqual(SD.marking(rd("lane")), SD.NONE)
        self.assertEqual(SD.marking(rd("side", service="driveway")), SD.NONE)
        self.assertEqual(SD.marking(rd("main", surface="gravel")), SD.NONE)
        self.assertEqual(SD.marking(rd("main")), SD.DOUBLE_YELLOW)
        self.assertEqual(SD.marking(rd("main", lanes=3)), SD.DASH_WHITE)
        self.assertEqual(SD.marking(rd("main", oneway=1)), SD.EDGES)
        self.assertEqual(SD.marking(rd("main", speed=100)), SD.HIGHWAY)
        self.assertEqual(SD.marking(rd("main", speed=100, oneway=1)), SD.HIGHWAY)
        self.assertEqual(SD.marking(rd("side", ramp=True, oneway=1)), SD.EDGES)
        self.assertEqual(SD.marking(rd("side", rc="CO")), SD.DASH_YELLOW)
        self.assertEqual(SD.marking(rd("side", rc="LO")), SD.NONE)
        self.assertEqual(SD.marking(rd("side", rc="CO", oneway=1)), SD.NONE)

    def test_sidewalks(self):
        self.assertEqual(SD.sidewalk(rd("side"), False), SD.CONCRETE)
        self.assertEqual(SD.sidewalk(rd("side"), True), SD.BRICK)
        self.assertEqual(SD.sidewalk(rd("lane"), True), SD.EDGE)
        self.assertEqual(SD.sidewalk(rd("main", speed=100), True), SD.EDGE)
        self.assertEqual(SD.sidewalk(rd("side", speed=80), False), SD.EDGE)
        self.assertEqual(SD.sidewalk(rd("side", surface="gravel"), False), SD.EDGE)

    def test_downtown_is_where_sandstone_and_brick_are(self):
        d = SD.Downtown([{"points": rect(0, 0, 20, 20), "material": "sandstone"},
                         {"points": rect(500, 0, 520, 20), "material": "clapboard"}])
        self.assertTrue(d.near(10, 10))
        self.assertTrue(d.near(40, 10))
        self.assertFalse(d.near(510, 10))
        self.assertFalse(d.near(200, 10))


class DataSide(unittest.TestCase):
    def test_nsrn_surface_lanes_class(self):
        self.assertEqual(nsrn._lanes("ROAD - Local - 2 Lanes - Paved"), 2)
        self.assertEqual(nsrn._lanes("RAMP - 1 Lane - Paved"), 1)
        self.assertIsNone(nsrn._lanes("TRACK"))
        data = json.load(open(os.path.join(ROOT, "data", "amherst_map.json")))
        roads = data["roads"]
        self.assertTrue(any(r.get("surface") == "gravel" for r in roads))
        self.assertTrue(all(r.get("rc") for r in roads))
        self.assertTrue(all(r.get("surface") == "gravel" for r in roads if r.get("rc") == "TK"))

    def test_osm_nodes_become_marks(self):
        f = osm_to_map._mark_of
        self.assertEqual(f({"highway": "stop"}), {"kind": "stop"})
        self.assertEqual(f({"highway": "traffic_signals"}), {"kind": "signal"})
        self.assertEqual(f({"highway": "crossing", "crossing": "marked"}), {"kind": "crossing", "style": "marked"})
        self.assertEqual(f({"railway": "level_crossing"}), {"kind": "rail_crossing"})
        self.assertEqual(f({"emergency": "fire_hydrant"}), {"kind": "hydrant"})
        self.assertIsNone(f({"highway": "residential"}))
        self.assertIsNone(f({}))

    def test_shipped_map_has_marks(self):
        data = json.load(open(os.path.join(ROOT, "data", "amherst_map.json")))
        kinds = {m["kind"] for m in data["marks"]}
        self.assertTrue({"stop", "signal", "crossing", "rail_crossing"} <= kinds)

    def test_bank_landmark_matches_only_the_named_bank(self):
        """The sandstone-corner entry must not restyle every bank (it once matched amenity=bank for all)."""
        spec = LM.load_spec(LM.DEFAULT_SPEC)
        data = {"meta": {"bounds": [-900, -900, 900, 900]}, "roads": [], "parks": [], "memorials": [], "pois": [],
                "buildings": [{"points": rect(10, 10, 30, 30), "tags": {"name": "RBC", "amenity": "bank"}},
                              {"points": rect(60, 10, 80, 30), "tags": {"name": "CIBC", "amenity": "bank"}}]}
        LM.apply_landmarks(data, spec, to_xy=lambda lat, lon: ((lon + 64.21318) * 80000.0, -(lat - 45.83315) * 111000.0))
        rbc, cibc = data["buildings"]
        self.assertEqual(rbc.get("height"), 14.0)
        self.assertIsNone(cibc.get("height"))


class MarkDetails(unittest.TestCase):
    T = [rd("main", name="Main St", points=[[-200, 0], [200, 0]], width=10),
         rd("side", name="Elm St", points=[[0, 100], [0, 0]], width=8)]          # Elm ends at the junction (0, 0)

    def test_stop_sign_on_the_minor_road_with_a_bar_in_the_right_lane(self):
        w = world(self.T, [{"kind": "stop", "x": 0.0, "y": 0.0}])
        signs = [p for p in w.props if p["kind"] == "stopsign"]
        self.assertEqual(len(signs), 1)
        s = signs[0]
        self.assertGreater(s["y"], 0.0)                                  # on Elm St's side of the junction
        # Elm runs toward -y (north); a driver heading that way has +x on their right
        self.assertGreater(s["x"], 0.0)
        bar = w.paint[0]
        self.assertTrue(all(p[1] > 0.0 for p in bar["pts"]))             # before the junction, not in it
        self.assertTrue(all(p[0] > 0.0 for p in bar["pts"]))             # right-hand lane only
        self.assertEqual(len(w.paint), 1)

    def test_oneway_road_leaving_the_junction_gets_no_stop(self):
        w = world([rd("side", name="Out St", points=[[0, 0], [0, 100]], oneway=1)],
                  [{"kind": "stop", "x": 0.0, "y": 0.0}])
        self.assertEqual([p for p in w.props if p["kind"] == "stopsign"], [])
        self.assertEqual(w.paint, [])

    def test_oneway_road_arriving_at_the_junction_gets_one(self):
        w = world([rd("side", name="In St", points=[[0, 100], [0, 0]], oneway=1)],
                  [{"kind": "stop", "x": 0.0, "y": 0.0}])
        self.assertEqual(len([p for p in w.props if p["kind"] == "stopsign"]), 1)

    def test_signals_cover_every_approach_and_take_turns(self):
        t = [rd("main", name="A", points=[[-200, 0], [0, 0]]), rd("main", name="A", points=[[200, 0], [0, 0]]),
             rd("side", name="B", points=[[0, 100], [0, 0]])]
        w = world(t, [{"kind": "signal", "x": 0.0, "y": 0.0}])
        sig = [p for p in w.props if p["kind"] == "signal"]
        self.assertEqual(len(sig), 3)
        self.assertEqual({p["ph"] for p in sig}, {0, 1})

    def test_crosswalk_bars_stay_on_the_road(self):
        w = world(self.T, [{"kind": "crossing", "style": "marked", "x": 50.0, "y": 0.0}])
        self.assertGreaterEqual(len(w.paint), 4)
        for bar in w.paint:
            for x, y in bar["pts"]:
                self.assertLessEqual(abs(y), 5.0 + 1e-6)
                self.assertLess(abs(x - 50.0), 2.0)

    def test_unmarked_crossing_has_no_paint(self):
        w = world(self.T, [{"kind": "crossing", "style": "unmarked", "x": 50.0, "y": 0.0}])
        self.assertEqual(w.paint, [])

    def test_rail_crossing_gets_a_sign_each_way(self):
        w = world(self.T, [{"kind": "rail_crossing", "x": 50.0, "y": 0.0}])
        signs = [p for p in w.props if p["kind"] == "crossbuck"]
        self.assertEqual(len(signs), 2)
        self.assertLess(min(p["x"] for p in signs), 50.0)                # one either side of the track
        self.assertGreater(max(p["x"] for p in signs), 50.0)
        self.assertNotEqual(round(signs[0]["x"]), round(signs[1]["x"]))

    def test_marks_far_from_any_road_are_ignored(self):
        w = world(self.T, [{"kind": "stop", "x": 300.0, "y": 300.0}, {"kind": "crossing", "x": 300.0, "y": 300.0}])
        self.assertEqual(w.paint, [])
        self.assertEqual([p for p in w.props if p["kind"] != "tree"], [])


class Furniture(unittest.TestCase):
    DOWN = [{"points": rect(x, 12, x + 18, 30), "material": "sandstone"} for x in range(0, 400, 20)]
    ROADS = [rd("side", name="Main St", points=[[0, 0], [400, 0]], width=9)]

    def kinds(self, w):
        out = {}
        for p in w.props:
            out.setdefault(p["kind"], []).append(p)
        return out

    def test_hydrants_everywhere_benches_and_bins_only_downtown(self):
        far = [rd("side", name="Far St", points=[[0, 300], [400, 300]], width=9)]
        w = world(self.ROADS + far, buildings=self.DOWN, procedural=True)
        k = self.kinds(w)
        self.assertTrue(k.get("hydrant"))
        self.assertTrue(k.get("bench") and k.get("bin"))
        for p in k["bench"] + k["bin"]:
            self.assertLess(abs(p["y"]), 20.0)                           # none along Far St (no sandstone there)
        for p in k["hydrant"]:
            self.assertGreater(w.road_clearance(p["x"], p["y"]), 0.5)

    def test_deterministic(self):
        a = world(self.ROADS, buildings=self.DOWN, procedural=True)
        b = world(self.ROADS, buildings=self.DOWN, procedural=True)
        self.assertEqual([(p["kind"], p["x"], p["y"]) for p in a.props], [(p["kind"], p["x"], p["y"]) for p in b.props])

    def test_no_furniture_on_lanes_gravel_or_highways(self):
        t = [rd("lane", points=[[0, 0], [400, 0]]), rd("side", surface="gravel", points=[[0, 100], [400, 100]]),
             rd("main", speed=100, points=[[0, 200], [400, 200]])]
        w = world(t, buildings=self.DOWN, procedural=True)
        self.assertFalse([p for p in w.props if p["kind"] in ("hydrant", "bench", "bin")])

    def test_incomplete_furniture_from_osm_props_is_dropped(self):
        data = {"meta": {"bounds": [-400, -400, 400, 400], "procedural_props": False}, "roads": [], "buildings": [],
                "props": [{"kind": "bench", "x": 3.0, "y": 3.0}]}
        self.assertEqual(len(World(data).props), 0)


class Drawing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def frame(self, w, style, x, y, heading):
        r = Renderer3D(w, style)
        surf = pygame.Surface((320, 224))
        c = Car(x, y, heading)
        r.render(surf, c, ChaseCamera(c, w), [], 3.0, ())
        return r, surf

    def test_all_paint_and_furniture_render_in_both_styles(self):
        roads = [rd("main", name="Main St", points=[[-200, 0], [200, 0]], width=10),
                 rd("main", name="Hwy", points=[[-200, 60], [200, 60]], width=9, speed=100, oneway=1),
                 rd("side", name="Elm St", points=[[0, 100], [0, 5]], width=8, rc="CO"),
                 rd("lane", name="Track", points=[[-200, -60], [200, -60]], width=4, surface="gravel")]
        marks = [{"kind": "stop", "x": 0, "y": 0}, {"kind": "signal", "x": 40, "y": 0},
                 {"kind": "crossing", "style": "marked", "x": -30, "y": 0}, {"kind": "rail_crossing", "x": 80, "y": 0}]
        bld = [{"points": rect(x, 12, x + 18, 30), "material": "brick"} for x in range(-120, 120, 20)]
        w = world(roads, marks, bld, procedural=True)
        for style in ("street", "retro"):
            r, surf = self.frame(w, style, -60.0, 0.0, 0.0)
            self.assertGreater(r.polys, 30)
        px = [surf.get_at((x, y))[:3] for x in range(0, 320, 4) for y in range(110, 224, 4)]
        self.assertGreater(len(set(px)), 6)                              # not a blank frame

    def test_real_map_renders_with_detail(self):
        w = World.load(os.path.join(ROOT, "data", "amherst_map.json"))
        r, _ = self.frame(w, "street", *w.spawn()[:2], 0.5)
        self.assertGreater(r.polys, 50)
        kinds = {p["kind"] for p in w.props}
        self.assertTrue({"hydrant", "stopsign", "signal", "crossbuck", "bench"} <= kinds)


if __name__ == "__main__":
    unittest.main()
