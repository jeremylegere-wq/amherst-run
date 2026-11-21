#!/usr/bin/env python3
"""Golden files for the native C++ game's parity tests: what the Python game answers, for the C++ game to match.

    python tools/golden.py                 # -> dist/golden/*.csv (bake the map with tools/bake_native.py too)

heights.csv   x, y, z_hint, ground, height_at   surface heights on the real map: random points, plus points on and
              beside every overpass deck at the deck level and at the ground (so both levels are checked)

Fixed seed, so the files only change when the map or the game's rules change.
"""
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def height_samples(world, n=2000, seed=7):
    rng = random.Random(seed)
    x0, y0, x1, y1 = world.bounds
    rows = []
    for _ in range(n):
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        rows.append((x, y, 0.0))
    for sp in world.spans:                                  # on the decks: high and low hints, and just beside
        for k in range(0, len(sp["points"]), 3):
            x, y = sp["points"][k]
            g = world.ground(x, y)
            for dx in (0.0, sp["width"] / 2 + 1.0):
                rows.append((x + dx, y, g + sp["h"][k] + 1.0))
                rows.append((x + dx, y, g))
    return [(x, y, z, world.ground(x, y), world.height_at(x, y, z)) for x, y, z in rows]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "golden"))
    args = ap.parse_args(argv)
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from game.world import World
    world = World.load(args.map)
    os.makedirs(args.out, exist_ok=True)
    rows = height_samples(world)
    path = os.path.join(args.out, "heights.csv")
    with open(path, "w") as f:
        f.write("x,y,z_hint,ground,height_at\n")
        for r in rows:
            f.write("%.3f,%.3f,%.3f,%.4f,%.4f\n" % r)
    print("wrote %s: %d samples" % (path, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
