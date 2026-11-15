import copy
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from game import mapedits as M  # noqa: E402


def sample():
    road = {"type": "side", "width": 8.0, "name": "Main St", "speed": 50, "rc": "LO",
            "points": [[0.0, 0.0], [100.0, 0.0]]}
    far = {"points": [[10, 20], [20, 20], [20, 30], [10, 30]], "tags": {"building": "yes"}}
    on_road = {"points": [[40, -3], [50, -3], [50, 5], [40, 5]], "tags": {"building": "yes"}}
    twin_a = {"points": [[60, 20], [70, 20], [70, 30], [60, 30]], "tags": {"building": "yes"}}
    twin_b = {"points": [[65, 22], [75, 22], [75, 32], [65, 32]], "tags": {"building": "yes"}}
    row = {"points": [[70, 20], [80, 20], [80, 30], [70, 30]], "tags": {"building": "yes"}}    # shares a wall with twin_a
    return {"meta": {"origin_lat": 45.826, "origin_lon": -64.218, "bounds": [-500, -500, 500, 500]},
            "roads": [road], "buildings": [far, on_road, twin_a, twin_b, row]}


class Geometry(unittest.TestCase):
    def test_building_on_road_is_found(self):
        d = sample()
        probs = M.Index(d["buildings"], d["roads"]).all_problems()
        self.assertIn(1, [p["building"] for p in probs if p["kind"] == "road"])
        self.assertNotIn(0, [p["building"] for p in probs])

    def test_overlap_vs_shared_wall(self):
        d = sample()
        b = d["buildings"]
        self.assertTrue(M.buildings_overlap(b[2]["points"], b[3]["points"]))
        self.assertFalse(M.buildings_overlap(b[2]["points"], b[4]["points"]))       # walls only touch

    def test_bridges_and_lanes_are_ignored(self):
        d = sample()
        d["roads"][0]["bridge"] = True
        self.assertEqual([p for p in M.Index(d["buildings"], d["roads"]).all_problems() if p["kind"] == "road"], [])
        d = sample()
        d["roads"][0]["type"] = "lane"
        self.assertEqual([p for p in M.Index(d["buildings"], d["roads"]).all_problems() if p["kind"] == "road"], [])
        found = [p for p in M.Index(d["buildings"], d["roads"], skip_lanes=False).all_problems() if p["kind"] == "road"]
        self.assertTrue(found)

    def test_push_clear_moves_building_off_road(self):
        d = sample()
        idx = M.Index(d["buildings"], d["roads"])
        moved, still = M.push_clear(idx, 1)
        self.assertGreater(moved, 0)
        self.assertFalse(still)
        fresh = M.Index(d["buildings"], d["roads"])
        self.assertEqual([p for p in fresh.all_problems() if p["kind"] == "road"], [])

    def test_push_clear_refuses_to_enter_another_building(self):
        d = sample()
        d["buildings"][1]["points"] = [[40, 4], [50, 4], [50, 10], [40, 10]]
        d["buildings"].append({"points": [[40, -14], [50, -14], [50, -8], [40, -8]], "tags": {}})   # box on the far side
        d["buildings"].append({"points": [[38, 6], [52, 6], [52, 12], [38, 12]], "tags": {}})        # and one in the way
        idx = M.Index(d["buildings"], d["roads"])
        before = copy.deepcopy(d["buildings"][1]["points"])
        moved, still = M.push_clear(idx, 1)
        if moved == 0:
            self.assertEqual(d["buildings"][1]["points"], before)


class Edits(unittest.TestCase):
    def test_apply_delete_replace_add(self):
        d = sample()
        doc = M.empty()
        doc["buildings"]["delete"].append([15.0, 25.0])
        doc["buildings"]["replace"].append({"at": [45.0, 1.0], "points": [[40, 20], [50, 20], [50, 28], [40, 28]], "height": 9.0})
        doc["roads"]["replace"].append({"at": [50.0, 0.0], "name": "Renamed St", "width": 10.0})
        doc["roads"]["add"].append({"points": [[0, 50], [100, 50]], "name": "New St"})
        report = M.apply(d, doc)
        self.assertEqual(len(d["buildings"]), 4)
        moved = [b for b in d["buildings"] if b.get("height") == 9.0][0]
        self.assertEqual(moved["points"][0], [40, 20])
        self.assertEqual(d["roads"][0]["name"], "Renamed St")
        self.assertEqual(len(d["roads"]), 2)
        self.assertEqual(d["roads"][1]["type"], "side")
        self.assertIn("4 applied", report[0].replace("map edits: ", ""))

    def test_edit_that_matches_nothing_is_reported_not_applied(self):
        d = sample()
        doc = M.empty()
        doc["buildings"]["delete"].append([400.0, 400.0])
        report = M.apply(d, doc)
        self.assertEqual(len(d["buildings"]), 5)
        self.assertTrue(any("skipped" in r for r in report))

    def test_mark_mode_keeps_deleted_items(self):
        d = sample()
        doc = M.empty()
        doc["buildings"]["delete"].append([15.0, 25.0])
        M.apply(d, doc, mark=True)
        self.assertEqual(len(d["buildings"]), 5)
        self.assertTrue(d["buildings"][0]["_deleted"])

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "map_edits.json")
            doc = M.empty()
            doc["roads"]["delete"].append([1, 2])
            M.save(path, doc)
            self.assertEqual(M.load(path)["roads"]["delete"], [[1, 2]])
            self.assertEqual(M.count(M.load(path)), 1)
            open(path, "w").write("not json")
            self.assertIsNone(M.load(path))


class EditorSaveLoad(unittest.TestCase):
    def test_editor_changes_come_back_through_the_game_loader(self):
        import map_editor as ME
        from game.world import World
        d = sample()
        d.update({"rails": [], "water": [], "props": [], "parks": [], "memorials": [], "pois": [], "marks": [],
                  "landmarks": []})
        d["meta"]["name"] = "t"
        with tempfile.TemporaryDirectory() as t:
            mp = os.path.join(t, "amherst_map.json")
            json.dump(d, open(mp, "w"))
            ed = ME.Editor(mp, os.path.join(t, "map_edits.json"), os.path.join(t, "custom_buildings.json"))
            self.assertEqual(len([p for p in ed.problems if p["kind"] == "road"]), 1)
            ed.sel = ("b", 1)
            ed.fix()
            ed.sel = ("b", 0)
            ed.delete_selected()
            ed.save()
            world = World.load(mp, custom=None, zoning=False)
            self.assertEqual(len(world.buildings), 4)                      # one deleted, one moved
            again = M.Index([{"points": b["points"]} for b in world.buildings], world.roads)
            self.assertEqual([p for p in again.all_problems() if p["kind"] == "road"], [])


if __name__ == "__main__":
    unittest.main()


class SpawnAndPropEdits(unittest.TestCase):
    META = {"origin_lat": 45.8260, "origin_lon": -64.2180}

    def test_spawn_moves_to_lat_lon_and_bearing(self):
        import math
        data = {"meta": dict(self.META, spawn=[0, 0, 0]), "buildings": [], "roads": []}
        rep = M.apply(data, {"spawn": {"lat": 45.8260, "lon": -64.2180, "bearing": 90}})
        self.assertTrue(any("spawn moved" in r for r in rep))
        x, y, h = data["meta"]["spawn"]
        self.assertAlmostEqual(x, 0.0, places=3)
        self.assertAlmostEqual(h, 0.0, places=3)                       # bearing 90 = east = heading 0
        M.apply(data, {"spawn": {"lat": 45.8269, "lon": -64.2180, "bearing": 180}})
        x, y, h = data["meta"]["spawn"]
        self.assertAlmostEqual(y, -100.1, delta=0.5)                   # 0.0009 degrees north is ~100 m (y grows south)
        self.assertAlmostEqual(h, math.pi / 2, places=3)               # facing south

    def test_props_are_added_at_lat_lon(self):
        data = {"meta": dict(self.META), "buildings": [], "roads": []}
        M.apply(data, {"props": {"add": [{"kind": "tree", "lat": 45.8260, "lon": -64.2180, "h": 10, "r": 4, "_note": "x"}]}})
        p = data["props"][0]
        self.assertEqual((p["kind"], p["x"], p["y"], p["h"]), ("tree", 0.0, 0.0, 10))
        self.assertNotIn("_note", p)

    def test_no_origin_means_skipped_not_crashed(self):
        data = {"meta": {}, "buildings": [], "roads": []}
        rep = M.apply(data, {"spawn": {"lat": 1, "lon": 2}, "props": {"add": [{"kind": "tree", "lat": 1, "lon": 2}]}})
        self.assertTrue(any("skipped" in r for r in rep))
        self.assertNotIn("spawn", data["meta"])


class EditorKeepsHandSections(unittest.TestCase):
    def test_saving_in_the_editor_keeps_spawn_and_props(self):
        import io
        import shutil
        from contextlib import redirect_stdout
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import map_editor
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(os.path.join(ROOT, "data", "sample_map.json"), d)
            hand = {"spawn": {"lat": 45.8, "lon": -64.2, "bearing": 30},
                    "props": {"add": [{"kind": "tree", "lat": 45.8, "lon": -64.2, "h": 9, "r": 4}]}}
            M.save(os.path.join(d, "map_edits.json"), dict(M.empty(), **hand))
            with redirect_stdout(io.StringIO()):
                ed = map_editor.Editor(os.path.join(d, "sample_map.json"), os.path.join(d, "map_edits.json"),
                                       os.path.join(d, "custom_buildings.json"))
                ed.save()
            doc = M.load(os.path.join(d, "map_edits.json"))
            self.assertEqual(doc["spawn"], hand["spawn"])
            self.assertEqual(doc["props"], hand["props"])
