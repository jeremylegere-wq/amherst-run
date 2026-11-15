#!/usr/bin/env python3
"""Benchmark traffic + police + 3D rendering together, without a window.

Usage (from the project root):
    python tools/bench_town.py                       # dense synthetic town
    python tools/bench_town.py data/amherst_map.json # your real map
    python tools/bench_town.py data/amherst_map.json --style street --weather snow

Simulates a parked player with 4 wanted stars and 30 civilian cars for 20 seconds at 30 fps
(2 physics steps per frame) and reports the cost of the AI step and of rendering, in ms.
The budget for 30 fps is 33 ms per frame for everything.
"""
import math
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402

import make_sample_map  # noqa: E402
from game import config as C  # noqa: E402
from game.car import Car  # noqa: E402
from game.render3d import ChaseCamera, Renderer3D  # noqa: E402
from game.town import Town  # noqa: E402
from game.world import World  # noqa: E402


def stats(label, xs):
    xs = sorted(xs)
    print(f"  {label:18s} avg {sum(xs)/len(xs):6.2f} ms   p95 {xs[int(len(xs)*0.95)]:6.2f} ms   max {xs[-1]:6.2f} ms")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", default=None)
    ap.add_argument("--style", default="retro", help="renderer style (default retro, as older numbers used)")
    ap.add_argument("--weather", default="clear")
    ap.add_argument("--at", default=None, metavar="X,Y",
                    help="park the player here instead of the spawn (Victoria Square, the old spawn: 394.6,-835.8)")
    args = ap.parse_args()
    if args.map:
        world, label = World.load(args.map), args.map
    else:
        make_sample_map.BLOCK = 40
        world, label = World(make_sample_map.build(extent=60)), "dense synthetic town"
    pygame.init()
    pygame.display.set_mode((C.INTERNAL_W, C.INTERNAL_H))
    surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))

    t0 = time.perf_counter()
    town = Town(world, seed=2, traffic=30)
    print(f"{label} [{args.style}, {args.weather}]: {len(world.buildings)} buildings, {len(world.roads)} roads")
    print(f"  road graph + town built in {(time.perf_counter()-t0)*1000:.0f} ms "
          f"({len(town.graph.nodes)} nodes, {len(town.graph.edges)} edges)")
    r3d = Renderer3D(world, style=args.style, weather=args.weather)
    x, y, h = world.spawn()
    if args.at:
        x, y = (float(v) for v in args.at.split(","))
    player = Car(x, y, h)
    cam = ChaseCamera(player, world)
    town.add_heat(4.0)

    ai_ms, render_ms, total_ms = [], [], []
    for frame in range(30 * 20):
        t0 = time.perf_counter()
        for _ in range(2):
            town.update(1 / 60, player)
        t1 = time.perf_counter()
        cam.update(player, 1 / 30)
        r3d.render(surf, player, cam, others=town.cars, t=town.time)
        t2 = time.perf_counter()
        ai_ms.append((t1 - t0) * 1000)
        render_ms.append((t2 - t1) * 1000)
        total_ms.append((t2 - t0) * 1000)
    stats("AI + physics", ai_ms)
    stats("3D render", render_ms)
    stats("frame total", total_ms)
    worst = max(total_ms)
    print(f"  cars alive: {len(town.cars)} (police {len(town.police)}); worst frame {worst:.1f} ms "
          f"-> {'OK for 30 fps' if worst < 33 else 'over the 33 ms budget'}")


if __name__ == "__main__":
    main()
