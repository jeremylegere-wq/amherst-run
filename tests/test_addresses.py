"""Tests for real civic addresses: tools/fetch_addresses.py (network mocked) and game/addresses.py.

Run from the project root:  python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
import io

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import fetch_addresses as FA  # noqa: E402
from game.addresses import Addresses  # noqa: E402

LAT0, LON0 = 45.826, -64.218


def row(num, name, lat, lon, **extra):
    r = {"civicnum": str(num), "strname": name, "strsuffix": "St", "lat": str(lat), "long": str(lon)}
    r.update(extra)
    return r


class ConvertTests(unittest.TestCase):
    def test_street_and_number_are_built_from_the_parts(self):
        r = row(12, "Victoria", LAT0, LON0, civsuffix="A", strdir="E")
        self.assertEqual(FA.street_of(r), "Victoria St E")
        self.assertEqual(FA.number_of(r), "12A")
        self.assertEqual(FA.number_of({"civicnum": "7.0"}), "7")

    def test_projection_matches_the_map_converter(self):
        import osm_to_map
        for lat, lon in ((45.83315, -64.21318), (45.80, -64.25)):
            a = FA.latlon_to_xy(lat, lon, LAT0, LON0)
            b = osm_to_map.project(lat, lon, LAT0, LON0)
            self.assertAlmostEqual(a[0], b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)
            back = FA.xy_to_latlon(a[0], a[1], LAT0, LON0)
            self.assertAlmostEqual(back[0], lat, places=9)
            self.assertAlmostEqual(back[1], lon, places=9)

    def test_units_at_one_address_are_kept_once_and_bad_rows_dropped(self):
        rows = [row(5, "Church", LAT0, LON0, unit_num="1"), row(5, "Church", LAT0, LON0, unit_num="2"),
                {"civicnum": "9", "strname": "Church"}, row("", "Church", LAT0, LON0)]
        pts = FA.convert(rows, LAT0, LON0)
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0][2:], ["5", "Church St"])
        self.assertAlmostEqual(pts[0][0], 0.0, places=1)

    def test_map_bbox_covers_the_bounds(self):
        meta = {"origin_lat": LAT0, "origin_lon": LON0, "bounds": [-1000, -2000, 3000, 500]}
        s, w, n, e = FA.map_bbox(meta)
        self.assertTrue(s < LAT0 < n and w < LON0 < e)
        self.assertAlmostEqual(FA.latlon_to_xy(n, w, LAT0, LON0)[1], -2000, places=3)

    def test_pages_until_a_short_page(self):
        calls = []

        def fake(url):
            calls.append(url)
            return [row(1, "A", LAT0, LON0)] * (FA.PAGE if len(calls) < 3 else 7)
        rows = FA.fetch_rows((45.8, -64.3, 45.9, -64.1), fake)
        self.assertEqual(len(rows), 2 * FA.PAGE + 7)
        self.assertIn("within_box", calls[0])
        self.assertIn("offset=%d" % FA.PAGE, calls[1])

    def test_main_writes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "m.json")
            with open(mp, "w") as f:
                json.dump({"meta": {"origin_lat": LAT0, "origin_lon": LON0, "bounds": [-500, -500, 500, 500]}}, f)
            with redirect_stdout(io.StringIO()):
                FA.main(["--map", mp], fetch=lambda url: [row(3, "Spring", LAT0, LON0)])
            doc = json.load(open(os.path.join(d, "addresses.json")))
            self.assertEqual(doc["points"][0][2:], ["3", "Spring St"])
            self.assertIn("Open Government Licence", doc["licence"])
            self.assertIsNotNone(Addresses.load(os.path.join(d, "addresses.json")))


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.a = Addresses([[0, 0, "10", "Church St"], [30, 0, "12", "Church St"], [5, 5, "3", "Spring St"]])

    def test_nearest_on_the_same_street(self):
        self.assertEqual(self.a.near(26, 2, "Church St"), "12 Church St")
        self.assertEqual(self.a.near(4, 4, "Church St"), "10 Church St")    # Spring St is closer but a different street

    def test_nothing_far_away_or_on_an_unknown_street(self):
        self.assertIsNone(self.a.near(500, 500, "Church St"))
        self.assertIsNone(self.a.near(0, 0, "Nowhere Rd"))

    def test_missing_or_broken_file_is_ignored(self):
        self.assertIsNone(Addresses.load(os.path.join(ROOT, "no-such-file.json")))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{oops")
        try:
            with redirect_stdout(io.StringIO()):
                self.assertIsNone(Addresses.load(f.name))
        finally:
            os.unlink(f.name)


class MissionAddressTests(unittest.TestCase):
    def test_parcel_jobs_use_real_numbers_when_known(self):
        from game.missions import MissionManager
        from game.town import Town
        from game.world import World
        import make_sample_map
        data = make_sample_map.build()
        data["roads"].append({"type": "side", "width": 8, "name": "Test St", "points": [[5000, 0], [5200, 0]]})
        w = World(data)
        ms = MissionManager(w, Town(w, traffic=0), seed=1)
        made_up = ms.address(5020, 3)
        self.assertTrue(made_up.endswith("Test St"))
        w.addresses = Addresses([[5022, 12, "41", "Test St"]])
        self.assertEqual(ms.address(5020, 3), "41 Test St")
        w.addresses = Addresses([[5022, 12, "41", "Spring St"]])               # wrong street: keep the made-up one
        self.assertEqual(ms.address(5020, 3), made_up)


if __name__ == "__main__":
    unittest.main()
