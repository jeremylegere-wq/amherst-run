"""Real trees from the LiDAR survey (data/lidar_trees.json, made by tools/fetch_lidar_trees.py).

World streams them per prop cell like the woods (game/world.py _make_woods): where the survey covers the map these
trees replace both the random woods and the random street trees; elsewhere the random ones stay.
"""
import base64
import json
import os
import zlib

import numpy as np

NAME = "lidar_trees.json"
KEY = 1 << 20             # cell key = gx * KEY + gy (gx, gy shifted to be positive)
SHIFT = 1 << 19


def _unpack(text):
    return np.frombuffer(zlib.decompress(base64.b64decode(text)), dtype="<i2")


def load_beside(map_path):
    path = os.path.join(os.path.dirname(os.path.abspath(map_path)), NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class LidarTrees:
    """The tree tops, sorted by prop cell for quick per-cell lookups, and the survey's coverage."""

    def __init__(self, doc, cell):
        self.cell = cell
        x = _unpack(doc["x"]).astype(np.float32) * doc["unit_xy"]
        y = _unpack(doc["y"]).astype(np.float32) * doc["unit_xy"]
        h = _unpack(doc["h"]).astype(np.float32) * doc["unit_h"]
        gx = np.floor(x / cell).astype(np.int64) + SHIFT
        gy = np.floor(y / cell).astype(np.int64) + SHIFT
        key = gx * KEY + gy
        order = np.argsort(key, kind="stable")
        self.key, self.x, self.y, self.h = key[order], x[order], y[order], h[order]
        cv = doc["cover"]
        self.cx0, self.cy0, self.ccell = cv["x0"], cv["y0"], cv["cell"]
        self.cnx, self.cny = cv["nx"], cv["ny"]
        self.cover = np.frombuffer(zlib.decompress(base64.b64decode(cv["bits"])), dtype=np.uint8).reshape(self.cny, self.cnx)

    def __len__(self):
        return len(self.x)

    def covered(self, x, y):
        """True where the survey has data (so real trees are planted there, not random ones)."""
        i, j = int((x - self.cx0) // self.ccell), int((y - self.cy0) // self.ccell)
        return 0 <= i < self.cnx and 0 <= j < self.cny and bool(self.cover[j, i])

    def in_cell(self, gx, gy):
        """[(x, y, h)] of the tree tops in prop cell (gx, gy), tallest first."""
        k = (gx + SHIFT) * KEY + (gy + SHIFT)
        a, b = np.searchsorted(self.key, [k, k + 1])
        if a == b:
            return []
        idx = np.argsort(-self.h[a:b]) + a
        return list(zip(self.x[idx].tolist(), self.y[idx].tolist(), self.h[idx].tolist()))
