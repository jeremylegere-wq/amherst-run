#!/usr/bin/env python3
"""Benchmark the 3D renderer without a window.

Usage (from the project root):
    python tools/bench_render.py                  # sample town + large synthetic town
    python tools/bench_render.py data/amherst_map.json

Drives a car down a road (with a little steering) and reports ms per rendered frame.
Budget for 30 fps is 33 ms for everything, so rendering should stay well under ~20 ms.
"""
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402

import make_sample_map  # noqa: E402
from game import config as C  # noqa: E402
from game.car import Car  # noqa: E402
from game.render3d import ChaseCamera, Renderer3D  # noqa: E402
from game.world import World  # noqa: E402


def bench(world, label, frames=300, shot=None):
    pygame.init()
    pygame.display.set_mode((C.INTERNAL_W, C.INTERNAL_H))
    surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
    t0 = time.perf_counter()
    r = Renderer3D(world)
    prep = time.perf_counter() - t0
    x, y, h = world.spawn()
    car = Car(x, y, h)
    cam = ChaseCamera(car, world)
    times, polys, blds = [], [], []
    for n in range(frames):
        steer = 0.0
        for _ in range(2):
            car.update(1 / 60, True, False, steer, False, world.on_road(car.x, car.y))
        cam.update(car, 1 / 30)
        t = time.perf_counter()
        r.render(surf, car, cam)
        times.append((time.perf_counter() - t) * 1000)
        polys.append(r.polys)
        blds.append(r.n_buildings)
    if shot:
        pygame.image.save(surf, shot)
    times.sort()
    avg = sum(times) / len(times)
    print(f"{label}: {len(world.buildings)} buildings, {len(world.roads)} roads | prep {prep*1000:.0f} ms | "
          f"render avg {avg:.1f} ms, p95 {times[int(len(times)*0.95)]:.1f} ms, max {times[-1]:.1f} ms "
          f"(~{1000/avg:.0f} fps) | polys avg {sum(polys)/len(polys):.0f}, max {max(polys)}, "
          f"buildings drawn avg {sum(blds)/len(blds):.0f}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        bench(World.load(sys.argv[1]), sys.argv[1])
    else:
        bench(World(make_sample_map.build()), "sample town", shot="screenshots/bench_sample.png")
        bench(World(make_sample_map.build(extent=24)), "large synthetic town", shot="screenshots/bench_large.png")
