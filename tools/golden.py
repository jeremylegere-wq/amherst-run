#!/usr/bin/env python3
"""Golden files for the native C++ game's parity tests: what the Python game answers, for the C++ game to match.

    python tools/golden.py                 # -> dist/golden/*.csv (bake the map with tools/bake_native.py too)

heights.csv   x, y, z_hint, ground, height_at   surface heights on the real map: random points, plus points on and
              beside every overpass deck at the deck level and at the ground (so both levels are checked)
drive.csv     run, step, throttle, brake, steer, handbrake, bumper, x, y, z, heading, vx, vy
              scripted drives with player 1's car (game/car.py physics, game/collision.py move_and_slide and
              settle_height, exactly as game/main.py steps the player at 60 Hz). Step 0 is the start; each later row
              holds the inputs of that step and the state after it. Trees, poles and other props are left out (the
              baked map has none yet), and so are traffic and police.

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


DT = 1.0 / 60.0


def _script(spec):
    """[(seconds, throttle, brake, steer, handbrake, bumper)] -> per-step inputs."""
    out = []
    for secs, *inp in spec:
        out += [tuple(inp)] * int(round(secs / DT))
    return out


# (name, start x, y or None for the spawn, heading or None for along the road, script)
DRIVES = [
    ("spawn_into_house_and_back", None, None, None,
     [(2.0, 1, 0, 0.0, 0, 0), (1.0, 0, 0, 0.0, 0, 0), (3.0, 0, 1, -0.6, 0, 0), (2.0, 1, 0, 0.8, 0, 0)]),
    ("highway_104_onto_the_deck", -1655.0, -2000.0, None,
     [(9.0, 1, 0, 0.0, 0, 0), (2.0, 0, 0, 0.1, 0, 0)]),
    ("downtown_weave_and_handbrake", 394.6, -835.8, None,
     [(3.0, 1, 0, 0.0, 0, 0), (1.0, 1, 0, 0.7, 0, 0), (1.0, 1, 0, -0.7, 0, 0), (0.8, 0, 0, 1.0, 1, 0),
      (2.0, 0, 1, 0.0, 0, 0)]),
    ("power_slide_and_boost", 1574.0, -1230.0, None,
     [(4.0, 1, 0, 0.0, 0, 0), (0.1, 1, 0, 0.9, 0, 1), (2.2, 1, 0, 0.9, 0, 1), (2.0, 1, 0, 0.0, 0, 0)]),
    ("hill_coast", -679.0, 445.0, None,
     [(3.0, 1, 0, 0.0, 0, 0), (5.0, 0, 0, 0.0, 0, 0)]),
]


def drive_runs(world):
    from game.car import player_car
    from game.collision import move_and_slide, settle_height
    from game.main import start_on_road
    rows = []
    world.props_near = lambda *a, **k: []                  # no props in the baked map yet
    for name, sx, sy, sh, spec in DRIVES:
        if sx is None:
            x, y, h = world.spawn()
        else:
            x, y, h = start_on_road(world, sx, sy)
            if sh is not None:
                h = sh
        car = player_car(0, x, y, h)
        car.z = world.height_at(x, y, world.ground(x, y))
        rows.append((name, 0, 0, 0, 0.0, 0, 0, car.x, car.y, car.z, car.heading, car.vx, car.vy))
        for step, (th, br, st, hb, bu) in enumerate(_script(spec), 1):
            px, py = car.x, car.y
            car.update(DT, bool(th), bool(br), st, bool(hb), on_road=world.on_road(car.x, car.y), bumper=bool(bu))
            move_and_slide(car, world, px, py, thorough=True)
            settle_height(car, world, DT)
            rows.append((name, step, th, br, st, hb, bu, car.x, car.y, car.z, car.heading, car.vx, car.vy))
    return rows


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
    rows = drive_runs(world)
    path = os.path.join(args.out, "drive.csv")
    with open(path, "w") as f:
        f.write("run,step,throttle,brake,steer,handbrake,bumper,x,y,z,heading,vx,vy\n")
        for r in rows:
            f.write("%s,%d,%d,%d,%.3f,%d,%d,%.6f,%.6f,%.6f,%.8f,%.6f,%.6f\n" % r)
    print("wrote %s: %d drives, %d steps" % (path, len(DRIVES), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
