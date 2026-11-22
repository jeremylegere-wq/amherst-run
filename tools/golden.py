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
              civilian drivers (game/ai.py drive_traffic at 20 Hz with game/junctions.py's rules on the town clock,
              game/town.py's physics step at 60 Hz) on fixed starts, and cars converging on a junction with lights,
              one with stop signs and an all-way one, from every approach. At each junction the driver takes the
              most likely turn (the largest of choose_next's weights, the first on a tie) instead of a random one,
              so the run repeats exactly.
jobs.tsv      tab-separated: "address" x y text (MissionManager.address: the real civic number on that street within 45 m,
              else a made-up one), "route" ax ay bx by metres (_route_len, which sizes delivery time limits), and
              "tour" hub label (targets as label@x@y joined by |) time-limit reward (_make_tour from each tour hub;
              only tours that need no random fill-in checkpoints)
items.tsv     tab-separated: "box" x y (game/items.py box_sites downtown, as a balloon battle lays them out),
              and "shot" run step x y result (step_shot of a puck and a seeker fired at fixed spots downtown, with a
              rival car to home on and hit: positions every step, then "gone" / "hit" / "fly")
police.csv    run, step, car (0 = the player, then police), x, y, heading, vx, vy
              police chases (game/ai.py drive_police at 20 Hz, game/town.py's physics step at 60 Hz) of a player
              who is parked, or driving a script. Police re-plan their route every 1.0 + 0.4 * random() s; here
              random() is always 0.5, so the run repeats exactly.

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
    ("signal_crossing", 35.0, ("junction", 738.0, 39.0)),     # OSM traffic lights
    ("stop_crossing", 30.0, ("junction", 1876.0, -104.0)),    # OSM stop sign
    ("allway_crossing", 30.0, ("junction", 353.0, 120.0)),    # a plain 4-way of equal streets
]
CONTROL_DT = 0.05


def _junction_starts(graph, x, y):
    """(edge id, distance along it) for one car on every road into the junction node nearest (x, y), 40 m back."""
    n = graph.nearest_node(x, y, 20.0)
    out = []
    for eid, e in enumerate(graph.edges):
        if e.b == n:
            out.append((eid, max(0.0, e.length - 40.0)))
    return out


def traffic_runs(world, graph):
    from game.ai import AICar, PAL_TRAFFIC, drive_traffic
    from game.collision import collide_cars, move_and_slide, settle_height
    from game.junctions import Junctions
    choose = best_next(graph)
    graph.choose_next = choose
    junctions = Junctions(graph, getattr(world, "marks", ()))
    rows = []
    for name, secs, starts in TRAFFIC:
        cars = []
        if starts[0] == "junction":
            places = [(eid, s, 1.0) for eid, s in _junction_starts(graph, starts[1], starts[2])]
        else:
            places = []
            for x, y, h, ahead, pace in starts:
                eid, s = start_edge(graph, x, y, h)
                s += ahead
                while s > graph.edges[eid].length - 0.5:
                    s -= graph.edges[eid].length
                    eid = choose(eid)
                places.append((eid, s, pace))
        for eid, s, pace in places:
            cx, cy, ch = graph.lane_point(eid, s)
            c = AICar("traffic", PAL_TRAFFIC[0], cx, cy, ch)
            c.z = world.height_at(cx, cy, 0.0)
            c.edge, c.nxt, c.pace = eid, choose(eid), pace
            v = graph.edges[eid].cruise * pace
            c.vx, c.vy = math.cos(ch) * v, math.sin(ch) * v
            cars.append(c)
        acc, now = 0.0, 0.0
        for k, c in enumerate(cars):
            rows.append((name, 0, k, c.pace, c.x, c.y, c.heading, c.vx, c.vy, c.steer, int(c.throttle), int(c.brake),
                         c.edge))
        for step in range(1, int(round(secs / DT)) + 1):    # game/town.py Town.update, for these cars only
            now += DT
            acc += DT
            if acc >= CONTROL_DT:
                ctl, acc = acc, 0.0
                for c in cars:
                    drive_traffic(c, graph, cars, None, ctl, junctions, now)
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


def job_samples(world, graph, n=300, seed=13):
    """jobs.tsv rows (see the module doc)."""
    from game.missions import MissionManager

    class _Town:
        cops = True
    _Town.graph = graph
    mm = MissionManager(world, _Town())
    rng = random.Random(seed)
    rows = []
    for _ in range(n):                                  # addresses at random lane points
        x, y, _h = graph.lane_point(rng.randrange(len(graph.edges)), 0.0)
        x += rng.uniform(-8, 8)
        y += rng.uniform(-8, 8)
        rows.append(("address", "%.3f" % x, "%.3f" % y, mm.address(x, y)))
    routes = 0
    while routes < 100:                                 # route lengths between points 100-900 m apart
        a = graph.nodes[rng.randrange(len(graph.nodes))]
        b = graph.nodes[rng.randrange(len(graph.nodes))]
        if not 100 < math.hypot(a[0] - b[0], a[1] - b[1]) < 900:
            continue
        routes += 1
        a = (a[0] + rng.uniform(-10, 10), a[1] + rng.uniform(-10, 10))
        b = (b[0] + rng.uniform(-10, 10), b[1] + rng.uniform(-10, 10))
        rows.append(("route", "%.3f" % a[0], "%.3f" % a[1], "%.3f" % b[0], "%.3f" % b[1], "%.4f" % mm._route_len(a, b)))

    class _NoDice:
        def __getattr__(self, name):
            raise LookupError("needs random checkpoints")
    for hub in mm.all_hubs:
        if hub.role != "tour":
            continue
        mm.rng = _NoDice()
        try:
            m = mm._make_tour(hub)
        except LookupError:
            continue
        targets = "|".join("%s@%.4f@%.4f" % (t.label, t.x, t.y) for t in m.targets)
        rows.append(("tour", hub.label, targets, "%.4f" % m.time_limit, str(m.reward)))
    return rows


SHOTS = [  # (name, kind, x, y, heading, rival x, y): a puck into a wall (it bounces), a seeker after a rival
    ("puck_off_the_walls", "puck", 395.0, -836.0, 0.3, None),
    ("puck_down_the_street", "puck", 331.25, -761.25, 2.36, None),
    ("seeker_after_a_rival", "seeker", 331.25, -761.25, 2.0, (300.0, -730.0)),
]


def item_samples(world, graph):
    from game import items as I
    from game.battle import ARENA, ARENA_RADIUS
    from game.car import player_car
    rows = [("box", "%.4f" % b.x, "%.4f" % b.y) for b in I.box_sites(graph, ARENA, ARENA_RADIUS)]
    for name, kind, x, y, h, rival in SHOTS:
        car = player_car(0, x, y, h)
        shot = I.fire(kind, car, 0)
        rivals = [(1, player_car(1, rival[0], rival[1], 0.0))] if rival else []
        res = "fly"
        for step in range(1, 601):
            res = I.step_shot(shot, world, DT, rivals)
            rows.append(("shot", name, str(step), "%.5f" % shot.x, "%.5f" % shot.y,
                         res if isinstance(res, str) else "hit"))
            if res != "fly":
                break
    return rows


class _Half:
    """A stand-in for random.Random whose random() is always 0.5 (the police's re-planning interval)."""
    def random(self):
        return 0.5


# (name, seconds, heat active, v_cap, player start (x, y) or None for the spawn, player script, police starts
# [(x, y, heading)] each put on the nearest lane heading that way)
POLICE = [
    ("box_in_a_parked_player", 25.0, True, 31.0, (331.25, -761.25), [(25.0, 0, 0, 0.0, 0, 0)],
     [(331.0, -840.0, -1.5708)]),
    ("chase_a_driving_player", 30.0, True, 31.0, (-1655.0, -2000.0),
     [(10.0, 1, 0, 0.0, 0, 0), (3.0, 1, 0, 0.6, 0, 0), (17.0, 1, 0, 0.0, 0, 0)],
     [(-1650.0, -2060.0, 1.5708), (-1640.0, -2120.0, 1.5708)]),
    ("stand_down", 12.0, False, 26.0, (394.6, -835.8), [(12.0, 0, 0, 0.0, 0, 0)], [(394.0, -900.0, 1.5708)]),
]


def police_runs(world, graph):
    from game.ai import AICar, PAL_POLICE, drive_police
    from game.car import player_car
    from game.collision import collide_cars, move_and_slide, settle_height
    from game.main import start_on_road
    rows = []
    for name, secs, active, v_cap, pstart, script, starts in POLICE:
        x, y, h = start_on_road(world, *pstart)
        player = player_car(0, x, y, h)
        player.z = world.height_at(x, y, world.ground(x, y))
        cops = []
        for cx, cy, ch in starts:
            eid, s = start_edge(graph, cx, cy, ch)
            lx, ly, lh = graph.lane_point(eid, s)
            c = AICar("police", PAL_POLICE, lx, ly, lh)
            c.z = world.height_at(lx, ly, 0.0)
            c.path_t = 0.5                                       # (the town staggers this with random())
            c.vx, c.vy = math.cos(lh) * 10.0, math.sin(lh) * 10.0
            cops.append(c)
        rng, acc = _Half(), 0.0
        everyone = [player] + cops
        for k, c in enumerate(everyone):
            rows.append((name, 0, k, c.x, c.y, c.heading, c.vx, c.vy))
        for step, (th, br, st, hb, bu) in enumerate(_script(script), 1):
            px, py = player.x, player.y                          # game/main.py: the player first
            player.update(DT, bool(th), bool(br), st, bool(hb), on_road=world.on_road(player.x, player.y),
                          bumper=bool(bu))
            move_and_slide(player, world, px, py, thorough=True)
            settle_height(player, world, DT)
            acc += DT                                            # then game/town.py Town.update
            if acc >= CONTROL_DT:
                ctl, acc = acc, 0.0
                for c in cops:
                    drive_police(c, graph, world, player, cops, ctl, rng, active, v_cap)
            for c in cops:
                px, py = c.x, c.y
                c.update(DT, c.throttle, c.brake, c.steer, False, world.on_road(c.x, c.y))
                move_and_slide(c, world, px, py)
                settle_height(c, world, DT)
            for i in range(len(everyone)):
                for j in range(i + 1, len(everyone)):
                    a, b = everyone[i], everyone[j]
                    if abs(a.x - b.x) <= 6.0 and abs(a.y - b.y) <= 6.0:
                        collide_cars(a, b)
            for k, c in enumerate(everyone):
                rows.append((name, step, k, c.x, c.y, c.heading, c.vx, c.vy))
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
    rows = job_samples(world, graph)
    with open(os.path.join(args.out, "jobs.tsv"), "w") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")
    print("wrote jobs.tsv: %d addresses, %d routes, %d tours" % tuple(sum(1 for r in rows if r[0] == k)
                                                                     for k in ("address", "route", "tour")))
    rows = item_samples(world, graph)
    with open(os.path.join(args.out, "items.tsv"), "w") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")
    print("wrote items.tsv: %d boxes, %d shot steps" % (sum(1 for r in rows if r[0] == "box"),
                                                       sum(1 for r in rows if r[0] == "shot")))
    rows = police_runs(world, graph)
    with open(os.path.join(args.out, "police.csv"), "w") as f:
        f.write("run,step,car,x,y,heading,vx,vy\n")
        for r in rows:
            f.write("%s,%d,%d,%.6f,%.6f,%.8f,%.6f,%.6f\n" % r)
    print("wrote police.csv: %d runs, %d rows" % (len(POLICE), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
