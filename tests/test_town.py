"""Tests for M4: collisions, road graph, traffic, police and the wanted system, converter extras.

Run from the project root:  python -m unittest discover -s tests -v
"""
import io
import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import make_sample_map  # noqa: E402
import osm_to_map  # noqa: E402
from game import ai  # noqa: E402
from game import town as town_mod  # noqa: E402
from game.ai import AICar, PAL_POLICE, PAL_TRAFFIC  # noqa: E402
from game.car import Car  # noqa: E402
from game.collision import car_hits_world, collide_cars, move_and_slide  # noqa: E402
from game.roadgraph import RoadGraph  # noqa: E402
from game.town import Town  # noqa: E402
from game.world import World  # noqa: E402


def road(points, rtype="side", width=8, **extra):
    r = {"type": rtype, "width": width, "points": [list(p) for p in points]}
    r.update(extra)
    return r


def world_with_wall():
    data = make_sample_map.build()
    data["buildings"] = [{"points": [[20, -30], [60, -30], [60, 30], [20, 30]]}]
    return World(data)


def simulate(world, drive, seconds, heat=0.0, seed=5, traffic=16):
    """Headless copy of Game.step. Returns (town, player). Stops at the first reset request."""
    town = Town(world, seed=seed, traffic=traffic)
    x, y, h = world.spawn()
    p = Car(x, y, h)
    if heat:
        town.add_heat(heat)
    for i in range(int(seconds * 60)):
        inp = drive(i / 60, p, town)
        if town.state != "playing":
            inp = (False, False, 0.0, True)
        px, py = p.x, p.y
        p.power = town.player_power()
        p.update(1 / 60, *inp, on_road=world.on_road(p.x, p.y))
        impact = move_and_slide(p, world, px, py, thorough=True)
        town.update(1 / 60, p, impact)
        if town.consume_reset():
            break
    return town, p


PARKED = lambda t, p, tw: (False, False, 0.0, False)  # noqa: E731


class CollisionTests(unittest.TestCase):
    def setUp(self):
        self.world = world_with_wall()

    def test_glancing_hit_slides_along_the_wall(self):
        car = Car(17.0, 0.0, 0.0)
        car.vx, car.vy = 4.0, 6.0
        px, py = car.x, car.y
        car.x += car.vx * 0.3                   # 18.2: front corners now inside the building
        car.y += car.vy * 0.3
        impact = move_and_slide(car, self.world, px, py)
        self.assertAlmostEqual(impact, 4.0, places=3)
        self.assertEqual(car.x, 17.0)           # x movement undone
        self.assertAlmostEqual(car.y, 1.8, places=3)  # y movement kept: it slid
        self.assertFalse(car_hits_world(car, self.world))
        self.assertLess(car.vx, 0)              # bounced a little
        self.assertGreater(car.vy, 5.0)         # kept most of its sliding speed

    def test_clear_move_reports_no_impact(self):
        car = Car(0.0, 0.0, 0.0)
        self.assertEqual(move_and_slide(car, self.world, -1.0, 0.0), 0.0)

    def test_head_on_reports_full_impact_and_bounces(self):
        car = Car(17.0, 0.0, 0.0)
        car.vx = 10.0
        px, py = car.x, car.y
        car.x += 3.0
        impact = move_and_slide(car, self.world, px, py)
        self.assertAlmostEqual(impact, 10.0, places=3)
        self.assertEqual(car.x, 17.0)
        self.assertLess(car.vx, 0)

    def test_wedged_car_can_crawl_out(self):
        car = Car(40.0, 0.0, 0.0)               # spawned inside the building
        car.vx = 2.0
        px, py = car.x, car.y
        car.x += 1.0
        impact = move_and_slide(car, self.world, px, py)
        self.assertEqual(impact, 0.0)
        self.assertEqual(car.x, 41.0)           # allowed to move, not frozen

    def test_map_edge_blocks(self):
        car = Car(300.0, 0.0, 0.0)              # bounds are +-270 plus a 12 m margin
        self.assertTrue(car_hits_world(car, self.world))

    def test_head_on_cars_bounce_and_separate(self):
        a, b = Car(0.0, 0.0, 0.0), Car(3.5, 0.0, math.pi)
        a.vx, b.vx = 10.0, -10.0
        impact = collide_cars(a, b)
        self.assertAlmostEqual(impact, 20.0, places=3)
        self.assertAlmostEqual(a.vx, -3.5, places=3)
        self.assertAlmostEqual(b.vx, 3.5, places=3)
        self.assertGreater(b.x - a.x, 3.5)      # pushed apart

    def test_heavier_car_is_pushed_less(self):
        light, heavy = Car(0.0, 0.0, 0.0), Car(3.5, 0.0, math.pi)
        heavy.mass = 3.0
        light.vx, heavy.vx = 10.0, -10.0
        collide_cars(light, heavy)
        self.assertGreater(abs(light.vx - 10.0), abs(heavy.vx + 10.0))

    def test_cars_that_are_apart_do_not_collide(self):
        a, b = Car(0.0, 0.0, 0.0), Car(20.0, 0.0, 0.0)
        self.assertEqual(collide_cars(a, b), 0.0)

    def test_damage_reduces_top_speed(self):
        fresh, hurt = Car(), Car()
        hurt.power = 0.65
        for _ in range(60 * 15):
            fresh.update(1 / 60, True, False, 0.0, False, True)
            hurt.update(1 / 60, True, False, 0.0, False, True)
        self.assertLess(hurt.speed, fresh.speed * 0.8)


class RoadGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = make_sample_map.build()
        cls.g = RoadGraph(cls.data["roads"])

    def test_grid_town_junction_degrees(self):
        deg = [len(o) for o in self.g.out]
        self.assertEqual(deg.count(4), 25)      # interior crossings of the 7 x 7 street grid
        self.assertEqual(deg.count(3), 20)      # edge crossings (T shapes)
        self.assertTrue(all(d >= 2 for d in deg))

    def test_every_edge_has_a_reverse_edge(self):
        pairs = {(e.a, e.b) for e in self.g.edges}
        self.assertTrue(all((b, a) in pairs for a, b in pairs))

    def test_corner_to_corner_path(self):
        a, b = self.g.nearest_node(-270, -270), self.g.nearest_node(270, 270)
        path = self.g.shortest_path(a, b)
        self.assertEqual(self.g.nodes[path[0]], (-270.0, -270.0))
        self.assertEqual(self.g.nodes[path[-1]], (270.0, 270.0))
        length = sum(math.hypot(self.g.nodes[p][0] - self.g.nodes[q][0], self.g.nodes[p][1] - self.g.nodes[q][1])
                     for p, q in zip(path, path[1:]))
        self.assertAlmostEqual(length, 1080.0, delta=1.0)   # Manhattan distance on a grid

    def test_edges_are_short(self):
        self.assertTrue(all(e.length <= 50.5 for e in self.g.edges))

    def test_t_junction_is_snapped(self):
        g = RoadGraph([road([(0, 0), (100, 0)]), road([(50, -40), (51.2, 1.5)])])   # spur ends 1.5 m past the road
        a, b = g.nearest_node(50, -40), g.nearest_node(100, 0)
        self.assertIsNotNone(g.shortest_path(a, b))

    def test_separate_roads_are_not_connected(self):
        g = RoadGraph([road([(0, 0), (100, 0)]), road([(0, 50), (100, 50)])])
        self.assertIsNone(g.shortest_path(g.nearest_node(0, 0), g.nearest_node(100, 50)))

    def test_bridge_does_not_connect_to_road_below(self):
        g = RoadGraph([road([(-50, 0), (50, 0)]), road([(0, -50), (0, 50)], bridge=True)])
        self.assertIsNone(g.shortest_path(g.nearest_node(-50, 0), g.nearest_node(0, 50)))
        flat = RoadGraph([road([(-50, 0), (50, 0)]), road([(0, -50), (0, 50)])])
        self.assertIsNotNone(flat.shortest_path(flat.nearest_node(-50, 0), flat.nearest_node(0, 50)))

    def test_one_way_road_only_goes_forward(self):
        g = RoadGraph([road([(0, 0), (100, 0)], oneway=1)])
        a, b = g.nearest_node(0, 0), g.nearest_node(100, 0)
        self.assertIsNotNone(g.shortest_path(a, b))
        self.assertIsNone(g.shortest_path(b, a))
        rev = RoadGraph([road([(0, 0), (100, 0)], oneway=-1)])
        a, b = rev.nearest_node(0, 0), rev.nearest_node(100, 0)
        self.assertIsNone(rev.shortest_path(a, b))
        self.assertIsNotNone(rev.shortest_path(b, a))

    def test_driveways_are_left_out(self):
        g = RoadGraph([road([(0, 0), (100, 0)]), road([(50, 0), (50, 30)], rtype="lane", service="driveway")])
        self.assertEqual(g.nearest_node(50, 30, max_r=10), None)

    def test_lane_is_on_the_right_hand_side(self):
        g = RoadGraph([road([(0, 0), (100, 0)])])
        for eid, e in enumerate(g.edges):
            x, y, h = g.lane_point(eid, 10.0)
            if e.dx > 0:                         # heading east: right-hand side is south (+y)
                self.assertGreater(y, 1.0)
                self.assertAlmostEqual(h, 0.0)
            else:                                # heading west: right-hand side is north (-y)
                self.assertLess(y, -1.0)

    def test_choose_next_never_makes_a_u_turn_with_options(self):
        import random
        rng = random.Random(1)
        for eid, e in enumerate(self.g.edges):
            if len(self.g.out[e.b]) < 2:
                continue
            for _ in range(5):
                nxt = self.g.edges[self.g.choose_next(eid, rng)]
                self.assertNotEqual(nxt.b, e.a)

    def test_dead_end_allows_a_u_turn(self):
        import random
        g = RoadGraph([road([(0, 0), (60, 0)])])
        eid = next(i for i, e in enumerate(g.edges) if e.dx > 0 and len(g.out[e.b]) == 1)
        self.assertIsNotNone(g.choose_next(eid, random.Random(1)))


class TrafficTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(make_sample_map.build())

    def test_traffic_stays_on_road_moves_and_holds_its_numbers(self):
        town, _ = simulate(self.world, PARKED, 1, traffic=20)
        p = Car(*self.world.spawn())
        on = total = 0
        speeds = []
        for i in range(60 * 40):
            town.update(1 / 60, p)
            if i % 30 == 0:
                for c in town.cars:
                    total += 1
                    on += self.world.on_road(c.x, c.y)
                    speeds.append(c.speed)
                    self.assertTrue(math.isfinite(c.x) and math.isfinite(c.y))
        self.assertGreater(on / total, 0.9)
        self.assertGreater(sum(speeds) / len(speeds), 4.0)
        self.assertAlmostEqual(len([c for c in town.cars if c.kind == "traffic"]), 20, delta=3)

    def test_traffic_keeps_to_the_right(self):
        town = Town(self.world, seed=2, traffic=24)
        p = Car(*self.world.spawn())
        score = []
        for i in range(60 * 40):
            town.update(1 / 60, p)
            if i % 20 == 0:
                for c in town.cars:
                    if abs(c.vy) < 0.8 and abs(c.vx) > 5.0:           # driving along an east-west street
                        off = c.y - round(c.y / 90.0) * 90.0           # distance from that street's centre line
                        if abs(off) < 4.0:
                            score.append(off * math.copysign(1.0, c.vx))  # east + south(+y), west + north(-y)
        self.assertGreater(len(score), 30)
        self.assertGreater(sum(score) / len(score), 0.8)

    def test_same_seed_gives_same_town(self):
        def snapshot():
            town = Town(self.world, seed=9, traffic=12)
            p = Car(*self.world.spawn())
            for _ in range(60 * 8):
                town.update(1 / 60, p)
            return [(round(c.x, 3), round(c.y, 3)) for c in town.cars]
        self.assertEqual(snapshot(), snapshot())

    def test_no_traffic_when_target_is_zero(self):
        town, _ = simulate(self.world, PARKED, 5, traffic=0)
        self.assertEqual(len(town.cars), 0)

    def test_traffic_brakes_for_a_stopped_car_ahead(self):
        car = AICar("traffic", PAL_TRAFFIC[0], 0.0, 0.0, 0.0)
        car.vx = 12.0
        blocker = Car(10.0, 0.0, 0.0)
        self.assertLess(ai.obstacle_limit(car, [car, blocker]), 8.0)
        far = Car(60.0, 0.0, 0.0)                                  # beyond the speed-scaled look-ahead
        self.assertGreater(ai.obstacle_limit(car, [car, far]), 1e8)
        beside = Car(8.0, 6.0, 0.0)
        self.assertGreater(ai.obstacle_limit(car, [car, beside]), 1e8)

    def test_traffic_sees_a_car_about_to_cross_its_path(self):
        car = AICar("traffic", PAL_TRAFFIC[0], 0.0, 0.0, 0.0)
        car.vx = 12.0
        crosser = Car(16.0, -9.0, math.pi / 2)                     # 9 m to the side, heading across our lane
        crosser.vy = 10.0
        self.assertLess(ai.obstacle_limit(car, [car, crosser]), 12.0)
        away = Car(16.0, -9.0, -math.pi / 2)                       # same spot, driving away from our lane
        away.vy = -10.0
        self.assertGreater(ai.obstacle_limit(car, [car, away]), 1e8)

    def test_quiet_roads_get_fewer_cars(self):
        world = World(make_sample_map.build())
        town = Town(world, seed=1, traffic=16)
        lone = Car(1e5, 1e5, 0.0)                                  # nowhere near a road
        self.assertEqual(town.local_target(lone), 3)


class PoliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(make_sample_map.build())

    def test_no_police_without_heat(self):
        town, _ = simulate(self.world, PARKED, 30)
        self.assertEqual(len(town.police), 0)

    def test_police_arrive_and_arrest_a_parked_player(self):
        for seed in (5, 6, 7):
            town, p = simulate(self.world, PARKED, 60, heat=2.0, seed=seed)
            self.assertEqual(town.state, "busted", f"seed {seed}")
            self.assertLess(town.damage, 30.0, f"cops rammed too hard (seed {seed})")

    def test_more_stars_means_more_police(self):
        town, _ = simulate(self.world, PARKED, 12, heat=3.5, seed=5)
        self.assertGreaterEqual(len(town.police), 3)
        self.assertLessEqual(len(town.police), 4)

    def test_police_actually_close_in_on_a_moving_player(self):
        def cruise(t, p, tw):
            return (True, False, 0.0, False) if t < 6 else (False, False, 0.0, False)
        town, p = simulate(self.world, cruise, 45, heat=2.0, seed=8)
        self.assertTrue(town.state != "playing" or any(
            math.hypot(c.x - p.x, c.y - p.y) < 30 for c in town.police))

    def test_heat_drains_when_police_lose_sight(self):
        town = Town(self.world, traffic=0)
        p = Car(*self.world.spawn())
        town._filled = True
        town.add_heat(1.0)
        town.seen = False
        for _ in range(60 * 5):
            town._update_state(1 / 60, p)
        self.assertEqual(town.heat, 1.0)                     # grace period: nothing drained yet
        for _ in range(60 * 10):
            town._update_state(1 / 60, p)
        self.assertEqual(town.heat, 0.0)

    def test_heat_holds_while_police_have_eyes_on_you(self):
        town = Town(self.world, traffic=0)
        p = Car(*self.world.spawn())
        town.add_heat(2.0)
        town.seen = True
        for _ in range(60 * 30):
            town._update_state(1 / 60, p)
        self.assertEqual(town.heat, 2.0)

    def test_hitting_traffic_adds_heat(self):
        town = Town(self.world, traffic=0)
        town._filled = True
        town._ctl_acc = town._mng_acc = -1e9                 # freeze AI decisions and spawning
        x, y, h = self.world.spawn()
        p = Car(x, y, h)
        p.vx = 15.0
        victim = AICar("traffic", PAL_TRAFFIC[2], x + 8.0, y, 0.0)
        town.cars.append(victim)
        for _ in range(60):
            px, py = p.x, p.y
            p.update(1 / 60, True, False, 0.0, False, True)
            town.update(1 / 60, p, 0.0)
        self.assertGreaterEqual(town.heat, 0.6)
        self.assertIn("hit", town.events)
        self.assertGreater(town.damage, 0.0)

    def test_hitting_a_police_car_adds_no_heat(self):
        town = Town(self.world, traffic=0)
        town._filled = True
        town._ctl_acc = town._mng_acc = -1e9
        x, y, h = self.world.spawn()
        p = Car(x, y, h)
        p.vx = 15.0
        town.cars.append(AICar("police", PAL_POLICE, x + 8.0, y, 0.0))
        for _ in range(60):
            p.update(1 / 60, True, False, 0.0, False, True)
            town.update(1 / 60, p, 0.0)
        self.assertEqual(town.heat, 0.0)

    def test_wrecked_then_reset(self):
        town = Town(self.world, traffic=0)
        town._filled = True
        p = Car(*self.world.spawn())
        town.damage = 100.0
        town.update(1 / 60, p)
        self.assertEqual(town.state, "wrecked")
        for _ in range(int((town_mod.RESET_DELAY + 0.5) * 60)):
            town.update(1 / 60, p)
        self.assertTrue(town.consume_reset())
        self.assertFalse(town.consume_reset())
        town.reset()
        self.assertEqual((town.state, town.heat, town.damage, len(town.cars)), ("playing", 0.0, 0.0, 0))

    def test_stars_follow_heat(self):
        town = Town(self.world, traffic=0)
        self.assertEqual(town.stars, 0)
        town.add_heat(0.6)
        self.assertEqual(town.stars, 1)
        town.add_heat(1.0)
        self.assertEqual(town.stars, 2)
        town.add_heat(10.0)
        self.assertEqual(town.heat, town_mod.MAX_HEAT)

    def test_clear_line_sees_through_streets_not_buildings(self):
        w = world_with_wall()
        self.assertTrue(ai.clear_line(w, 0, 100, 100, 100))
        self.assertFalse(ai.clear_line(w, 0, 0, 100, 0))

    def test_steer_to_turns_towards_the_target(self):
        car = Car(0.0, 0.0, 0.0)                              # facing east
        steer, err = ai.steer_to(car, 10.0, 10.0)             # target is south-east: to the right
        self.assertGreater(steer, 0)
        self.assertGreater(err, 0)
        steer, err = ai.steer_to(car, 10.0, -10.0)
        self.assertLess(steer, 0)

    def test_speed_control_never_reverses_a_stopped_car(self):
        car = AICar("traffic", PAL_TRAFFIC[0], 0.0, 0.0, 0.0)
        ai.speed_control(car, 0.0)
        self.assertFalse(car.brake)                           # braking at standstill would reverse
        car.vx = 10.0
        ai.speed_control(car, 0.0)
        self.assertTrue(car.brake)
        ai.speed_control(car, 20.0)
        self.assertTrue(car.throttle)


class ConverterExtraTests(unittest.TestCase):
    def test_building_height_parsing(self):
        h = osm_to_map.building_height
        self.assertEqual(h({"height": "12"}), 12.0)
        self.assertEqual(h({"height": "12.5 m"}), 12.5)
        self.assertAlmostEqual(h({"height": "40 ft"}), 12.2)
        self.assertEqual(h({"building:levels": "2"}), 7.4)
        self.assertEqual(h({"height": "6;8", "building:levels": "3"}), 10.6)   # junk height falls back to levels
        self.assertIsNone(h({"height": "tall"}))
        self.assertIsNone(h({}))
        self.assertEqual(h({"height": "900"}), 120.0)                          # clamped
        self.assertEqual(h({"height": "0.5"}), 2.5)

    def test_road_extras(self):
        e = osm_to_map.road_extras
        self.assertEqual(e({"highway": "primary", "oneway": "yes"}), {"oneway": 1})
        self.assertEqual(e({"highway": "residential", "oneway": "-1"}), {"oneway": -1})
        self.assertEqual(e({"highway": "residential", "junction": "roundabout"}), {"oneway": 1})
        self.assertEqual(e({"highway": "motorway"}), {"oneway": 1})
        self.assertEqual(e({"highway": "motorway", "oneway": "no"}), {})
        self.assertEqual(e({"highway": "primary", "bridge": "viaduct"}), {"bridge": True})
        self.assertEqual(e({"highway": "primary", "tunnel": "no"}), {})
        self.assertEqual(e({"highway": "service", "service": "driveway"}), {"service": "driveway"})

    def test_convert_carries_the_new_fields(self):
        osm = b"""<?xml version='1.0'?>
        <osm version='0.6'>
          <bounds minlat='45.80' minlon='-64.22' maxlat='45.82' maxlon='-64.20'/>
          <node id='1' lat='45.810' lon='-64.210'/><node id='2' lat='45.810' lon='-64.205'/>
          <node id='3' lat='45.811' lon='-64.205'/><node id='4' lat='45.811' lon='-64.210'/>
          <way id='10'><nd ref='1'/><nd ref='2'/><tag k='highway' v='primary'/><tag k='oneway' v='yes'/><tag k='bridge' v='yes'/></way>
          <way id='11'><nd ref='1'/><nd ref='2'/><nd ref='3'/><nd ref='4'/><nd ref='1'/>
            <tag k='building' v='yes'/><tag k='building:levels' v='4'/></way>
        </osm>"""
        data = osm_to_map.convert(io.BytesIO(osm))
        self.assertEqual(data["roads"][0]["oneway"], 1)
        self.assertTrue(data["roads"][0]["bridge"])
        self.assertEqual(data["buildings"][0]["height"], 13.8)

    def test_converted_real_style_map_builds_a_graph_and_a_town(self):
        data = make_sample_map.build()
        data["roads"][0]["oneway"] = 1
        w = World(data)
        town = Town(w, traffic=6)
        p = Car(*w.spawn())
        for _ in range(60 * 5):
            town.update(1 / 60, p)
        self.assertGreater(len(town.cars), 0)


class GameIntegrationTests(unittest.TestCase):
    def test_game_runs_headless_with_traffic_and_police(self):
        from game.main import Game
        world = World(make_sample_map.build())
        game = Game(world, 1, deterministic=True, traffic=10, seed=3)
        game.town.add_heat(2.0)
        game.run(frames=120, autodrive=True)
        self.assertGreater(len(game.town.cars), 0)

    def test_top_down_view_draws_cars(self):
        from game.main import Game
        world = World(make_sample_map.build())
        game = Game(world, 1, deterministic=True, traffic=10, seed=3)
        game.view3d = False
        game.town.add_heat(1.0)
        game.run(frames=60)


if __name__ == "__main__":
    unittest.main()
