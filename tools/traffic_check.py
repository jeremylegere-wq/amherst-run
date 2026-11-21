#!/usr/bin/env python3
"""Measure how civilian traffic behaves, so changes to game/ai.py and game/town.py can be compared.

    python tools/traffic_check.py                  # three spots on the real map, 90 s each
    python tools/traffic_check.py --seconds 60 --drive

For each spot the player's car is parked (or, with --drive, drives along the road graph) and the town runs at 60 Hz.
Reported per spot: traffic cars around on average, AI-vs-AI crashes, cars removed because they were stuck or jammed,
cars that appeared inside the player's view (pop-in: spawned within 160 m in front), and the average speed of
moving traffic as a share of its road's limit.
"""
import argparse
import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import collision, town as T  # noqa: E402
from game.car import player_car  # noqa: E402
from game.world import World  # noqa: E402

SPOTS = {"downtown": (394.6, -835.8, -67.0), "residential": (1814.0, -1447.1, -144.0), "rural": (6330.0, 3010.0, 45.0)}


def run(world, x, y, heading_deg, seconds, seed=3, traffic=None):
    player = player_car(0, x, y, math.radians(heading_deg))
    player.z = world.ground(x, y)
    town = T.Town(world, seed=seed, **({} if traffic is None else {"traffic": traffic}))
    town.set_cops(False)
    stats = {"crash": 0, "jam": 0, "popin": 0, "samples": 0, "cars": 0, "pace": [], "spawned": 0}
    real_collide = collision.collide_cars

    def counting(a, b):
        imp = real_collide(a, b)
        if imp > 0.8 and a.kind == "traffic" and b.kind == "traffic":
            stats["crash"] += 1
        return imp
    T.collide_cars = counting
    seen = set()
    fx, fy = math.cos(player.heading), math.sin(player.heading)
    for k in range(int(seconds * 60)):
        before = {id(c): c for c in town.cars}
        town.update(1 / 60, player)
        now = {id(c) for c in town.cars}
        for cid, c in before.items():
            if cid not in now and (c.stuck > 6.0 or c.wait > 20.0):
                stats["jam"] += 1
        for c in town.cars:
            if id(c) in seen:
                continue
            seen.add(id(c))
            if k > 60:                                       # spawned after the first second (not the initial fill)
                stats["spawned"] += 1
                dx, dy = c.x - player.x, c.y - player.y
                d = math.hypot(dx, dy)
                if d < 160.0 and dx * fx + dy * fy > d * 0.5:
                    stats["popin"] += 1
        if k % 30 == 0:
            stats["samples"] += 1
            stats["cars"] += sum(1 for c in town.cars if c.kind == "traffic")
            for c in town.cars:
                if c.kind == "traffic" and c.edge is not None and c.speed > 2.0:
                    stats["pace"].append(c.speed / max(1.0, town.graph.edges[c.edge].cruise))
    T.collide_cars = real_collide
    pace = sum(stats["pace"]) / len(stats["pace"]) if stats["pace"] else 0.0
    return {"cars": round(stats["cars"] / max(1, stats["samples"]), 1), "ai_crashes": stats["crash"],
            "jams": stats["jam"], "pop_in": stats["popin"], "spawned": stats["spawned"], "pace": round(pace, 2)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--traffic", type=int, default=None, help="override the town's traffic target")
    args = ap.parse_args(argv)
    world = World.load(args.map)
    total = {}
    for name, (x, y, h) in SPOTS.items():
        r = run(world, x, y, h, args.seconds, traffic=args.traffic)
        print("%-12s %s" % (name, "  ".join("%s %s" % kv for kv in r.items())))
        for k, v in r.items():
            total[k] = total.get(k, 0) + v
    return 0


if __name__ == "__main__":
    sys.exit(main())
