#!/usr/bin/env python3
"""Drive a probe car along every road (in its right-hand lane) and report where the road does not work:

  blocked   something solid stops the car (a building, a pole, a tree, the map edge)
  step      the surface jumps more than STEP_MAX metres between two samples 2 m apart (a cliff, not a slope)
  steep     a grade steeper than STEEP over 10 m (a wall to drive up)

    python tools/road_check.py              # the whole map
    python tools/road_check.py --near X Y   # only roads within 400 m of a point
"""
import argparse
import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game.car import Car  # noqa: E402
from game.collision import car_hits_world  # noqa: E402
from game.world import World  # noqa: E402

STEP = 2.0
STEP_MAX = 0.8
STEEP = 0.25
SKIP = ("driveway", "track")


def _blocker(world, car):
    """What stops the car: a building, the map edge, or the kind of prop."""
    from game.collision import _sample_points
    if any(world.in_building(x, y) for x, y in _sample_points(car, True)):
        return "building"
    if not world.in_bounds(car.x, car.y, 0.0):
        return "edge"
    near = [p for p in world.props_near(car.x, car.y, 4.0) if p.get("cr", 0) > 0]
    near.sort(key=lambda p: math.hypot(p["x"] - car.x, p["y"] - car.y))
    return near[0]["kind"] if near else "?"


def check(world, near=None, radius=400.0):
    problems = []
    for r in world.roads:
        if r.get("service") in SKIP:
            continue
        pts = r["points"]
        if near and min(math.dist(p, near) for p in pts) > radius:
            continue
        lifted = lambda p: world.height_at(p[0], p[1], 999.0) - world.ground(p[0], p[1])   # noqa: E731
        if not r.get("lift") and lifted(pts[0]) > lifted(pts[-1]):
            pts = pts[::-1]                    # start a ramp road from its ground end, as a car would arrive
        lane = 0.0                         # the centre line: a lane offset jumps sideways at every bend
        z = None
        prev = None
        hist = []
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 0.5:
                continue
            dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            n = max(1, int(L / STEP))
            for k in range(n):
                x = a[0] + dx * L * k / n - dy * lane
                y = a[1] + dy * L * k / n + dx * lane
                h = world.height_at(x, y, z if z is not None else (world.ground(x, y) + (r.get("lift") or 0) * 2))
                car = Car(x, y, math.atan2(dy, dx))
                car.z = h
                if world.in_bounds(x, y, 30.0) and car_hits_world(car, world):
                    problems.append(("blocked:" + _blocker(world, car), r["name"] or "-", r["type"], round(x), round(y)))
                if z is not None and abs(h - z) > STEP_MAX and prev is not None and math.dist(prev, (x, y)) < STEP * 1.6:
                    problems.append(("step %.1f m" % (h - z), r["name"] or "-", r["type"], round(x), round(y)))
                hist.append(h)
                if len(hist) > 5:
                    g = abs(hist[-1] - hist[-6]) / (5 * STEP)
                    if g > STEEP:
                        problems.append(("steep %.0f%%" % (g * 100), r["name"] or "-", r["type"], round(x), round(y)))
                z = h
                prev = (x, y)
    out, seen = [], []
    for p in problems:
        if all(math.dist(p[3:], s) > 25 for s in seen):
            seen.append(p[3:])
            out.append(p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--near", nargs=2, type=float)
    args = ap.parse_args(argv)
    world = World.load(args.map)
    world.warm_woods(*(args.near or world.spawn()[:2]), 50.0)
    probs = check(world, tuple(args.near) if args.near else None)
    kinds = {}
    for p in probs:
        kinds[p[0].split()[0]] = kinds.get(p[0].split()[0], 0) + 1
    print("%d problems: %s" % (len(probs), kinds))
    for p in probs[:60]:
        print("  %-14s %-28s %-5s (%d, %d)" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
