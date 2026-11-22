"""tools/bake_native.py: the map file for the native C++ game."""
import json
import math
import os
import struct
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import bake_native as B  # noqa: E402

from game.terrain import Terrain  # noqa: E402
from game.world import World  # noqa: E402


def _tri_area(pts, tris):
    return sum(abs((pts[j][0] - pts[i][0]) * (pts[k][1] - pts[i][1]) - (pts[k][0] - pts[i][0]) * (pts[j][1] - pts[i][1]))
               / 2 for i, j, k in tris)


class Triangulate(unittest.TestCase):
    def test_l_shape_is_covered_exactly(self):
        pts = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]      # area 64, one reflex corner
        tris = B.triangulate(pts)
        self.assertEqual(len(tris), 4)
        self.assertAlmostEqual(_tri_area(pts, tris), 64.0)

    def test_clockwise_outline_gives_counter_clockwise_triangles(self):
        pts = [(0, 0), (0, 5), (5, 5), (5, 0)]
        for i, j, k in B.triangulate(pts):
            a, b, c = pts[i], pts[j], pts[k]
            self.assertGreater((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]), 0)

    def test_closing_point_is_dropped(self):
        self.assertEqual(B._clean([[0, 0], [1, 0], [1, 1], [0, 0]]), [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])


class Props(unittest.TestCase):
    def test_props_are_written_with_their_kinds(self):
        w = Bake().world()
        w._prop_grid[(0, 0)].append({"kind": "tree", "x": 5.0, "y": 6.0, "h": 7.25, "r": 2.5, "cr": 0.4, "c": 2})
        w._prop_grid[(1, 0)].append({"kind": "fence", "x": 40.0, "y": 1.0, "x2": 50.0, "y2": 1.0, "h": 1.1, "r": 0,
                                     "cr": 0})
        payload, n = B._props_payload(w)
        self.assertEqual(n, 2)
        (nk,) = struct.unpack_from("<I", payload)
        self.assertEqual(nk, 2)                               # fence, tree (sorted)
        off = 4 + sum(4 + len(k) for k in ("fence", "tree")) + 4
        kind, c, r, g, b, flags, x, y, h, rad, cr, head = struct.unpack_from("<2B3BB2f3Hh", payload, off)
        self.assertEqual((kind, c, x, y, h, rad, cr), (1, 2, 5.0, 6.0, 725, 250, 40))


class Bake(unittest.TestCase):
    def world(self):
        roads = [{"type": "main", "width": 9, "name": "Main St", "points": [[-200, 0], [-25, 0]]},
                 {"type": "main", "width": 9, "name": "Main St", "points": [[-25, 0], [25, 0]], "bridge": True,
                  "lift": 5.2},
                 {"type": "main", "width": 9, "name": "Main St", "points": [[25, 0], [200, 0]]},
                 {"type": "side", "width": 7, "name": "Low Rd", "points": [[0, -200], [0, 200]], "oneway": 1}]
        data = {"meta": {"bounds": [-250, -250, 250, 250], "procedural_props": False, "spawn": [10, -50, 1.0]},
                "roads": json.loads(json.dumps(roads)),
                "buildings": [{"points": [[50, 50], [70, 50], [70, 62], [50, 62]], "height": 7.5, "roof": "gable",
                               "roof_height": 2.0, "colour": [10, 20, 30], "tags": {}}],
                "water": [{"points": [[-100, 100], [-60, 100], [-60, 140]]}]}
        n = 41
        t = Terrain(-250, -250, 12.5, n, n, [10.0 + 0.01 * i for i in range(n * n)], scale=1.0)
        return World(data, terrain=t)

    def test_round_trip(self):
        w = self.world()
        data, info = B.bake(w, source="test")
        ch = B.read_chunks(data)
        self.assertEqual(ch["_version"], B.VERSION)
        x0, y0, x1, y1, sx, sy, sh = struct.unpack_from("<4f3f", ch["META"])
        self.assertEqual((x0, y1, sx, sy), (-250, 250, 10, -50))
        self.assertAlmostEqual(sh, 1.0, places=6)
        # terrain: heights come back to within half a step
        tx0, ty0, step, nx, ny, base, unit = struct.unpack_from("<3f2I2f", ch["TERR"])
        self.assertEqual((nx, ny, step), (41, 41, 12.5))
        q = struct.unpack_from("<%dH" % (nx * ny), ch["TERR"], struct.calcsize("<3f2I2f"))
        for i in (0, 500, nx * ny - 1):
            self.assertLess(abs(base + unit * q[i] - w.terrain.h[i]), unit)
        # roads: count, the deck flag on the lifted piece, one-way, names
        (nroads,) = struct.unpack_from("<I", ch["ROAD"])
        self.assertEqual(nroads, 4)
        off, flags = 4, []
        for _ in range(nroads):
            t, svc, fl, lanes, width, speed, name, npts = struct.unpack_from("<4B2f2I", ch["ROAD"], off)
            flags.append(fl)
            off += struct.calcsize("<4B2f2I") + 8 * npts
        self.assertEqual(off, len(ch["ROAD"]))
        self.assertTrue(flags[1] & 4 and flags[1] & 2)        # the bridge is a deck
        self.assertTrue(flags[3] & 1)                          # one-way
        (nspans,) = struct.unpack_from("<I", ch["SPAN"])
        self.assertEqual(nspans, 1)
        self.assertEqual(info["buildings"], 1)
        bh, rh, roof, bflags = struct.unpack_from("<2f2B", ch["BLDG"], 4)
        self.assertEqual((bh, rh, roof), (7.5, 2.0, 1))
        self.assertEqual(struct.unpack_from("<3B", ch["BLDG"], 4 + 10), (10, 20, 30))
        self.assertEqual(info["polygons"], 1)
        (nkinds,) = struct.unpack_from("<I", ch["PROP"])
        self.assertEqual(nkinds, 0)                            # this little world has no props
        self.assertEqual(B.bake(self.world(), source="test")[0], data)   # the same map bakes to the same bytes

    def test_house_details_face_the_street(self):
        w = self.world()
        w.buildings.append({"points": [[20, 12], [30, 12], [30, 20], [20, 20]], "height": 6.8, "roof": "gable",
                            "roof_height": 2.5, "tags": {"building": "house"}, "chimney": 0.5})
        ch = B.read_chunks(B.bake(w, source="test")[0])
        (n,) = struct.unpack_from("<I", ch["BDET"])
        self.assertEqual(n, 2)                                # one entry per BLDG building, in the same order
        size = struct.calcsize("<6B2hf12B3fb2B")
        kind, storeys, flags, steeple, lm, dormers, front, wrap, door = struct.unpack_from("<6B2hf", ch["BDET"], 4 + size)
        self.assertEqual((kind, storeys, lm), (5, 2, 0))      # a two-storey house, not a landmark
        self.assertEqual(front, 0)                            # wall 0 runs along y = 12, facing Main St (y = 0)
        self.assertTrue(0.3 <= door <= 0.7)
        (chimney,) = struct.unpack_from("<f", ch["BDET"], 4 + size + struct.calcsize("<6B2hf12B2f"))
        self.assertEqual(chimney, 0.5)

    def test_unknown_file_is_refused(self):
        with self.assertRaises(ValueError):
            B.read_chunks(b"NOPE" + bytes(8))


if __name__ == "__main__":
    unittest.main()
