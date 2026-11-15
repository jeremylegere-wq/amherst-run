"""Tests for the 3D renderer maths and a render smoke test.

Run from the project root:  python -m unittest discover -s tests -v
"""
import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

import make_sample_map  # noqa: E402
from game import config as C  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import Car  # noqa: E402
from game.world import World  # noqa: E402


class FakeCam:
    def __init__(self, x=0.0, y=0.0, z=2.0, yaw=0.0, pitch=0.0):
        self.x, self.y, self.z, self.yaw, self.pitch = x, y, z, yaw, pitch


def make_renderer(world=None):
    world = world or World(make_sample_map.build())
    return R.Renderer3D(world)


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.r = make_renderer()
        self.r._set_camera(FakeCam())

    def test_point_straight_ahead_is_screen_centre(self):
        sx, sy, depth = self.r.project(50, 0, 2)
        self.assertAlmostEqual(sx, C.INTERNAL_W / 2, places=3)
        self.assertAlmostEqual(sy, C.INTERNAL_H / 2, places=3)
        self.assertAlmostEqual(depth, 50, places=3)

    def test_right_of_heading_is_screen_right(self):
        # facing east, "right" is south = +y
        self.assertGreater(self.r.project(50, 10, 2)[0], C.INTERNAL_W / 2)
        self.assertLess(self.r.project(50, -10, 2)[0], C.INTERNAL_W / 2)

    def test_higher_is_up_the_screen(self):
        self.assertLess(self.r.project(50, 0, 10)[1], C.INTERNAL_H / 2)
        self.assertGreater(self.r.project(50, 0, 0)[1], C.INTERNAL_H / 2)

    def test_behind_camera_is_none(self):
        self.assertIsNone(self.r.project(-10, 0, 2))

    def test_yaw_rotates_view(self):
        self.r._set_camera(FakeCam(yaw=math.pi / 2))  # facing south (+y)
        sx, sy, _ = self.r.project(0, 50, 2)
        self.assertAlmostEqual(sx, C.INTERNAL_W / 2, places=3)

    def test_pitch_moves_horizon_up(self):
        self.r._set_camera(FakeCam(pitch=0.2))
        # a far point at camera height now sits above the screen centre line
        self.assertLess(self.r.project(500, 0, 2)[1], C.INTERNAL_H / 2)


class ClippingTests(unittest.TestCase):
    def test_polygon_behind_camera_is_dropped(self):
        r = make_renderer()
        r._set_camera(FakeCam())
        self.assertIsNone(r.project_poly([(-5, -1, 0), (-5, 1, 0), (-8, 1, 0), (-8, -1, 0)]))

    def test_polygon_crossing_near_plane_is_clipped(self):
        r = make_renderer()
        r._set_camera(FakeCam())
        # a long quad running from behind the camera to far ahead
        res = r.project_poly([(-20, -3, 0), (200, -3, 0), (200, 3, 0), (-20, 3, 0)])
        self.assertIsNotNone(res)
        scr, depth = res
        self.assertGreaterEqual(len(scr), 3)
        for x, y in scr:
            self.assertTrue(math.isfinite(x) and math.isfinite(y))
        self.assertGreater(depth, R.NEAR)


class ShadingTests(unittest.TestCase):
    def test_roof_brighter_than_shaded_wall(self):
        roof = R.shade_index(0, 0, 1)
        walls = [R.shade_index(math.cos(a), math.sin(a), 0) for a in [i * math.pi / 8 for i in range(16)]]
        self.assertEqual(roof, 3)
        self.assertLess(min(walls), roof)
        self.assertTrue(all(0 <= w <= 3 for w in walls))

    def test_fog_bands_increase_with_depth(self):
        bands = [R.Renderer3D.fog_band(d) for d in range(0, 260, 5)]
        self.assertEqual(bands[0], 0)
        self.assertEqual(bands, sorted(bands))
        self.assertEqual(bands[-1], R.FOG_BANDS - 1)

    def test_fog_colour_converges_to_fog_rgb(self):
        r = make_renderer()
        far = r.col((200, 0, 0), 3, R.FOG_BANDS - 1)
        near = r.col((200, 0, 0), 3, 0)
        self.assertEqual(near, (200, 0, 0))
        self.assertLess(sum(abs(a - b) for a, b in zip(far, R.FOG_RGB)),
                        sum(abs(a - b) for a, b in zip(near, R.FOG_RGB)))


class BuildingTests(unittest.TestCase):
    def _renderer_with_square(self, pts):
        data = make_sample_map.build()
        data["buildings"] = [{"points": pts}]
        return make_renderer(World(data))

    def test_wall_normals_point_outward_for_both_windings(self):
        ccw = [[0, 0], [10, 0], [10, 10], [0, 10]]
        for pts in (ccw, list(reversed(ccw))):
            r = self._renderer_with_square(pts)
            cx, cy, h, ci, walls, fp, rad = r.buildings[0]
            for x0, y0, x1, y1, nx, ny, sh in walls:
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                # stepping along the normal from the wall midpoint must move away from the centre
                self.assertGreater((mx - cx) * nx + (my - cy) * ny, 0)

    def test_building_heights_deterministic_and_reasonable(self):
        r = make_renderer()
        r2 = make_renderer()
        for i, b in r.buildings.items():
            self.assertEqual(b[2], r2.buildings[i][2])
            self.assertTrue(4 <= b[2] <= 17)


class CameraTests(unittest.TestCase):
    def test_chase_camera_sits_behind_and_above_car(self):
        world = World(make_sample_map.build())
        car = Car(0, 0, 0.0)
        cam = R.ChaseCamera(car, world)
        self.assertLess(cam.x, car.x)         # behind (car faces east)
        self.assertGreater(cam.z, 2.0)
        self.assertGreater(cam.pitch, 0)      # looking slightly down

    def test_camera_yaw_follows_with_lag(self):
        car = Car(0, 0, 0.0)
        cam = R.ChaseCamera(car, None)
        car.heading = 1.0
        cam.update(car, 1 / 30)
        self.assertGreater(cam.yaw, 0.0)
        self.assertLess(cam.yaw, 1.0)
        for _ in range(120):
            cam.update(car, 1 / 30)
        self.assertAlmostEqual(cam.yaw, 1.0, places=2)

    def test_camera_yaw_wraps_the_short_way(self):
        car = Car(0, 0, math.pi - 0.1)
        cam = R.ChaseCamera(car, None)
        car.heading = -math.pi + 0.1   # only 0.2 rad away across the wrap
        cam.update(car, 1 / 30)
        self.assertGreater(abs(cam.yaw), 2.9)  # did not swing the long way round


class RenderSmokeTests(unittest.TestCase):
    def test_renders_non_empty_frame_with_polys(self):
        pygame.init()
        world = World(make_sample_map.build())
        r = R.Renderer3D(world)
        x, y, h = world.spawn()
        car = Car(x, y, h)
        cam = R.ChaseCamera(car, world)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        r.render(surf, car, cam)
        self.assertGreater(r.polys, 20)
        colours = {tuple(surf.get_at((px, py)))[:3] for px in range(0, C.INTERNAL_W, 16) for py in range(0, C.INTERNAL_H, 16)}
        self.assertGreater(len(colours), 6)  # sky, ground, road, car, buildings...
        # car body colour should appear somewhere near the bottom centre
        self.assertTrue(any(tuple(surf.get_at((px, py)))[:3] == R.CAR_BODY
                            for px in range(130, 190, 2) for py in range(90, min(170, C.INTERNAL_H), 2)))

    def test_objects_are_painted_far_to_near(self):
        """Regression: the painter's sort went missing once and buildings drew through each other."""
        pygame.init()
        world = World(make_sample_map.build())
        r = R.Renderer3D(world)
        order = []
        for name in ("_draw_wall_piece", "_draw_prop", "_draw_car", "_draw_building_top"):
            orig = getattr(r, name)

            def spy(surf, obj, *rest, _orig=orig, **kw):
                dist = rest[0] if rest and isinstance(rest[0], float) else None
                if dist is not None:
                    order.append(dist)
                return _orig(surf, obj, *rest, **kw)
            setattr(r, name, spy)
        x, y, h = world.spawn()
        car = Car(x, y, h)
        r.render(pygame.Surface((C.INTERNAL_W, C.INTERNAL_H)), car, R.ChaseCamera(car, world))
        self.assertGreater(len(order), 5)
        self.assertEqual(order, sorted(order, reverse=True))

    def _ordered(self, cam, obj_xy):
        """Draw order (kinds) of one 12 m wall piece (0,0)-(12,0) facing north (-y) and one prop, camera at cam."""
        pygame.init()
        cls = type(self)
        if getattr(cls, "_order_r", None) is None:
            cls._order_r = R.Renderer3D(World(make_sample_map.build()))                      # built once for these
        r = cls._order_r
        r.cx, r.cy = cam
        piece = [0, 0, 0.0, 0.0, 12.0, 0.0, 0.0, -1.0, 0, False]
        prop = {"x": obj_xy[0], "y": obj_xy[1], "kind": "tree"}
        objs = [(math.hypot(6.0 - cam[0], 0.0 - cam[1]), 0, piece),
                (math.hypot(obj_xy[0] - cam[0], obj_xy[1] - cam[1]), 2, prop)]
        r._fix_wall_order(objs)
        objs.sort(key=lambda o: o[0], reverse=True)
        return [k for _d, k, _o in objs]

    def test_prop_in_front_of_a_wall_is_painted_after_it(self):
        # the tree (22.7 m) is further than the wall piece's middle (21.3 m) but stands in front of the wall
        self.assertEqual(self._ordered((20.0, -16.0), (3.0, -1.0)), [0, 2])

    def test_prop_behind_a_wall_is_painted_before_it(self):
        # the tree (23.6 m) is nearer than the piece's middle (24.8 m) but stands behind the wall
        self.assertEqual(self._ordered((23.0, -18.0), (9.0, 1.0)), [2, 0])

    def test_prop_beside_a_wall_keeps_its_distance_order(self):
        # off to the side (25 m, the wall's middle 21.3 m): the sight line misses the wall, so plain distance decides
        self.assertEqual(self._ordered((20.0, -16.0), (40.0, -1.0)), [2, 0])

    def test_random_views_never_crash(self):
        import random
        pygame.init()
        world = World(make_sample_map.build())
        r = R.Renderer3D(world)
        surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        rng = random.Random(3)
        for _ in range(150):
            car = Car(rng.uniform(-450, 450), rng.uniform(-450, 450), rng.uniform(0, 6.28))
            car.vx, car.vy = rng.uniform(-30, 30), rng.uniform(-30, 30)
            cam = R.ChaseCamera(car, world)
            r.render(surf, car, cam)


if __name__ == "__main__":
    unittest.main()
