#!/usr/bin/env python3
"""Autopilot for testing: drives the PLAYER car along the road graph to a point and stops there.

Used by tests and by `python tools/autopilot.py` to check that missions can be finished inside
their time limits with the real car physics (no teleporting).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.ai import obstacle_limit, speed_control, steer_to, wrap  # noqa: E402


class Autopilot:
    def __init__(self, graph, cruise=17.0):
        self.graph, self.cruise = graph, cruise
        self.route, self.replan = [], 0.0
        self.target = None
        self.stuck, self.reverse_t, self.rev_steer = 0.0, 0.0, 1.0

    def set_target(self, x, y):
        self.target, self.route, self.replan = (x, y), [], 0.0

    def controls(self, car, dt, others=()):
        """Return (throttle, brake, steer, handbrake) for this physics step."""
        if self.target is None:
            return False, car.forward_speed() > 1.0, 0.0, False
        if self.reverse_t > 0.0:                         # backing out of a tree or a jam
            self.reverse_t -= dt
            return False, True, self.rev_steer, False
        g, (gx, gy) = self.graph, self.target
        self.replan -= dt
        if self.replan <= 0.0:
            self.replan = 1.5
            a = g.nearest_node(car.x, car.y, 80.0, car.heading if car.speed > 4.0 else None)
            b = g.nearest_node(gx, gy, 80.0)
            self.route = (g.shortest_path(a, b) or []) if a is not None and b is not None else []
        nodes = g.nodes
        while self.route and math.hypot(nodes[self.route[0]][0] - car.x, nodes[self.route[0]][1] - car.y) < 8.0:
            self.route.pop(0)
        dist_goal = math.hypot(gx - car.x, gy - car.y)
        if self.route and dist_goal > 25.0:
            tx, ty = nodes[self.route[0]]
            v = self.cruise
            if len(self.route) > 1:
                nx, ny = nodes[self.route[1]]
                ang = abs(wrap(math.atan2(ny - ty, nx - tx) - math.atan2(ty - car.y, tx - car.x)))
                vc = max(6.0, self.cruise * (1.0 - 1.1 * ang / math.pi))
                d = math.hypot(tx - car.x, ty - car.y)
                v = min(v, math.sqrt(vc * vc + 2 * 8.0 * max(0.0, d - 4.0)))
        else:
            tx, ty = gx, gy
            v = max(0.0, (dist_goal - 1.5) * 0.7)          # ease in and stop on the spot
        steer, err = steer_to(car, tx, ty)
        if abs(err) > 1.0:
            v = min(v, 6.0)
        v = min(v, obstacle_limit(car, others, look=14.0, width=2.0))
        speed_control(car, v)
        if car.speed < 1.0 and v > 3.0:
            self.stuck += dt
        else:
            self.stuck = max(0.0, self.stuck - dt)
        if self.stuck > 1.0:
            self.stuck, self.reverse_t, self.rev_steer = 0.0, 1.0, (-1.0 if steer >= 0 else 1.0)
        return car.throttle, car.brake, steer, False


def play_job(game_like, hub_role, max_seconds=240.0):
    """Drive to the hub with the given role, take the job and try to finish it.

    game_like needs: world, town, missions, car. Returns (result_banner, seconds_used, time_limit).
    """
    from game.collision import move_and_slide
    world, town, ms, car = game_like.world, game_like.town, game_like.missions, game_like.car
    hub = next(h for h in ms.hubs if h.role == hub_role)
    pilot = Autopilot(town.graph)
    pilot.set_target(hub.x, hub.y)
    started, limit, t_start = False, None, 0.0
    dt = 1 / 60
    for i in range(int(max_seconds * 60)):
        if ms.mission is not None and not started:
            started, limit, t_start = True, ms.mission.time_limit, i * dt
        if started and ms.mission is None:
            return ms.banner[0] if ms.banner else "?", i * dt - t_start, limit
        if started:
            tgt = ms.current_target()
            if tgt and pilot.target != tgt:
                pilot.set_target(*tgt)
        inputs = pilot.controls(car, dt, town.cars)
        px, py = car.x, car.y
        car.power = town.player_power()
        car.update(dt, *inputs, on_road=world.on_road(car.x, car.y))
        impact = move_and_slide(car, world, px, py, thorough=True)
        town.update(dt, car, impact)
        ms.update(dt, car)
        if town.consume_reset():                 # same as Game.step after BUSTED / WRECKED
            if started:
                return ms.banner[0] if ms.banner else "BUSTED", i * dt - t_start, limit
            town.reset()
            car = game_like.car = type(car)(*world.spawn())
            pilot.set_target(hub.x, hub.y)
    return "TIMEOUT (autopilot)", max_seconds, limit


if __name__ == "__main__":
    from types import SimpleNamespace
    from game.car import Car
    from game.missions import MissionManager
    from game.town import Town
    from game.world import World
    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_map.json"
    world = World.load(path)
    for role in ("deliveries", "tour"):
        for seed in range(1, 6):
            town = Town(world, seed=seed, traffic=12)
            g = SimpleNamespace(world=world, town=town, car=Car(*world.spawn()))
            g.missions = MissionManager(world, town, seed=seed)
            if not any(h.role == role for h in g.missions.hubs):
                print(f"{role}: no hub on this map")
                break
            result, used, limit = play_job(g, role)
            lim = f"{limit:.0f}s" if limit else "-"
            print(f"{role:10s} seed {seed}: {result:22s} used {used:5.1f}s of {lim}  cash ${g.missions.cash}")
