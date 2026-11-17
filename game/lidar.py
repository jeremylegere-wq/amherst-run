"""Real building heights and roof shapes measured from LiDAR (data/building_heights.json, tools/fetch_heights.py).

Applied by World.load to the converted map BEFORE the hand edits (the keys are the original footprint centres), so:
    hand edits (map_edits.json)  >  LiDAR  >  zoning / converter estimates.
Buildings it sets are marked "lidar": True, and the zoning pass still gives them their district's colours and
materials, just not a made-up height or roof (game/zoning.py). Without the file nothing changes.
"""
import json
import os

HEIGHTS_NAME = "building_heights.json"
MEASURED = ("height", "roof", "roof_height", "ridge_across")   # the fields LiDAR owns
TOLERANCE = 3.0
CELL = 20.0


def load_beside(map_path):
    path = os.path.join(os.path.dirname(os.path.abspath(map_path)), HEIGHTS_NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("building heights ignored (%s): %s" % (path, e))
        return None


def apply(data, doc):
    """Set height / roof / roof_height / ridge_across on the buildings the file measured. Returns a report line."""
    if not doc:
        return None
    grid = {}
    for row in doc.get("buildings", []):
        grid.setdefault((int(row[0] // CELL), int(row[1] // CELL)), []).append(row)
    n = 0
    for b in data["buildings"]:
        pts = b["points"]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        gx, gy = int(cx // CELL), int(cy // CELL)
        best, best_d = None, TOLERANCE
        for i in (gx - 1, gx, gx + 1):
            for j in (gy - 1, gy, gy + 1):
                for row in grid.get((i, j), ()):
                    d = abs(row[0] - cx) + abs(row[1] - cy)
                    if d < best_d:
                        best, best_d = row, d
        if best is None:
            continue
        for k in MEASURED:
            b.pop(k, None)
        b["height"] = float(best[2])
        if best[3] in ("gable", "hip") and best[4] > 0 and len(pts) == 4:
            b["roof"] = best[3]
            b["roof_height"] = float(best[4])
            if len(best) > 5 and best[5]:
                b["ridge_across"] = True
        b["lidar"] = True
        n += 1
    return "building heights (LiDAR): %d of %d buildings" % (n, len(data["buildings"]))
