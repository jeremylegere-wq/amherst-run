"""Tests for LiDAR building heights: tools/cog.py (TIFF reading), tools/fetch_heights.py (roof fitting) and
game/lidar.py (applying the results). Everything is synthetic; nothing is downloaded.

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cog  # noqa: E402
import fetch_heights as FH  # noqa: E402
from game import lidar, mapedits, zoning  # noqa: E402
from game.builder import roof_faces  # noqa: E402


def lzw_encode(data):
    """TIFF LZW encoder (MSB-first, early change) - only to test the decoder."""
    out, acc, nacc = bytearray(), 0, 0

    def put(code, width):
        nonlocal acc, nacc
        acc = (acc << width) | code
        nacc += width
        while nacc >= 8:
            nacc -= 8
            out.append((acc >> nacc) & 0xFF)

    table = {bytes([i]): i for i in range(256)}
    nxt, width = 258, 9
    put(256, width)
    w = b""
    for c in data:
        wc = w + bytes([c])
        if wc in table:
            w = wc
            continue
        put(table[w], width)
        table[wc] = nxt
        nxt += 1
        # TIFF "early change": the decoder (one table entry behind the encoder) widens at 511 entries, which is
        # when the encoder's next free code reaches 512.
        if nxt >= (1 << width) and width < 12:
            width += 1
        if nxt >= 4094:
            put(256, width)
            table = {bytes([i]): i for i in range(256)}
            nxt, width = 258, 9
        w = bytes([c])
    if w:
        put(table[w], width)
    put(257, width)
    if nacc:
        out.append((acc << (8 - nacc)) & 0xFF)
    return bytes(out)


def tiny_tiff(tiles, tw=4, th=4, across=2, down=1, x0=1000.0, y0=2000.0, nodata=-32767.0, lzw=True):
    """A classic little-endian tiled float32 GeoTIFF in memory: tiles = list of (th x tw) arrays, row-major."""
    blobs = []
    for t in tiles:
        raw = np.asarray(t, dtype="<f4").tobytes()
        blobs.append(lzw_encode(raw) if lzw else raw)
    nodata_s = (repr(nodata) + "\0").encode()
    entries = [(256, 4, 1, tw * across), (257, 4, 1, th * down), (258, 3, 1, 32), (259, 3, 1, 5 if lzw else 1),
               (277, 3, 1, 1), (322, 4, 1, tw), (323, 4, 1, th), (324, 4, len(tiles), None), (325, 4, len(tiles), None),
               (339, 3, 1, 3), (33550, 12, 3, None), (33922, 12, 6, None), (42113, 2, len(nodata_s), None)]
    n = len(entries)
    ifd_at = 8
    extra_at = ifd_at + 2 + n * 12 + 4
    extra = bytearray()
    payload = {}

    def put_extra(b):
        at = extra_at + len(extra)
        extra.extend(b)
        return at

    data_at = extra_at + 4096
    offs, cnts, at = [], [], data_at
    for b in blobs:
        offs.append(at)
        cnts.append(len(b))
        at += len(b)
    payload[324] = put_extra(struct.pack("<%dI" % len(offs), *offs))
    payload[325] = put_extra(struct.pack("<%dI" % len(cnts), *cnts))
    payload[33550] = put_extra(struct.pack("<3d", 1.0, 1.0, 0.0))
    payload[33922] = put_extra(struct.pack("<6d", 0, 0, 0, x0, y0, 0))
    payload[42113] = put_extra(nodata_s)
    ifd = bytearray(struct.pack("<H", n))
    for tag, typ, cnt, val in entries:
        if val is None:
            ifd += struct.pack("<HHII", tag, typ, cnt, payload[tag])
        elif typ == 3:
            ifd += struct.pack("<HHIHH", tag, typ, cnt, val, 0)
        else:
            ifd += struct.pack("<HHII", tag, typ, cnt, val)
    ifd += struct.pack("<I", 0)
    head = b"II" + struct.pack("<HI", 42, ifd_at)
    body = head + ifd + extra
    body += b"\0" * (data_at - len(body))
    return body + b"".join(blobs)


class DecoderTests(unittest.TestCase):
    def test_lzw_round_trip(self):
        rng = np.random.default_rng(1)
        for data in (b"", b"A", b"TOBEORNOTTOBEORTOBEORNOT" * 50, rng.integers(0, 256, 30000, dtype=np.uint8).tobytes(),
                     np.linspace(20, 30, 4096, dtype="<f4").tobytes()):
            self.assertEqual(cog.lzw_decode(lzw_encode(data)), data)

    def test_projection_properties(self):
        x, y = cog.lcc3979(np.array([49.0]), np.array([-95.0]))
        self.assertAlmostEqual(float(x[0]), 0.0, places=3)                 # the projection origin
        self.assertAlmostEqual(float(y[0]), 0.0, places=3)
        a = cog.lcc3979(np.array([49.0, 49.0]), np.array([-90.0, -90.0 + 1000 / (111320 * math.cos(math.radians(49)))]))
        self.assertAlmostEqual(math.hypot(a[0][1] - a[0][0], a[1][1] - a[1][0]), 1000.0, delta=3.0)  # scale ~1 on 49N
        n = cog.lcc3979(np.array([45.83, 45.84]), np.array([-64.2, -64.2]))
        self.assertGreater(n[1][1], n[1][0])                                # further north = larger y
        self.assertGreater(float(n[0][0]), 2.0e6)                          # Amherst is ~2,300 km east of 95W

    def test_reads_tiles_and_samples(self):
        t0 = np.arange(16, dtype="f4").reshape(4, 4)
        t1 = np.full((4, 4), 7.5, dtype="f4")
        t1[0, 0] = -32767.0                                                 # nodata
        blob = tiny_tiff([t0, t1])

        def fetch(url, start, end):
            return blob[start:end + 1]
        for use_cache in (False, True):
            with tempfile.TemporaryDirectory() as d:
                g = cog.COG("mem://x", fetch=fetch, cache_dir=d if use_cache else None)
                self.assertEqual((g.width, g.height, g.tw, g.across), (8, 4, 4, 2))
                if use_cache:
                    g.download(0, 0)
                    cog.decode_file(g._cache_path(0, 0, "raw"), g._cache_path(0, 0, "npy"), g.decode_spec())
                    self.assertTrue(g.cached(0, 0))
                # pixel (col 1, row 2) of tile 0 = 9; tile 1 col 0 row 0 is nodata; col 6 row 3 = 7.5
                v = g.sample(np.array([1000.0 + 1.5, 1000.0 + 4.5, 1000.0 + 6.5]), np.array([2000.0 - 2.5, 2000.0 - 0.5, 2000.0 - 3.5]))
                self.assertEqual(float(v[0]), 9.0)
                self.assertTrue(math.isnan(float(v[1])))
                self.assertEqual(float(v[2]), 7.5)

    def test_rejects_a_misread_index(self):
        blob = bytearray(tiny_tiff([np.zeros((4, 4), "f4"), np.zeros((4, 4), "f4")]))
        g = cog.COG("mem://x", fetch=lambda u, s, e: bytes(blob[s:e + 1]))
        g._entries[0] = ((100, 200), (10 ** 12, 10 ** 12))
        with self.assertRaises(ValueError):
            g.tile(0, 0)


def roof_points(poly, roof, wall, rh, across=False, step=0.5, hip=False):
    """Synthetic heights above ground for a roof over a 4-cornered footprint."""
    gx, gy = FH.grid_points(poly, step)
    (cx, cy), (ux, uy), hl, hw = FH.frame(poly)
    if across:
        ux, uy, hl, hw = -uy, ux, hw, hl
    u = (gx - cx) * ux + (gy - cy) * uy
    v = -(gx - cx) * uy + (gy - cy) * ux
    if roof == "flat":
        z = np.full(gx.shape, wall)
    else:
        z = wall + rh * (1 - np.clip(np.abs(v) / hw, 0, 1))
        if hip:
            z -= rh * np.clip((np.abs(u) - max(0, hl - hw)) / hw, 0, 1)
            z = np.maximum(z, wall)
    return gx, gy, z


class RoofFitTests(unittest.TestCase):
    HOUSE = [[0, 0], [12, 0], [12, 8], [0, 8]]                             # 12 m along x, 8 m deep

    def test_gable_along_the_long_side(self):
        gx, gy, z = roof_points(self.HOUSE, "gable", 5.0, 3.0)
        h, kind, rh, across = FH.fit_roof(gx, gy, z, self.HOUSE)
        self.assertEqual((kind, across), ("gable", False))
        self.assertAlmostEqual(h, 5.0, delta=0.3)
        self.assertAlmostEqual(rh, 3.0, delta=0.3)

    def test_cross_gable(self):
        gx, gy, z = roof_points(self.HOUSE, "gable", 4.5, 3.5, across=True)
        h, kind, rh, across = FH.fit_roof(gx, gy, z, self.HOUSE)
        self.assertEqual((kind, across), ("gable", True))
        self.assertAlmostEqual(h + rh, 8.0, delta=0.4)

    def test_hip(self):
        gx, gy, z = roof_points([[0, 0], [16, 0], [16, 8], [0, 8]], "gable", 5.0, 3.0, hip=True)
        self.assertEqual(FH.fit_roof(gx, gy, z, [[0, 0], [16, 0], [16, 8], [0, 8]])[1], "hip")

    def test_flat_and_noise(self):
        gx, gy, z = roof_points(self.HOUSE, "flat", 9.0, 0.0)
        z = z + np.random.default_rng(2).normal(0, 0.15, z.shape)
        h, kind, rh, _ = FH.fit_roof(gx, gy, z, self.HOUSE)
        self.assertEqual(kind, "flat")
        self.assertAlmostEqual(h, 9.0, delta=0.4)

    def test_a_chimney_does_not_spoil_the_fit(self):
        gx, gy, z = roof_points(self.HOUSE, "gable", 5.0, 3.0)
        z[(np.abs(gx - 4) < 0.6) & (np.abs(gy - 4) < 0.6)] += 1.5
        h, kind, rh, _ = FH.fit_roof(gx, gy, z, self.HOUSE)
        self.assertEqual(kind, "gable")
        self.assertAlmostEqual(h + rh, 8.0, delta=0.4)


class ApplyTests(unittest.TestCase):
    def data(self):
        return {"meta": {}, "roads": [], "buildings": [
            {"points": [[0, 0], [12, 0], [12, 8], [0, 8]], "tags": {"building": "house"}},
            {"points": [[50, 0], [62, 0], [62, 8], [50, 8]], "tags": {"building": "house"}, "height": 3.0},
            {"points": [[100, 0], [110, 0], [110, 10], [105, 12], [100, 10]], "tags": {}},
            {"points": [[200, 0], [210, 0], [210, 10], [200, 10]], "tags": {}}]}

    DOC = {"buildings": [[6, 4, 5.2, "gable", 2.8, 1], [56, 4, 7.0, "hip", 2.0], [105.0, 6.4, 11.0, "gable", 3.0]]}

    def test_measured_fields_are_set_and_marked(self):
        d = self.data()
        self.assertIn("3 of 4", lidar.apply(d, self.DOC))
        a, b, c, e = d["buildings"]
        self.assertEqual((a["height"], a["roof"], a["roof_height"], a.get("ridge_across")), (5.2, "gable", 2.8, True))
        self.assertEqual((b["height"], b["roof"]), (7.0, "hip"))           # LiDAR beats the converter's estimate
        self.assertEqual(c["height"], 11.0)
        self.assertNotIn("roof", c)                                       # roofs only on 4-cornered footprints
        self.assertNotIn("lidar", e)

    def test_zoning_still_colours_measured_buildings_but_keeps_their_shape(self):
        d = self.data()
        lidar.apply(d, self.DOC)
        self.assertTrue(zoning.plain(d["buildings"][0]))

        class AllResidential:
            def zone_at(self, x, y):
                return "R"
        zoning.apply(d, AllResidential())
        a = d["buildings"][0]
        self.assertEqual((a["height"], a["roof"], a["roof_height"]), (5.2, "gable", 2.8))
        self.assertEqual(a.get("zone"), "R")

    def test_hand_edits_beat_lidar(self):
        d = self.data()
        lidar.apply(d, self.DOC)
        mapedits.apply(d, {"buildings": {"replace": [{"at": [6, 4], "height": 4.4, "roof": "gable", "roof_height": 3.6}]}})
        a = d["buildings"][0]
        self.assertEqual((a["height"], a["roof_height"]), (4.4, 3.6))
        self.assertNotIn("ridge_across", a)                               # the hand-set roof replaces the measured one

    def test_no_file_changes_nothing(self):
        d = self.data()
        self.assertIsNone(lidar.apply(d, None))
        self.assertNotIn("height", d["buildings"][0])

    def test_cross_ridge_roof_faces(self):
        along = roof_faces([[0, 0], [12, 0], [12, 8], [0, 8]], 5.0, "gable", 3.0)
        across = roof_faces([[0, 0], [12, 0], [12, 8], [0, 8]], 5.0, "gable", 3.0, across=True)
        ridge = lambda faces: sorted({(round(p[0], 3), round(p[1], 3)) for f in faces for p in f if p[2] > 7.9})
        self.assertEqual(ridge(along), [(0.0, 4.0), (12.0, 4.0)])        # ridge along x (the long side)
        self.assertEqual(ridge(across), [(6.0, 0.0), (6.0, 8.0)])        # ridge along y (across)


if __name__ == "__main__":
    unittest.main()


def with_overview(full, ov_tile, tw=4, th=4, ov_w=4, ov_h=2):
    """`full` (a tiny_tiff) plus a second image directory: a 1-tile overview of ov_w x ov_h pixels (no geo tags)."""
    full = bytearray(full)
    n0 = struct.unpack("<H", full[8:10])[0]
    next_at = 8 + 2 + n0 * 12                                     # where IFD 0 stores the offset of the next IFD
    blob = np.asarray(ov_tile, dtype="<f4").tobytes()
    blob_at = len(full)
    full += blob
    entries = [(256, 4, 1, ov_w), (257, 4, 1, ov_h), (258, 3, 1, 32), (259, 3, 1, 1), (277, 3, 1, 1),
               (322, 4, 1, tw), (323, 4, 1, th), (324, 4, 1, blob_at), (325, 4, 1, len(blob)), (339, 3, 1, 3)]
    ifd_at = len(full)
    ifd = bytearray(struct.pack("<H", len(entries)))
    for tag, typ, cnt, val in entries:
        ifd += struct.pack("<HHIHH", tag, typ, cnt, val, 0) if typ == 3 else struct.pack("<HHII", tag, typ, cnt, val)
    ifd += struct.pack("<I", 0)
    full += ifd
    full[next_at:next_at + 4] = struct.pack("<I", ifd_at)
    return bytes(full)


class OverviewTests(unittest.TestCase):
    def test_level_one_reads_the_half_size_image_in_the_same_place(self):
        full = tiny_tiff([np.full((4, 4), 10.0), np.full((4, 4), 20.0)], lzw=False)
        ov = np.zeros((4, 4))
        ov[:2, :2], ov[:2, 2:] = 11.0, 19.0                             # left half, right half of the area
        data = with_overview(full, ov)
        fetch = lambda url, a, b: data[a:b + 1]                        # noqa: E731
        base = cog.COG("mem", fetch=fetch)
        lvl = cog.COG("mem", fetch=fetch, level=1)
        self.assertEqual((lvl.width, lvl.height), (4, 2))
        self.assertAlmostEqual(lvl.sx, base.sx * 2)
        self.assertEqual((lvl.x0, lvl.y0), (base.x0, base.y0))
        x = np.array([base.x0 + 1.0, base.x0 + 6.0])
        y = np.array([base.y0 - 1.0, base.y0 - 1.0])
        self.assertEqual(list(base.sample(x, y)), [10.0, 20.0])
        self.assertEqual(list(lvl.sample(x, y)), [11.0, 19.0])
        with self.assertRaises(ValueError):
            cog.COG("mem", fetch=fetch, level=2)


class LidarGroundTests(unittest.TestCase):
    def test_compressed_heights_round_trip_through_the_game(self):
        import fetch_lidar_ground as FLG
        from game.terrain import Terrain
        h = np.array([0.0, 12.3, -4.5, 171.2, 33.3, 7.7])
        t = Terrain.from_dict({"x0": 0, "y0": 0, "step": 12.5, "nx": 3, "ny": 2, "unit": 0.1,
                               "h16z": FLG.encode(h)}, scale=1.0)
        self.assertEqual([round(v, 1) for v in t.h], [round(v, 1) for v in h])
        self.assertAlmostEqual(t.height(12.5, 0.0), 12.3, places=4)


class LidarTreeTests(unittest.TestCase):
    def doc(self, xs, ys, hs, covered=True):
        import fetch_lidar_trees as FLT
        import base64
        import zlib
        cover = np.ones((4, 4), dtype=np.uint8) if covered else np.zeros((4, 4), dtype=np.uint8)
        return {"unit_xy": FLT.UNIT_XY, "unit_h": FLT.UNIT_H, "count": len(xs),
                "x": FLT.pack(np.round(np.array(xs) / FLT.UNIT_XY)), "y": FLT.pack(np.round(np.array(ys) / FLT.UNIT_XY)),
                "h": FLT.pack(np.round(np.array(hs) / FLT.UNIT_H)),
                "cover": {"x0": -320.0, "y0": -320.0, "cell": 160.0, "nx": 4, "ny": 4,
                          "bits": base64.b64encode(zlib.compress(cover.tobytes())).decode()}}

    def test_tops_are_peaks_not_roof_ridges(self):
        import fetch_lidar_trees as FLT
        chm = np.zeros((9, 9))
        chm[2, 2], chm[1:4, 1:4] = 0.0, chm[1:4, 1:4]
        yy, xx = np.mgrid[0:9, 0:9]
        chm += np.clip(9.0 - 3.0 * np.hypot(yy - 2, xx - 2), 0, None)   # a crown peaking at (2, 2)
        chm[6, 1:8] = 7.0                                                  # a level roof ridge along row 6
        chm[5, 1:8] = chm[7, 1:8] = 5.0
        r, k = FLT.tops(chm)
        self.assertEqual(list(zip(r.tolist(), k.tolist())), [(2, 2)])

    def test_cells_lookup_and_coverage(self):
        from game.lidar_trees import LidarTrees
        t = LidarTrees(self.doc([5.0, 45.0, 12.0], [5.0, 5.0, 30.0], [10.0, 20.0, 6.0]), 40.0)
        self.assertEqual(len(t), 3)
        cell = t.in_cell(0, 0)
        self.assertEqual([round(h) for _x, _y, h in cell], [10, 6])          # tallest first, only this cell
        self.assertTrue(t.covered(0.0, 0.0))
        self.assertFalse(t.covered(5000.0, 0.0))
        self.assertFalse(LidarTrees(self.doc([5.0], [5.0], [9.0], covered=False), 40.0).covered(0.0, 0.0))

    def test_real_trees_replace_random_ones_and_keep_off_roads_and_houses(self):
        import make_sample_map
        from game.world import World
        data = make_sample_map.build()
        data["roads"] = [{"type": "side", "width": 8, "name": "Elm St", "points": [[-300, 0], [300, 0]]}]
        data["buildings"] = [{"points": [[20, 20], [30, 20], [30, 30], [20, 30]], "tags": {"building": "house"}}]
        data["woods"] = []
        data["props"] = []                                                 # no mapped trees (the sample has a ring of them)
        data["lidar_trees"] = self.doc([5.0, 25.0, 50.0, 70.0], [1.0, 25.0, 60.0, 90.0], [8.0, 9.0, 15.0, 30.0])
        w = World(data)
        w.warm_woods(40.0, 50.0, 120.0)
        trees = [(p["x"], p["y"], p["h"]) for p in w.props_near(40.0, 50.0, 120.0) if p["kind"] == "tree"]
        spots = {(round(x), round(y)) for x, y, _h in trees}
        self.assertIn((50, 60), spots)                                     # a real tree in the yard
        self.assertNotIn((5, 1), spots)                                    # on the road
        self.assertNotIn((25, 25), spots)                                  # on the house
        tall = [h for x, y, h in trees if (round(x), round(y)) == (70, 90)]
        self.assertTrue(tall and tall[0] <= 24.0)                          # capped
        self.assertFalse([1 for x, y, h in trees if (round(x), round(y)) not in {(50, 60), (70, 90)}])   # no random ones
