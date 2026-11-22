#!/usr/bin/env python3
"""Golden files for the native C++ game's parity tests: what the Python game answers, for the C++ game to match.

    python tools/golden.py                 # -> dist/golden/*.csv (bake the map with tools/bake_native.py too)

heights.csv   x, y, z_hint, ground, height_at   surface heights on the real map: random points, plus points on and
              beside every overpass deck at the deck level and at the ground (so both levels are checked)
drive.csv     run, step, throttle, brake, steer, handbrake, bumper, x, y, z, heading, vx, vy
              scripted drives with player 1's car (game/car.py physics, game/collision.py move_and_slide and
              settle_height, exactly as game/main.py steps the player at 60 Hz). Step 0 is the start; each later row
              holds the inputs of that step and the state after it. Trees and props are planted exactly as the
              baked map has them (bake_native.plant_everything); traffic and police are left out.
paths.csv     src, dst, path (node ids, space separated; "none")   A* routes on the road graph between node pairs
nearest.csv   x, y, max_r, heading ("none"), node ("none")         nearest_node lookups, with and without a heading
traffic.csv   run, step, car, pace, x, y, heading, vx, vy, steer, throttle, brake, edge
              civilian drivers (game/ai.py drive_traffic at 20 Hz, game/town.py's physics step at 60 Hz, no
              junction rules) on fixed starts. At each junction the driver takes the most likely turn (the largest
              of choose_next's weights, the first on a tie) instead of a random one, so the run repeats exactly.

Fixed seed, so the files only change when the map or the game's rules change.
"""
import argparse
import math
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


# a tree downtown (340.8, -842.8): start 25 m west of it and drive straight at it, then reverse and go round
TREE_DRIVE = ("into_a_tree", 315.8, -842.8, 0.0,
              [(3.0, 1, 0, 0.0, 0, 0), (1.5, 0, 1, 0.0, 0, 0), (2.0, 1, 0, 0.5, 0, 0)])

# (name, start x, y or None for the spawn, heading (exact start) or None for along the nearest road, script)
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
    TREE_DRIVE,
]


def drive_runs(world):
    from game.car import player_car
    from game.collision import move_and_slide, settle_height
    from game.main import start_on_road
    rows = []
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from bake_native import plant_everything
    plant_everything(world)                               # the same trees as the baked map
    for name, sx, sy, sh, spec in DRIVES:
        if sx is None:
            x, y, h = world.spawn()
        elif sh is not None:                                 # an exact start (aimed at something)
            x, y, h = sx, sy, sh
        else:
            x, y, h = start_on_road(world, sx, sy)
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


def path_samples(graph, n=300, seed=11):
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        a = rng.randrange(len(graph.nodes))
        ax, ay = graph.nodes[a]
        near = [b for b in range(len(graph.nodes))
                if abs(graph.nodes[b][0] - ax) < 1500 and abs(graph.nodes[b][1] - ay) < 1500]
        b = rng.choice(near)
        rows.append((a, b, graph.shortest_path(a, b)))
    return rows


def nearest_samples(world, graph, n=400, seed=12):
    rng = random.Random(seed)
    x0, y0, x1, y1 = world.bounds
    rows = []
    for k in range(n):
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        if k % 2:                                           # half of them near a node, so they find one
            nx, ny = graph.nodes[rng.randrange(len(graph.nodes))]
            x, y = nx + rng.uniform(-60, 60), ny + rng.uniform(-60, 60)
        r = rng.choice((70.0, 80.0, 90.0))
        h = rng.uniform(-math.pi, math.pi) if k % 3 else None
        rows.append((x, y, r, h, graph.nearest_node(x, y, r, h)))
    return rows


def best_next(graph):
    """choose_next without the dice: the turn with the largest weight (the first on a tie)."""
    def choose(eid, _rng=None):
        e = graph.edges[eid]
        cands = graph.out[e.b]
        fwd = [c for c in cands if graph.edges[c].b != e.a] or list(cands)
        if not fwd:
            return None
        best, best_w = None, -1.0
        for c in fwd:
            n = graph.edges[c]
            w = 0.5 + 1.5 * max(0.0, e.dx * n.dx + e.dy * n.dy)
            if n.rtype == "lane":
                w *= 0.4
            if w > best_w:
                best, best_w = c, w
        return best
    return choose


def start_edge(graph, x, y, heading):
    """The graph edge whose lane passes nearest (x, y) heading the same way (within 60 degrees)."""
    best = None
    for eid in graph.edges_near(x, y, 40.0):
        e = graph.edges[eid]
        if e.dx * math.cos(heading) + e.dy * math.sin(heading) < 0.5:
            continue
        lx, ly = e.ax - e.dy * e.lane, e.ay + e.dx * e.lane
        s = max(0.0, min(e.length, (x - lx) * e.dx + (y - ly) * e.dy))
        d = math.hypot(lx + e.dx * s - x, ly + e.dy * s - y)
        if best is None or d < best[0]:
            best = (d, eid, s)
    return best[1], best[2]


# (name, seconds, [(x, y, heading, ahead metres, pace)]): each car starts on the lane nearest its point, `ahead`
# metres further along the same edge chain
TRAFFIC = [
    ("downtown_loop", 40.0, [(394.6, -835.8, 0.0, 0.0, 1.0)]),
    ("follow_a_slow_car", 30.0, [(-1655.0, -2000.0, 1.5708, 0.0, 1.0), (-1655.0, -2000.0, 1.5708, 25.0, 0.55)]),
    ("side_streets", 40.0, [(1574.0, -1230.0, 3.1416, 0.0, 0.95)]),
]
CONTROL_DT = 0.05


def traffic_runs(world, graph):
    from game.ai import AICar, PAL_TRAFFIC, drive_traffic
    from game.collision import collide_cars, move_and_slide, settle_height
    choose = best_next(graph)
    graph.choose_next = choose
    rows = []
    for name, secs, starts in TRAFFIC:
        cars = []
        for x, y, h, ahead, pace in starts:
            eid, s = start_edge(graph, x, y, h)
            s += ahead
            while s > graph.edges[eid].length - 0.5:
                s -= graph.edges[eid].length
                eid = choose(eid)
            cx, cy, ch = graph.lane_point(eid, s)
            c = AICar("traffic", PAL_TRAFFIC[0], cx, cy, ch)
            c.z = world.height_at(cx, cy, 0.0)
            c.edge, c.nxt, c.pace = eid, choose(eid), pace
            v = graph.edges[eid].cruise * pace
            c.vx, c.vy = math.cos(ch) * v, math.sin(ch) * v
            cars.append(c)
        acc = 0.0
        for k, c in enumerate(cars):
            rows.append((name, 0, k, c.pace, c.x, c.y, c.heading, c.vx, c.vy, c.steer, int(c.throttle), int(c.brake),
                         c.edge))
        for step in range(1, int(round(secs / DT)) + 1):    # game/town.py Town.update, for these cars only
            acc += DT
            if acc >= CONTROL_DT:
                ctl, acc = acc, 0.0
                for c in cars:
                    drive_traffic(c, graph, cars, None, ctl, None, 0.0)
            for c in cars:
                px, py = c.x, c.y
                c.update(DT, c.throttle, c.brake, c.steer, False, True)
                move_and_slide(c, world, px, py)
                settle_height(c, world, DT)
            for i in range(len(cars)):
                for j in range(i + 1, len(cars)):
                    a, b = cars[i], cars[j]
                    if abs(a.x - b.x) <= 6.0 and abs(a.y - b.y) <= 6.0:
                        collide_cars(a, b)
            for k, c in enumerate(cars):
                rows.append((name, step, k, c.pace, c.x, c.y, c.heading, c.vx, c.vy, c.steer, int(c.throttle), int(c.brake),
                             -1 if c.edge is None else c.edge))
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
    from game.roadgraph import RoadGraph
    graph = RoadGraph(world.roads)
    rows = path_samples(graph)
    with open(os.path.join(args.out, "paths.csv"), "w") as f:
        f.write("src,dst,path\n")
        for a, b, p in rows:
            f.write("%d,%d,%s\n" % (a, b, " ".join(map(str, p)) if p else "none"))
    print("wrote paths.csv: %d routes (%d found)" % (len(rows), sum(1 for r in rows if r[2])))
    rows = nearest_samples(world, graph)
    with open(os.path.join(args.out, "nearest.csv"), "w") as f:
        f.write("x,y,max_r,heading,node\n")
        for x, y, r, h, n in rows:
            f.write("%.4f,%.4f,%.1f,%s,%s\n" % (x, y, r, "none" if h is None else "%.6f" % h,
                                               "none" if n is None else n))
    print("wrote nearest.csv: %d lookups" % len(rows))
    rows = traffic_runs(world, graph)
    with open(os.path.join(args.out, "traffic.csv"), "w") as f:
        f.write("run,step,car,pace,x,y,heading,vx,vy,steer,throttle,brake,edge\n")
        for r in rows:
            f.write("%s,%d,%d,%.4f,%.6f,%.6f,%.8f,%.6f,%.6f,%.6f,%d,%d,%d\n" % r)
    print("wrote traffic.csv: %d runs, %d rows" % (len(TRAFFIC), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
