"""Offline tests for tools/fetch_osm.py (the network is mocked; nothing is downloaded).

Run from the project root:  python -m unittest discover -s tests -v
"""
import io
import json
import math
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import fetch_osm  # noqa: E402

# What Overpass returns: no <bounds> element
OVERPASS_REPLY = b"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="Overpass API">
  <note>The data included in this document is from www.openstreetmap.org.</note>
  <node id="1" lat="45.8100" lon="-64.2100"/>
  <node id="2" lat="45.8100" lon="-64.2050"/>
  <node id="3" lat="45.8110" lon="-64.2050"/>
  <node id="4" lat="45.8110" lon="-64.2100"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/><tag k="name" v="Victoria St"/></way>
  <way id="11"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/><tag k="building" v="yes"/></way>
</osm>
"""


class BboxTests(unittest.TestCase):
    def test_default_area_is_about_4km_square(self):
        s, w, n, e = fetch_osm.bbox_from_center(*fetch_osm.DEFAULT_CENTER, 2000)
        height_km = (n - s) * 111.2
        width_km = (e - w) * 111.2 * math.cos(math.radians(fetch_osm.DEFAULT_CENTER[0]))
        self.assertAlmostEqual(height_km, 4.0, delta=0.1)
        self.assertAlmostEqual(width_km, 4.0, delta=0.1)

    def test_bbox_is_centred(self):
        s, w, n, e = fetch_osm.bbox_from_center(45.8, -64.2, 1000)
        self.assertAlmostEqual((s + n) / 2, 45.8, places=6)
        self.assertAlmostEqual((w + e) / 2, -64.2, places=6)

    def test_default_centre_is_amherst(self):
        lat, lon = fetch_osm.DEFAULT_CENTER
        self.assertTrue(45.7 < lat < 45.9 and -64.4 < lon < -64.0)


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.q = fetch_osm.build_query((45.80, -64.25, 45.84, -64.18))

    def test_query_has_all_feature_types(self):
        for needle in ('way["highway"]', 'way["building"]', '"railway"="rail"',
                       '"natural"="water"', 'riverbank', 'reservoir'):
            self.assertIn(needle, self.q)

    def test_query_skips_footpaths_and_fetches_nodes(self):
        self.assertIn("footway", self.q)
        self.assertIn("(._;>;);", self.q)
        self.assertTrue(self.q.rstrip().endswith("out body;"))

    def test_query_contains_bbox_numbers(self):
        self.assertIn("45.800000,-64.250000,45.840000,-64.180000", self.q)


class BoundsTests(unittest.TestCase):
    def test_bounds_inserted_when_missing(self):
        out = fetch_osm.ensure_bounds(OVERPASS_REPLY, (45.80, -64.25, 45.84, -64.18))
        self.assertIn(b"<bounds", out)
        self.assertLess(out.index(b"<bounds"), out.index(b"<node"))

    def test_existing_bounds_untouched(self):
        with_bounds = OVERPASS_REPLY.replace(b"<note>", b'<bounds minlat="1" minlon="2" maxlat="3" maxlon="4"/><note>')
        self.assertEqual(fetch_osm.ensure_bounds(with_bounds, (0, 0, 1, 1)), with_bounds)

    def test_non_osm_rejected(self):
        with self.assertRaises(ValueError):
            fetch_osm.ensure_bounds(b"<html>nope</html>", (0, 0, 1, 1))

    def test_looks_like_osm(self):
        self.assertTrue(fetch_osm.looks_like_osm(OVERPASS_REPLY))
        self.assertFalse(fetch_osm.looks_like_osm(b"<html><body>429 Too Many Requests</body></html>"))
        self.assertFalse(fetch_osm.looks_like_osm(b'{"elements": []}'))


class DownloadTests(unittest.TestCase):
    def _fake_response(self, data):
        resp = mock.MagicMock()
        resp.read.return_value = data
        resp.__enter__.return_value = resp
        return resp

    def test_falls_back_to_second_server_after_error(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return self._fake_response(OVERPASS_REPLY)

        with mock.patch("fetch_osm.urllib.request.urlopen", fake_urlopen), redirect_stdout(io.StringIO()):
            data = fetch_osm.download("q", attempts=1)
        self.assertEqual(data, OVERPASS_REPLY)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])

    def test_rejects_html_error_page_and_gives_fallback_advice(self):
        html = b"<html><body>Server too busy</body></html>"
        with mock.patch("fetch_osm.urllib.request.urlopen", lambda req, timeout=None: self._fake_response(html)), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                fetch_osm.download("q", attempts=1)
        self.assertIn("overpass-turbo", str(ctx.exception))

    def test_network_failure_gives_fallback_advice(self):
        def boom(req, timeout=None):
            raise urllib.error.URLError("no route")
        with mock.patch("fetch_osm.urllib.request.urlopen", boom), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                fetch_osm.download("q", attempts=1)
        self.assertIn("Download failed", str(ctx.exception))


class EndToEndTests(unittest.TestCase):
    def test_download_save_and_convert(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sub", "town.osm")
            with mock.patch("fetch_osm.download", return_value=OVERPASS_REPLY), redirect_stdout(io.StringIO()):
                rc = fetch_osm.main(["--out", out, "--convert", "--no-nsrn", "--radius", "1500"])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out))
            map_path = os.path.join(tmp, "sub", "town_map.json")
            with open(map_path) as f:
                data = json.load(f)
            self.assertEqual(len(data["roads"]), 1)
            self.assertEqual(data["roads"][0]["name"], "Victoria St")

    def test_convert_applies_nsrn_streets_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "town.osm")
            with mock.patch("fetch_osm.download", return_value=OVERPASS_REPLY), redirect_stdout(io.StringIO()):
                fetch_osm.main(["--out", out, "--convert", "--radius", "1500"])
            with open(os.path.join(tmp, "town_map.json")) as f:
                data = json.load(f)
            self.assertEqual(data["meta"]["road_source"], "NSRN")
            self.assertGreater(len(data["roads"]), 5)          # the tiny test area still gets several real streets
            self.assertEqual(len(data["buildings"]), 1)
            # origin should be the centre of the requested box, not the mean of the nodes
            self.assertAlmostEqual(data["meta"]["origin_lat"], fetch_osm.DEFAULT_CENTER[0], places=4)
            self.assertAlmostEqual(data["meta"]["origin_lon"], fetch_osm.DEFAULT_CENTER[1], places=4)

    def test_print_query_makes_no_request(self):
        buf = io.StringIO()
        with mock.patch("fetch_osm.download", side_effect=AssertionError("must not download")), redirect_stdout(buf):
            self.assertEqual(fetch_osm.main(["--print-query"]), 0)
        self.assertIn("out body;", buf.getvalue())

    def test_too_large_area_refused(self):
        with self.assertRaises(SystemExit):
            fetch_osm.main(["--radius", "20000", "--print-query"])

    def test_invalid_bbox_refused(self):
        with self.assertRaises(SystemExit):
            fetch_osm.main(["--bbox", "46", "-64", "45", "-63", "--print-query"])


if __name__ == "__main__":
    unittest.main()
