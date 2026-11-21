"""Terrain heights: a regular grid of ground heights (metres) with smooth (bilinear) lookups.

data/elevation.json is made by tools/fetch_elevation.py. With no file the world is flat (height 0 everywhere), so
every older map still works.

File format (heights either as "h", a list of ints, or "h16z": little-endian int16, zlib, base64):
    {"step": 25.0, "x0": -3000.0, "y0": -3000.0, "nx": 240, "ny": 220, "unit": 0.1,
     "h": [row-major ints, nx * ny, in `unit` metres, y rows from y0 southwards], ...}
"""
import base64
import json
import math
import os
import zlib
from array import array

VERTICAL_SCALE = 1.5      # arcade exaggeration: real Amherst is gentle, so hills are stretched a little


class Terrain:
    def __init__(self, x0, y0, step, nx, ny, heights, scale=VERTICAL_SCALE, count=None):
        count = len(heights) if count is None else count
        if count != nx * ny:
            raise ValueError("elevation grid has %d values, expected %d x %d" % (count, nx, ny))
        self.x0, self.y0, self.step, self.nx, self.ny = float(x0), float(y0), float(step), int(nx), int(ny)
        self.h = array("f", (float(v) * scale for v in heights))    # compact: a 12.5 m grid has ~1.7 million nodes
        self.scale = scale

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_dict(cls, d, scale=VERTICAL_SCALE):
        unit = float(d.get("unit", 0.1))
        if "h16z" in d:                                      # compressed int16 (tools/fetch_lidar_ground.py)
            import numpy as np                               # one vector step instead of 1.7 million Python ones
            raw = np.frombuffer(zlib.decompress(base64.b64decode(d["h16z"])), dtype="<i2")
            t = cls(d["x0"], d["y0"], d["step"], d["nx"], d["ny"], (), scale, count=len(raw))
            t.h = array("f")
            t.h.frombytes((raw.astype(np.float32) * np.float32(unit * scale)).astype("=f4").tobytes())
            return t
        return cls(d["x0"], d["y0"], d["step"], d["nx"], d["ny"], [v * unit for v in d["h"]], scale)

    @classmethod
    def load(cls, path, scale=VERTICAL_SCALE):
        """Terrain from a file, or None if it does not exist or cannot be read (the world is then flat). A LiDAR file
        (tools/fetch_lidar_ground.py) keeps its coarse source grid as .previous: game/world.py uses it under overpasses,
        where the LiDAR's bridge embankments would fight the game's own decks and ramps."""
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            t = cls.from_dict(d, scale)
            t.previous, t.previous_shift = None, 0.0
            if "previous" in d:                              # the coarse source grid, used under overpasses
                t.previous = cls.from_dict(d["previous"], scale)
                t.previous_shift = float(d.get("previous_shift", 0.0)) * scale
            return t
        except (OSError, ValueError, KeyError) as e:
            print("elevation ignored (%s): %s" % (path, e))
            return None

    # ------------------------------------------------------------------ queries
    def _node(self, i, j):
        i = 0 if i < 0 else self.nx - 1 if i >= self.nx else i
        j = 0 if j < 0 else self.ny - 1 if j >= self.ny else j
        return self.h[j * self.nx + i]

    def node(self, i, j):
        """Height of grid node (i, j), clamped to the grid."""
        return self._node(i, j)

    def height(self, x, y):
        """Ground height at (x, y); beyond the grid the nearest edge value is used (no cliffs)."""
        fx, fy = (x - self.x0) / self.step, (y - self.y0) / self.step
        i, j = math.floor(fx), math.floor(fy)
        tx, ty = fx - i, fy - j
        nx = self.nx
        if 0 <= i < nx - 1 and 0 <= j < self.ny - 1:            # fast path (called ~1000 times a frame)
            k = j * nx + i
            h = self.h
            a, b, c, d = h[k], h[k + 1], h[k + nx], h[k + nx + 1]
        else:
            a, b = self._node(i, j), self._node(i + 1, j)
            c, d = self._node(i, j + 1), self._node(i + 1, j + 1)
        top = a + (b - a) * tx
        return top + (c + (d - c) * tx - top) * ty

    def cell_normal(self, a, b, c, d, size=None):
        """Unit normal of a grid cell from its corner heights (a NW, b NE, c SW, d SE); same as normal() at its centre.
        size: the cell's width when it spans several grid steps (game/render3d.py draws coarse cells far away)."""
        s2 = 2.0 * (size or self.step)
        gx = ((b - a) + (d - c)) / s2
        gy = ((c - a) + (d - b)) / s2
        n = math.sqrt(gx * gx + gy * gy + 1.0)
        return -gx / n, -gy / n, 1.0 / n

    def normal(self, x, y, d=None):
        """Unit surface normal (nx, ny, nz) at (x, y)."""
        d = d or self.step * 0.5
        gx = (self.height(x + d, y) - self.height(x - d, y)) / (2 * d)
        gy = (self.height(x, y + d) - self.height(x, y - d)) / (2 * d)
        n = math.sqrt(gx * gx + gy * gy + 1.0)
        return -gx / n, -gy / n, 1.0 / n

    def slope(self, x, y):
        """Rise over run (0.05 = a 5% grade)."""
        n = self.normal(x, y)
        return math.sqrt(max(0.0, 1.0 - n[2] * n[2])) / max(1e-6, n[2])

    def blend_weights(self, points, radius, blend, weights):
        """Record, for nodes near a polyline, how much of this terrain to keep (0 within `radius`, rising to 1 over the
        next `blend` metres by smoothstep). weights: {node index: weight}, the lowest weight wins where lines overlap."""
        import numpy as np
        if len(points) < 2:
            return
        reach = radius + blend
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        i0 = max(0, int((min(xs) - reach - self.x0) / self.step))
        i1 = min(self.nx - 1, int((max(xs) + reach - self.x0) / self.step) + 1)
        j0 = max(0, int((min(ys) - reach - self.y0) / self.step))
        j1 = min(self.ny - 1, int((max(ys) + reach - self.y0) / self.step) + 1)
        if i1 < i0 or j1 < j0:
            return
        ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1))
        X, Y = self.x0 + ii * self.step, self.y0 + jj * self.step
        best = np.full(X.shape, reach)
        for a, b in zip(points, points[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = np.zeros(X.shape) if L2 == 0 else np.clip(((X - a[0]) * dx + (Y - a[1]) * dy) / L2, 0.0, 1.0)
            np.minimum(best, np.hypot(X - a[0] - t * dx, Y - a[1] - t * dy), out=best)
        near = best < reach
        u = np.clip((best - radius) / blend, 0.0, 1.0)
        w = u * u * (3.0 - 2.0 * u)
        for n, wv in zip((jj[near] * self.nx + ii[near]).tolist(), w[near].tolist()):
            if wv < weights.get(n, 1.0):
                weights[n] = wv

    def apply_blend(self, weights, other, offset=0.0):
        """Mix in `other` terrain (+ offset) by 1 - weight at each recorded node (see blend_weights)."""
        for n, w in weights.items():
            i, j = n % self.nx, n // self.nx
            o = other.height(self.x0 + i * self.step, self.y0 + j * self.step) + offset
            self.h[n] = o * (1.0 - w) + self.h[n] * w
        return len(weights)

    def bounds(self):
        return (self.x0, self.y0, self.x0 + (self.nx - 1) * self.step, self.y0 + (self.ny - 1) * self.step)

    def range(self):
        return min(self.h), max(self.h)
