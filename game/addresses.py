"""Real civic addresses (house number + street) from data/addresses.json, made by tools/fetch_addresses.py.

Source: Nova Scotia Civic Address File (Open Government Licence - Nova Scotia). Without the file, the game makes up
house numbers (MissionManager.address), so older maps and the sample map keep working.
"""
import json
import math
import os

CELL = 50.0


class Addresses:
    def __init__(self, points):
        """points: [[x, y, number, street], ...] in game metres."""
        self.count = len(points)
        self.grid = {}
        for x, y, num, street in points:
            self.grid.setdefault((int(x // CELL), int(y // CELL)), []).append((float(x), float(y), str(num), street))

    @classmethod
    def load(cls, path):
        """Addresses from a file, or None if it does not exist or cannot be read."""
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return cls(json.load(f)["points"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            print("addresses ignored (%s): %s" % (path, e))
            return None

    def near(self, x, y, street, radius=45.0):
        """'12A Victoria St E': the nearest real address on `street` within radius metres, or None."""
        best, best_d = None, radius
        k = int(radius // CELL) + 1
        cx, cy = int(x // CELL), int(y // CELL)
        for gx in range(cx - k, cx + k + 1):
            for gy in range(cy - k, cy + k + 1):
                for px, py, num, s in self.grid.get((gx, gy), ()):
                    if s != street:
                        continue
                    d = math.hypot(px - x, py - y)
                    if d < best_d:
                        best, best_d = "%s %s" % (num, s), d
        return best
