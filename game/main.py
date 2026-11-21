"""Amherst Run - retro driving game: 3D chase view, top-down view, traffic and police.

Run from the project root:
    python -m game.main                      # uses data/amherst_map.json if present
    python -m game.main --map data/sample_map.json

Jobs: pull up and stop in a glowing marker - orange = parcel runs (post office), red = getaway (bank),
green = heritage tour (square/museum), blue = pay your fines (court house). Follow the arrow.

Controls: arrows/WASD drive, SPACE handbrake, V 3D/top-down view, M overview map,
C cop-free mode, F2 radar, F3 FPS + poly count, B build mode (see docs/BUILDING.md), H add a wanted star (debug), R respawn, ESC back to the start screen / quit.
The start screen offers 1 Player and 2 Player (split screen free roam, no police); --players 2 skips it.
Use --style retro for the chunky flat-shaded look.
"""
import argparse
import math
import os
import sys

import pygame

from . import __version__
from . import config as C
from . import padmap
from .car import Car, player_car
from .buildmode import BuildMode
from .collision import move_and_slide, settle_height
from .menu import Menu
from .minimap import SIZE as MAP_SIZE, Minimap, StreetTracker, is_highway, street_labels
from .missions import MissionManager
from .render3d import WEATHER, ChaseCamera, Renderer3D
from .touch import TouchControls
from .town import Town
from .train import Train
from .battle import Battle
WARM_RADIUS = 140.0     # metres around a start point whose streamed trees are planted before the first frame
from .twoplayer import TwoPlayer
from .world import World

P = C.PALETTE
RADAR_SIZE = MAP_SIZE
RADAR_RANGE = 160.0
INK = (22, 18, 40)
HUD_ORANGE = (255, 150, 30)
HUD_YELLOW = (252, 222, 48)


class Game:
    def __init__(self, world, scale, deterministic=False, traffic=16, seed=1, style="street", cops=True, trains=True, touch=False, no_joy=False, debug_input=False,
                 weather="clear"):
        pygame.init()
        self.world = world
        self.scale = scale
        self.deterministic = deterministic
        if C.FULLSCREEN and not deterministic:
            try:
                self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            except pygame.error:                      # some platforms (Pydroid) refuse the flag
                self.window = pygame.display.set_mode((0, 0))
        else:
            self.window = pygame.display.set_mode((C.INTERNAL_W * scale, C.INTERNAL_H * scale))
        pygame.display.set_caption("Amherst Run")
        self.screen = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
        self.touch = TouchControls() if touch else None
        # --- joystick / controller -------------------------------------------
        pygame.joystick.init()
        self.joy = None
        self.pads = []                                   # every real gamepad (2 player mode uses up to two)
        self.joy_names = []
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            self.joy_names.append("%s (%d axes, %d buttons)" % (j.get_name(), j.get_numaxes(), j.get_numbuttons()))
            # Only real gamepads: phones report sensors/keys as "joysticks" with no buttons and a stuck axis.
            if not no_joy and j.get_numaxes() >= 2 and j.get_numbuttons() >= 6:
                self.pads.append(j)
                if self.joy is None:
                    self.joy = j
        if self.joy is not None:
            layout = padmap.set_from(self.joy)
            self._BTN_A, self._BTN_B, self._BTN_Y = layout["a"], layout["b"], layout["y"]
            self._BTN_LB, self._BTN_RB = layout["lb"], layout["rb"]
            self._BTN_BACK, self._BTN_START, self._BTN_X = layout["back"], layout["start"], layout["x"]
            print("gamepad buttons:", layout)
        for n in self.joy_names:
            print("input device:", n, "<- USED" if self.joy and n.startswith(self.joy.get_name()) else "(ignored)")
        self.debug_input = debug_input
        self._joy_view_held = False      # edge-detect B button
        self._joy_map_held  = False      # edge-detect Y button
        self.font = pygame.font.Font(None, 16)
        self.big_font = pygame.font.Font(None, 34)
        self.style = style
        self.hud_font = pygame.font.Font(None, 30)      # chunky italic numbers for the street style
        self.hud_font.set_bold(True)
        self.hud_font.set_italic(True)
        self.tiny_font = pygame.font.Font(None, 13)
        self.small_font = pygame.font.Font(None, 15)
        self.small_font.set_bold(True)
        self.small_font.set_italic(True)
        self.shout_font = pygame.font.Font(None, 44)
        self.shout_font.set_bold(True)
        self.shout_font.set_italic(True)
        self.banner_font = pygame.font.Font(None, 30)
        self.banner_font.set_bold(True)
        self.banner_font.set_italic(True)
        self.clock = pygame.time.Clock()
        self.show_fps = True
        self.show_radar = True
        self.overview = False
        self.view3d = True
        self._seed, self._traffic, self._cops, self._trains = seed, traffic, cops, trains
        self.mode = "1p"
        self.two = None
        self.interactive = False                         # True when the start screen is in use: ESC goes back to it
        self.car = self._spawn_car()
        self.r3d = Renderer3D(world, style=style, weather=weather)
        self.cam = ChaseCamera(self.car, world)
        self.town = Town(world, seed=seed, traffic=traffic, cops=cops)
        self.missions = MissionManager(world, self.town, seed=seed)
        self.train = Train(world, seed=seed, enabled=trains)
        self.autodrive_t = 0.0
        self.minimap = Minimap(world, self.tiny_font)
        self.street = StreetTracker()
        self.build = BuildMode(world, self.r3d)

    def _spawn_car(self):
        x, y, h = self.world.spawn()
        car = player_car(0, x, y, h)
        car.z = self.world.ground(x, y)
        if hasattr(self.world, "warm_woods"):
            self.world.warm_woods(x, y, WARM_RADIUS)          # plant the trees in view now, not one area a frame
        return car

    def _respawn(self):
        self.missions.abort()
        self.town.reset()
        self.car = self._spawn_car()
        self.cam = ChaseCamera(self.car, self.world)

    def _begin(self, mode):
        """Set up a fresh game: "1p" = the full game, "2p"/"3p"/"4p" = split screen free roam (no police, no jobs)."""
        battle = mode in ("battle", "sprint")
        humans = 2 if battle else (int(mode[0]) if mode[0] in "234" else 1)
        two = humans > 1
        self.mode, self.two = mode, None
        self.town = Town(self.world, seed=self._seed, traffic=max(self._traffic, 12 + 4 * humans) if two else self._traffic,
                         cops=self._cops and not two)
        self.missions = MissionManager(self.world, self.town, seed=self._seed)
        self.train = Train(self.world, seed=self._seed, enabled=self._trains)
        self.street = StreetTracker()
        self.car = self._spawn_car()
        self.cam = ChaseCamera(self.car, self.world)
        self.view3d, self.overview = True, False
        self.r3d.set_viewport(C.INTERNAL_W, C.INTERNAL_H)
        if battle:
            self.two = Battle(self, "balloon" if mode == "battle" else "sprint", humans)
        elif two:
            self.two = TwoPlayer(self, humans)

    def menu_loop(self):
        """Show the start screen. Returns "1p", "2p" or None (quit)."""
        menu = Menu(self)
        while True:
            for e in pygame.event.get():
                r = menu.handle_event(e)
                if r:
                    return r[1] if r[0] == "choose" else None
            menu.draw(self.clock.tick(C.RENDER_FPS) / 1000.0)
            self.present()

    # --- input -------------------------------------------------------------
    # Xbox button indices (pygame; the real numbers are set from game/padmap.py): A=0 B=1 X=2 Y=3 LB=4 RB=5 Back=6 Start=7
    _BTN_A     = 0   # handbrake
    _BTN_B     = 1   # toggle 3D/top-down view
    _BTN_Y     = 3   # overview map
    _BTN_LB    = 4   # add star (debug)
    _BTN_RB    = 5   # toggle FPS
    _BTN_BACK  = 6   # quit
    _BTN_START = 7   # respawn
    _BTN_X     = 2   # cop-free mode on/off
    _AXIS_LX   = 0   # left stick horizontal (steer)
    _AXIS_LY   = 1   # left stick vertical (throttle/brake)
    _DEAD      = 0.18  # deadzone

    def _joy_axis(self, axis):
        """Return axis value with deadzone applied."""
        if self.joy is None:
            return 0.0
        try:
            v = self.joy.get_axis(axis)
        except Exception:
            return 0.0
        return v if abs(v) > self._DEAD else 0.0

    def _joy_btn(self, btn):
        if self.joy is None:
            return False
        try:
            return bool(self.joy.get_button(btn))
        except Exception:
            return False

    def _joy_hat(self):
        """D-pad as (x, y) where y is -1 up / +1 down."""
        if self.joy is None or self.joy.get_numhats() == 0:
            return 0, 0
        return self.joy.get_hat(0)

    def read_input(self, autodrive):
        if autodrive:
            self.autodrive_t += 1 / C.PHYSICS_HZ
            return True, False, 0.0, False  # straight line: deterministic smoke test
        k = pygame.key.get_pressed()

        # --- keyboard ---
        kb_throttle = bool(k[pygame.K_UP] or k[pygame.K_w])
        kb_brake    = bool(k[pygame.K_DOWN] or k[pygame.K_s])
        kb_steer    = float((k[pygame.K_RIGHT] or k[pygame.K_d]) - (k[pygame.K_LEFT] or k[pygame.K_a]))
        kb_hb       = bool(k[pygame.K_SPACE])
        kb_hop      = bool(k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT])

        # --- controller ---
        ax  = self._joy_axis(self._AXIS_LX)
        ay  = self._joy_axis(self._AXIS_LY)   # up = -1, down = +1
        hx, hy = self._joy_hat()

        # D-pad overrides analogue when pressed
        if hx != 0:
            ax = float(hx)
        if hy != 0:
            ay = float(-hy)   # hat y: +1 = up → throttle

        joy_throttle = ay < -self._DEAD
        joy_brake    = ay > self._DEAD
        joy_steer    = ax
        joy_hb       = self._joy_btn(self._BTN_A)

        throttle = kb_throttle or joy_throttle
        brake    = kb_brake    or joy_brake
        steer    = kb_steer if kb_steer != 0.0 else joy_steer
        handbrake = kb_hb or joy_hb
        bumper = kb_hop or self._joy_btn(self._BTN_LB) or self._joy_btn(self._BTN_RB)

        # --- touch screen ---
        if self.touch is not None:
            throttle = throttle or self.touch.throttle()
            brake = brake or self.touch.brake()
            handbrake = handbrake or self.touch.handbrake()
            if steer == 0.0:
                steer = self.touch.steer()
        return throttle, brake, steer, handbrake, bumper

    def _read_oneshot_buttons(self):
        """Handle controller buttons that trigger once per press (edge-detected)."""
        if self.joy is None:
            return

        # B — toggle view
        b_now = self._joy_btn(self._BTN_B)
        if b_now and not self._joy_view_held:
            self.view3d = not self.view3d
        self._joy_view_held = b_now

        # Y — overview map
        y_now = self._joy_btn(self._BTN_Y)
        if y_now and not self._joy_map_held:
            self.overview = not self.overview
        self._joy_map_held = y_now

        # LB / RB are the hop + drift-boost buttons (read in read_input)

        # Start — respawn
        if self._joy_btn(self._BTN_START):
            if not getattr(self, '_start_held', False):
                self._respawn()
        setattr(self, '_start_held', self._joy_btn(self._BTN_START))

    # --- simulation --------------------------------------------------------

    def _easter_eggs(self, world, car):
        """Hand-placed props with a "caption" (map_edits.json) say it once when you stop beside them."""
        seen = self.__dict__.setdefault("_eggs_seen", set())
        if abs(car.speed) > 2.0:
            return
        for p in world.props_near(car.x, car.y, 16.0) if hasattr(world, "props_near") else ():
            key = (p["kind"], p["x"], p["y"])
            if p.get("caption") and key not in seen and math.hypot(p["x"] - car.x, p["y"] - car.y) < 16.0:
                seen.add(key)
                self.missions._say(p["caption"], (236, 236, 244))
    def step(self, dt, inputs):
        car, world, town = self.car, self.world, self.town
        if town.state != "playing":
            inputs = (False, False, 0.0, True, False)   # arrested or wrecked: no control
        px, py = car.x, car.y
        car.power = town.player_power()
        car.update(dt, *inputs[:4], on_road=world.on_road(car.x, car.y), bumper=len(inputs) > 4 and bool(inputs[4]))
        impact = move_and_slide(car, world, px, py, thorough=True)
        settle_height(car, world, dt)
        town.update(dt, car, impact)
        self.train.update(dt)
        if self.train.active:
            hit = self.train.push_out(car)
            if hit > 3.0:
                town._hurt(hit)
            for c in town.cars:
                self.train.push_out(c)
        self.missions.update(dt, car)
        self._easter_eggs(world, car)
        self.street.update(world, car, dt)
        if town.consume_reset():
            town.reset()
            self.car = self._spawn_car()
            self.cam = ChaseCamera(self.car, world)

    # --- drawing -----------------------------------------------------------
    def draw(self):
        if self.two is not None:
            self.two.draw()
            return
        s = self.screen
        if self.view3d and not self.overview:
            self.r3d.render(s, self.car, self.cam, others=self.town.cars, t=self.town.time,
                            markers=self.missions.markers(), trains=self.train.units())
            self._draw_hud()
            return
        s.fill(P["grass"])
        if self.overview:
            x0, y0, x1, y1 = self.world.core_bounds
            zoom = min(C.INTERNAL_W / (x1 - x0), C.INTERNAL_H / (y1 - y0)) * 0.95
            camx, camy = (x0 + x1) / 2, (y0 + y1) / 2
        else:
            zoom = C.TOPDOWN_ZOOM
            camx, camy = self.car.x, self.car.y
        hw, hh = C.INTERNAL_W / 2 / zoom, C.INTERNAL_H / 2 / zoom
        vx0, vy0, vx1, vy1 = camx - hw, camy - hh, camx + hw, camy + hh

        def to_screen(p):
            return ((p[0] - camx) * zoom + C.INTERNAL_W / 2,
                    (p[1] - camy) * zoom + C.INTERNAL_H / 2)

        w = self.world
        for item in w.visible(w.water, vx0, vy0, vx1, vy1):
            pygame.draw.polygon(s, P["water"], [to_screen(p) for p in item["points"]])
        for item in w.visible(w.parks, vx0, vy0, vx1, vy1):
            pygame.draw.polygon(s, (96, 176, 80), [to_screen(p) for p in item["points"]])
        for item in w.visible(w.rails, vx0, vy0, vx1, vy1):
            pts = [to_screen(p) for p in item["points"]]
            pygame.draw.lines(s, P["rail_bed"], False, pts, max(1, int(3 * zoom)))
            pygame.draw.lines(s, P["rail"], False, pts, 1)

        roads = list(w.visible(w.roads, vx0, vy0, vx1, vy1))
        # draw edges first, then fills, so junctions merge cleanly
        for fill in (False, True):
            for r in roads:
                pts = [to_screen(p) for p in r["points"]]
                px = max(1, int(r["width"] * zoom)) if not self.overview else max(1, int(r["width"] * zoom * 1.5))
                if fill:
                    colour = (232, 188, 72) if is_highway(r) else P["road_" + r["type"]]
                    width = max(1, px - (2 if px > 4 else 0))
                else:
                    colour, width = P["road_edge"], px
                pygame.draw.lines(s, colour, False, pts, width)
                if width > 3:
                    for p in pts:
                        pygame.draw.circle(s, colour, (int(p[0]), int(p[1])), width // 2)
        if not self.overview:
            for r in roads:
                if r["type"] == "main":
                    pts = [to_screen(p) for p in r["points"]]
                    self._dashed(pts, P["road_line"])

        material_cols = {"sandstone": (204, 102, 70), "brick": (166, 70, 54), "clapboard": (226, 222, 210)}
        for b in w.visible(w.buildings, vx0, vy0, vx1, vy1):
            pts = [to_screen(p) for p in b["points"]]
            pygame.draw.polygon(s, material_cols.get(b.get("material"), P["building"]), pts)
            pygame.draw.polygon(s, P["building_edge"], pts, 1)
        if self.overview:      # name the landmarks on the whole-town map, without overlapping labels
            order = {"square": 0, "courthouse": 1, "civic": 2, "church": 3}
            items = [i for i in list(w.parks) + list(w.buildings) if i.get("label")]
            items.sort(key=lambda i: order.get(i.get("landmark"), 9))
            taken = [pygame.Rect(C.INTERNAL_W - RADAR_SIZE - 8, 0, RADAR_SIZE + 8, RADAR_SIZE + 20)]
            for item in items:
                n = len(item["points"])
                sx, sy = to_screen((sum(p[0] for p in item["points"]) / n, sum(p[1] for p in item["points"]) / n))
                msg = item["label"]
                w_, h_ = self.tiny_font.size(msg)
                for dy in (-4, 6, -14):
                    rect = pygame.Rect(int(sx - w_ / 2), int(sy + dy), w_ + 1, h_)
                    if rect.collidelist(taken) == -1:
                        taken.append(rect)
                        self._text(msg, rect.topleft, self.tiny_font)
                        break
            for name, pos in street_labels(w, to_screen, self.tiny_font, taken, s.get_rect()):
                self._text(name, pos, self.tiny_font)

        if not self.overview:
            for p in w.props_near(camx, camy, max(hw, hh) + 5):
                sx, sy = to_screen((p["x"], p["y"]))
                if p["kind"] == "tree":
                    rad = max(2, int(p["r"] * zoom))
                    pygame.draw.circle(s, (64, 150, 60), (int(sx), int(sy)), rad)
                    pygame.draw.circle(s, (28, 60, 30), (int(sx), int(sy)), rad, 1)
                elif p["kind"] == "cenotaph":
                    pygame.draw.circle(s, (186, 186, 196), (int(sx), int(sy)), max(2, int(1.4 * zoom)))
                    pygame.draw.circle(s, (22, 18, 40), (int(sx), int(sy)), max(2, int(1.4 * zoom)), 1)
                elif p["kind"] == "lighthouse":
                    pygame.draw.circle(s, (220, 52, 48), (int(sx), int(sy)), max(2, int(1.6 * zoom)))
                    pygame.draw.circle(s, (246, 246, 242), (int(sx), int(sy)), max(1, int(0.8 * zoom)))
                elif p["kind"] != "car_block":
                    pygame.draw.circle(s, (240, 230, 160), (int(sx), int(sy)), 1)

        for c in self.town.cars + self.r3d.parked_cars():
            if vx0 - 10 < c.x < vx1 + 10 and vy0 - 10 < c.y < vy1 + 10:
                if self.overview:
                    cx, cy = to_screen((c.x, c.y))
                    pygame.draw.circle(s, (80, 120, 255) if c.kind == "police" else (230, 230, 230),
                                       (int(cx), int(cy)), 2)
                else:
                    self._draw_car_topdown(c, to_screen)
        for mk in self.missions.markers():
            mx, my = to_screen((mk["x"], mk["y"]))
            rad = max(3, int(mk["radius"] * zoom))
            pygame.draw.circle(s, mk["colour"], (int(mx), int(my)), rad, 2)
            pygame.draw.circle(s, INK, (int(mx), int(my)), rad + 1, 1)
        if self.overview:
            cx, cy = to_screen((self.car.x, self.car.y))
            pygame.draw.circle(s, P["car_nose"], (int(cx), int(cy)), 3)
        else:
            self._draw_car_topdown(self.car, to_screen)
        self._draw_hud()

    def _dashed(self, pts, colour, dash=10, gap=10):
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L < 1:
                continue
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            d = 0.0
            while d < L:
                e = min(d + dash, L)
                pygame.draw.line(self.screen, colour, (a[0] + ux * d, a[1] + uy * d),
                                 (a[0] + ux * e, a[1] + uy * e), 1)
                d = e + gap

    def _draw_car_topdown(self, car, to_screen):
        pal = car.palette
        pts = [to_screen(c) for c in car.corners()]
        pygame.draw.polygon(self.screen, pal["body"], pts)
        if getattr(car, "kind", "") == "police":
            nose = (240, 40, 40) if int(self.town.time * 6) % 2 == 0 else (70, 110, 255)
        elif car is self.car:
            nose = P["car_nose"]
        else:
            nose = pal["lower"]
        pygame.draw.line(self.screen, nose, pts[0], pts[1], 2)  # front edge
        pygame.draw.polygon(self.screen, P["building_edge"], pts, 1)

    # --- HUD ---------------------------------------------------------------
    def _text(self, msg, pos, font=None):
        font = font or self.font
        self.screen.blit(font.render(msg, False, P["hud_shadow"]), (pos[0] + 1, pos[1] + 1))
        self.screen.blit(font.render(msg, False, P["hud_text"]), pos)

    def _draw_radar(self):
        """Top right: round GTA-style minimap (F2 hides it). Always: street-name sign and the speed-limit sign."""
        if self.show_radar:
            self.minimap.draw(self.screen, (C.INTERNAL_W - MAP_SIZE - 6, 17), self.car, self.town,
                              self.missions.markers(), self.street)
        self._draw_street_sign()
        self._draw_limit_sign()
        self._draw_build_hud()

    def _draw_attribution(self):
        """Map credits, one sentence per line, bottom right (shown on the whole-town map)."""
        parts = [t.strip() for t in self.world.meta.get("attribution", "").replace(". ", ".\n").split("\n") if t.strip()]
        y = C.INTERNAL_H - 30 - 11 * (len(parts) - 1)
        for msg in parts:
            self._text(msg, (C.INTERNAL_W - self.tiny_font.size(msg)[0] - 4, y), self.tiny_font)
            y += 11

    def _draw_build_hud(self):
        if not self.build.active:
            return
        y = 4
        for i, line in enumerate(self.build.hud_lines()):
            w = self.tiny_font.size(line)[0]
            self._text(line, ((C.INTERNAL_W - w) // 2, y), self.tiny_font)
            y += 11

    def _draw_street_sign(self):
        """Green street sign at the bottom centre with the name of the street you are on."""
        name = self.street.name
        if not name:
            return
        s = self.screen
        label = self.small_font.render(name, False, (255, 255, 255))
        w, h = label.get_width() + 12, label.get_height() + 4
        x, y = (C.INTERNAL_W - w) // 2, C.INTERNAL_H - h - 3
        pygame.draw.rect(s, INK, (x - 1, y - 1, w + 2, h + 2), border_radius=3)
        pygame.draw.rect(s, (24, 118, 74), (x, y, w, h), border_radius=3)
        pygame.draw.rect(s, (240, 248, 240), (x + 1, y + 1, w - 2, h - 2), 1, border_radius=2)
        s.blit(label, (x + 6, y + 2))

    def _draw_limit_sign(self):
        """White 'MAX' speed-limit sign next to the speedometer; the number flashes red when you are over."""
        limit = self.street.limit
        if not limit:
            return
        s = self.screen
        x, y, w, h = 80, C.INTERNAL_H - 31, 19, 24
        over = self.car.speed * 3.6 > limit * 1.1 and self.town.state == "playing"
        pygame.draw.rect(s, INK, (x - 1, y - 1, w + 2, h + 2), border_radius=3)
        pygame.draw.rect(s, (250, 250, 250), (x, y, w, h), border_radius=2)
        small = self.tiny_font.render("MAX", False, INK)
        s.blit(small, small.get_rect(center=(x + w // 2, y + 5)))
        col = (222, 30, 40) if over and int(self.town.time * 4) % 2 == 0 else INK
        num = self.font.render(str(int(limit)), False, col)
        s.blit(num, num.get_rect(center=(x + w // 2, y + 16)))

    def _outlined(self, msg, font, pos, fill, k=1):
        """Text with a dark ink outline and drop shadow (sticker look)."""
        body = font.render(msg, False, fill)
        edge = font.render(msg, False, INK)
        x, y = pos
        self.screen.blit(edge, (x + k + 1, y + k + 1))
        for dx in (-k, 0, k):
            for dy in (-k, 0, k):
                if dx or dy:
                    self.screen.blit(edge, (x + dx, y + dy))
        self.screen.blit(body, pos)

    def _shout(self, msg, centre, fill, angle=7, font=None):
        """Big tilted outlined text, e.g. BUSTED!"""
        font = font or self.shout_font
        body = font.render(msg, False, fill)
        edge = font.render(msg, False, INK)
        w, h = body.get_size()
        tile = pygame.Surface((w + 8, h + 8), pygame.SRCALPHA)
        tile.blit(edge, (6, 6))
        for dx in (-2, 0, 2):
            for dy in (-2, 0, 2):
                tile.blit(edge, (4 + dx, 4 + dy))
        tile.blit(body, (4, 4))
        tile = pygame.transform.rotate(tile, angle)
        self.screen.blit(tile, (centre[0] - tile.get_width() // 2, centre[1] - tile.get_height() // 2))

    @staticmethod
    def _slant(x, y, w, h, lean=4):
        """Parallelogram leaning right, like a speed stripe."""
        return [(x + lean, y), (x + w + lean, y), (x + w, y + h), (x, y + h)]

    def _draw_hud(self):
        if self.style == "street":
            self._draw_hud_street()
        else:
            self._draw_hud_retro()
        self._draw_mission_hud()

    def _draw_mission_hud(self):
        ms, W, H = self.missions, C.INTERNAL_W, C.INTERNAL_H
        self._outlined(f"${ms.cash}", self.small_font, (8, H - 42), (130, 250, 100))
        m = ms.mission
        if m is not None and self.town.state == "playing":
            secs = max(0, int(math.ceil(m.time_left)))
            clock = f"{secs // 60}:{secs % 60:02d}"
            hot = m.time_left < 10 and int(self.town.time * 4) % 2 == 0
            w_ = self.hud_font.size(clock)[0]
            self._outlined(clock, self.hud_font, ((W - w_) // 2, 2), (255, 70, 70) if hot else HUD_ORANGE)
            obj = ms.objective()
            w_ = self.small_font.size(obj)[0]
            self._outlined(obj, self.small_font, (max(2, (W - w_) // 2), 26), (250, 250, 250))
            tgt = ms.current_target()
            if tgt:
                self._draw_arrow(tgt, m.colour)
        elif m is None:
            hint = ms.hint(self.car)
            if hint:
                w_ = self.small_font.size(hint)[0]
                self._outlined(hint, self.small_font, (max(2, (W - w_) // 2), H - 44), (250, 250, 250))
        if ms.banner and self.town.state == "playing":
            text, colour, _left = ms.banner
            self._shout(text, (W // 2, H // 2 - 34), colour, angle=5, font=self.banner_font)

    def _draw_arrow(self, tgt, colour):
        """Direction arrow under the timer: straight up means straight ahead."""
        car = self.car
        ang = math.atan2(tgt[1] - car.y, tgt[0] - car.x) - car.heading
        cx, cy = C.INTERNAL_W // 2, 52

        def pt(a, r):
            return (cx + r * math.sin(a), cy - r * math.cos(a))

        poly = [pt(ang, 11), pt(ang + 2.4, 9), pt(ang + math.pi, 3), pt(ang - 2.4, 9)]
        pygame.draw.polygon(self.screen, colour, poly)
        pygame.draw.polygon(self.screen, INK, poly, 1)
        d = math.hypot(tgt[0] - car.x, tgt[1] - car.y)
        self._outlined(f"{int(d)} m", self.small_font, (cx + 15, cy - 6), (250, 250, 250))

    def _draw_hud_retro(self):
        s, town = self.screen, self.town
        kmh = int(self.car.speed * 3.6)
        self._text(f"{kmh:3d} km/h", (6, C.INTERNAL_H - 16))
        if self.show_fps:
            extra = f"  {self.r3d.polys} polys" if self.view3d and not self.overview else ""
            self._text(f"{self.clock.get_fps():4.1f} fps{extra}  {len(town.cars)} cars", (6, 4))
        # damage bar
        bx, by = C.INTERNAL_W - 62, C.INTERNAL_H - 14
        pygame.draw.rect(s, (16, 20, 28), (bx, by, 56, 8))
        fill = int(54 * min(1.0, town.damage / 100.0))
        if fill > 0:
            pygame.draw.rect(s, (232, 60, 52) if town.damage > 66 else (232, 170, 48), (bx + 1, by + 1, fill, 6))
        pygame.draw.rect(s, (96, 108, 128), (bx, by, 56, 8), 1)
        self._text("DMG", (bx - 24, by - 1))
        # wanted stars
        flash = int(town.time * 4) % 2 == 0
        for i in range(4 if town.cops else 0):
            sx = C.INTERNAL_W - 62 + i * 14
            on = i < town.stars
            colour = ((240, 40, 40) if flash else (255, 120, 90)) if on else (60, 64, 76)
            pygame.draw.rect(s, colour, (sx, 4, 10, 8))
            pygame.draw.rect(s, (16, 20, 28), (sx, 4, 10, 8), 1)
        self._draw_radar()
        if self.overview:
            self._draw_attribution()
        if town.state != "playing":
            msg = "BUSTED!" if town.state == "busted" else "WRECKED!"
            w, h = self.big_font.size(msg)
            pos = ((C.INTERNAL_W - w) // 2, C.INTERNAL_H // 2 - 30)
            self._text(msg, pos, self.big_font)

    def _draw_hud_street(self):
        s, town = self.screen, self.town
        # speed: big orange italic number with ink outline
        kmh = int(self.car.speed * 3.6)
        num = f"{kmh:3d}"
        self._outlined(num, self.hud_font, (6, C.INTERNAL_H - 26), HUD_ORANGE)
        nx = 6 + self.hud_font.size(num)[0] + 3
        self._outlined("km/h", self.small_font, (nx, C.INTERNAL_H - 15), (250, 250, 250))
        if self.show_fps:
            extra = f"  {self.r3d.polys} polys" if self.view3d and not self.overview else ""
            self._text(f"{self.clock.get_fps():4.1f} fps{extra}  {len(town.cars)} cars", (6, 4))
        # damage: slanted bar, yellow -> orange -> red
        bx, by, bw, bh = C.INTERNAL_W - 70, C.INTERNAL_H - 15, 60, 8
        pygame.draw.polygon(s, INK, self._slant(bx - 1, by - 1, bw + 2, bh + 2))
        pygame.draw.polygon(s, (60, 58, 84), self._slant(bx, by, bw, bh))
        frac = min(1.0, town.damage / 100.0)
        if frac > 0:
            colour = HUD_YELLOW if frac < 0.4 else HUD_ORANGE if frac < 0.7 else (236, 52, 52)
            pygame.draw.polygon(s, colour, self._slant(bx, by, max(2, int(bw * frac)), bh))
        self._outlined("DMG", self.small_font, (bx - 30, by - 2), (250, 250, 250))
        # wanted level: four slanted chevrons
        flash = int(town.time * 4) % 2 == 0
        for i in range(4 if town.cops else 0):
            sx = C.INTERNAL_W - 64 + i * 14
            on = i < town.stars
            colour = ((255, 56, 72) if flash else (255, 150, 170)) if on else (60, 58, 84)
            pygame.draw.polygon(s, INK, self._slant(sx - 1, 3, 13, 10, 5))
            pygame.draw.polygon(s, colour, self._slant(sx, 4, 11, 8, 4))
        self._draw_radar()
        if self.overview:
            self._draw_attribution()
        if town.state != "playing":
            msg = "BUSTED!" if town.state == "busted" else "WRECKED!"
            self._shout(msg, (C.INTERNAL_W // 2, C.INTERNAL_H // 2 - 24),
                        HUD_YELLOW if town.state == "busted" else HUD_ORANGE)

    WEATHER_ORDER = ("clear", "overcast", "fog", "golden", "snow")
    WEATHER_NAMES = {"clear": "Clear", "overcast": "Overcast", "fog": "Coastal fog", "golden": "Golden hour",
                     "snow": "Snow"}

    def _next_weather(self):
        """F4: cycle the weather / time of day."""
        order = self.WEATHER_ORDER
        cur = self.r3d.weather
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
        self.r3d.set_weather(nxt)
        self.missions._say(self.WEATHER_NAMES.get(nxt, nxt))

    def _toggle_cops(self):
        """C key: cop-free mode on/off. A getaway in progress is cancelled when the cops go."""
        self.town.set_cops(not self.town.cops)
        m = self.missions
        if not self.town.cops and m.mission is not None and m.mission.kind == "getaway":
            m.abort()
        if True:
            m._say("Cops on" if self.town.cops else "Cop-free mode")

    def present(self):
        """Scale the 16:9 picture to fit the window (centred, never stretched), then draw touch buttons."""
        ww, wh = self.window.get_size()
        k = min(ww / C.INTERNAL_W, wh / C.INTERNAL_H)
        w, h = int(C.INTERNAL_W * k), int(C.INTERNAL_H * k)
        if (w, h) != (ww, wh):
            self.window.fill((0, 0, 0))
        pygame.transform.scale(self.screen, (w, h), self.window.subsurface(((ww - w) // 2, (wh - h) // 2, w, h)))
        if self.touch is not None:
            self.touch.draw(self.window)
        if self.debug_input:
            info = "pad=%s touch=%s pointers=%d" % (self.joy.get_name() if self.joy else "none",
                                                    sorted(self.touch.pressed) if self.touch else "off",
                                                    len(self.touch.pointers) if self.touch else 0)
            self.window.blit(self.font.render(info, True, (255, 255, 0), (0, 0, 0)), (ww // 2 - 150, wh - 18))
        pygame.display.flip()

    # --- main loop ---------------------------------------------------------
    def run(self, frames=None, screenshot=None, autodrive=False, menu=False, mode="1p"):
        """menu=True shows the start screen first (and again after ESC); otherwise `mode` starts straight away."""
        if menu:
            self.interactive = True
            while True:
                choice = self.menu_loop()
                if choice is None:
                    break
                self._begin(choice)
                if self._play() == "quit":
                    break
        else:
            if mode != "1p":
                self._begin(mode)
            self._play(frames, screenshot, autodrive)
        if screenshot:
            pygame.image.save(self.screen, screenshot)
        pygame.quit()

    def _play(self, frames=None, screenshot=None, autodrive=False):
        """The game loop. Returns "menu" (ESC with the start screen in use) or "quit"."""
        dt_fixed = 1.0 / C.PHYSICS_HZ
        leave = "menu" if self.interactive else "quit"
        acc = 0.0
        n = 0
        running = True
        result = "quit"
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running, result = False, "quit"
                elif e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, getattr(pygame, "K_AC_BACK", pygame.K_ESCAPE)):
                    running, result = False, leave
                elif self.two is not None:
                    if e.type == pygame.JOYBUTTONDOWN and e.button == self._BTN_BACK:
                        running, result = False, leave
                    elif e.type == pygame.KEYDOWN and e.key == pygame.K_F3:
                        self.show_fps = not self.show_fps
                    else:
                        self.two.handle_event(e)
                elif e.type == pygame.JOYBUTTONDOWN:
                    if e.button == self._BTN_BACK:
                        running, result = False, leave
                    elif e.button == self._BTN_X:          # X: cop-free mode on/off
                        self._toggle_cops()
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_m:
                        self.overview = not self.overview
                    elif e.key == pygame.K_v:
                        self.view3d = not self.view3d
                    elif e.key == pygame.K_F2:
                        self.show_radar = not self.show_radar
                    elif e.key == pygame.K_F3:
                        self.show_fps = not self.show_fps
                    elif e.key == pygame.K_F4:
                        self._next_weather()
                    elif e.key == pygame.K_h:
                        self.town.add_heat(1.0)
                    elif e.key == pygame.K_c:
                        self._toggle_cops()
                    elif e.key == pygame.K_r:
                        self._respawn()
                    elif e.key == pygame.K_b:
                        self.build.toggle()
                    elif self.build.active and e.key == pygame.K_LEFTBRACKET:
                        self.build.cycle(-1)
                    elif self.build.active and e.key == pygame.K_RIGHTBRACKET:
                        self.build.cycle(1)
                    elif self.build.active and e.key == pygame.K_COMMA:
                        self.build.rotate(-15.0)
                    elif self.build.active and e.key == pygame.K_PERIOD:
                        self.build.rotate(15.0)
                    elif self.build.active and e.key == pygame.K_x:
                        self.build.flip()
                    elif self.build.active and e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self.build.place(self.car)
                    elif self.build.active and e.key == pygame.K_BACKSPACE:
                        self.build.undo()
                if self.touch is not None:
                    self.touch.handle_event(e, self.window.get_size())
            if self.two is None:
                self._read_oneshot_buttons()
            if self.touch is not None and self.two is None:
                for tap in self.touch.update(self.window.get_size()):
                    if tap == "view":
                        self.view3d = not self.view3d
                    elif tap == "map":
                        self.overview = not self.overview
                    elif tap == "reset":
                        self._respawn()

            frame_dt = 1.0 / C.RENDER_FPS if self.deterministic else min(0.1, self.clock.tick(C.RENDER_FPS) / 1000.0)
            if self.deterministic:
                self.clock.tick()
            acc += frame_dt
            while acc >= dt_fixed:
                if self.two is not None:
                    self.two.step(dt_fixed, self.two.read_inputs())
                else:
                    self.step(dt_fixed, self.read_input(autodrive))
                acc -= dt_fixed
            if self.two is not None:
                self.two.update_cams(frame_dt)
            else:
                self.cam.update(self.car, frame_dt)
                self.build.update(self.car)

            self.draw()
            self.present()
            n += 1
            if frames is not None and n >= frames:
                running = False
        return result


def write_crash_log():
    """Batocera and Android hide errors, so: save the error in every place that might be writable and return it."""
    import tempfile
    import traceback
    text = "Amherst Run %s\n%s\npygame %s, python %s\n" % (__version__, traceback.format_exc(), pygame.version.ver,
                                                         sys.version)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder in (root, os.path.expanduser("~"), "/userdata/system", "/userdata", tempfile.gettempdir()):
        try:
            path = os.path.join(folder, "amherst-run-crash.log")
            with open(path, "w") as f:
                f.write(text)
            print("Crash details saved to", path)
        except OSError:
            pass
    print(text)
    return text


def show_crash(text):
    """Put the error on the screen (the Batocera screen is the only place the player can read it)."""
    try:
        if not pygame.display.get_init() or pygame.display.get_surface() is None:
            return
        scr = pygame.display.get_surface()
        font = pygame.font.Font(None, 20)
        lines = ["AMHERST RUN CRASHED - photograph this screen. Press any key or button to close.", ""]
        for raw in text.splitlines()[-24:]:
            while len(raw) > 100:
                lines.append(raw[:100])
                raw = raw[100:]
            lines.append(raw)
        scr.fill((20, 0, 0))
        for i, ln in enumerate(lines[:44]):
            scr.blit(font.render(ln, True, (255, 230, 230)), (8, 6 + i * 16))
        pygame.display.flip()
        end = pygame.time.get_ticks() + 120000
        while pygame.time.get_ticks() < end:
            for e in pygame.event.get():
                if e.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN, pygame.QUIT, pygame.MOUSEBUTTONDOWN):
                    return
            pygame.time.wait(50)
    except Exception:
        pass


def default_map():
    for p in ("data/amherst_map.json", "data/sample_map.json"):
        if os.path.exists(p):
            return p
    sys.exit("No map found. Run: python tools/make_sample_map.py data/sample_map.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", action="version", version="Amherst Run " + __version__)
    ap.add_argument("--map", default=None)
    ap.add_argument("--scale", type=int, default=C.DEFAULT_SCALE)
    ap.add_argument("--frames", type=int, default=None, help="run N frames then exit (testing)")
    ap.add_argument("--screenshot", default=None, help="save the last frame to this path")
    ap.add_argument("--autodrive", action="store_true", help="scripted driving for tests")
    ap.add_argument("--overview", action="store_true", help="start in whole-map view")
    ap.add_argument("--view", choices=("3d", "top"), default="3d", help="starting camera view")
    ap.add_argument("--traffic", type=int, default=16, help="civilian cars around you downtown (fewer on quiet roads; 0 for none)")
    ap.add_argument("--heat", type=float, default=0.0, help="start with this wanted level (0-4)")
    ap.add_argument("--no-zoning", action="store_true", help="skip the zoning-based building looks (data/zoning.json)")
    ap.add_argument("--players", type=int, choices=(1, 2, 3, 4), default=None, help="skip the start screen: 1 = the game, 2 = split screen free roam")
    ap.add_argument("--no-menu", action="store_true", help="skip the start screen (same as --players 1)")
    ap.add_argument("--vs", choices=("battle", "sprint"), default=None,
                    help="skip the start screen into 2 player battle (balloons) or a VS race to a landmark")
    ap.add_argument("--no-train", action="store_true", help="no train on the rail line")
    ap.add_argument("--weather", choices=sorted(WEATHER), default="clear",
                    help="weather / time of day: clear, overcast, fog, golden (hour) or snow (F4 cycles in game)")
    ap.add_argument("--flat", action="store_true", help="ignore data/elevation.json: flat ground, faster on slow machines")
    ap.add_argument("--no-cops", action="store_true", help="cop-free mode: no police, wanted level or busting (C toggles in game)")
    ap.add_argument("--seed", type=int, default=1, help="random seed for traffic and police")
    ap.add_argument("--style", choices=("street", "retro"), default="street",
                    help="street = cel-shaded with ink outlines (default), retro = chunky flat shading with banded fog")
    ap.add_argument("--no-joy", action="store_true", help="ignore all gamepads/joysticks")
    ap.add_argument("--debug-input", action="store_true", help="show input state on screen")
    ap.add_argument("--touch", action="store_true", help="show on-screen touch controls (automatic on Android)")
    args = ap.parse_args()
    on_android = "ANDROID_ARGUMENT" in os.environ or "ANDROID_ROOT" in os.environ

    world = World.load(args.map or default_map(), zoning=not args.no_zoning, terrain=not args.flat)
    game = Game(world, args.scale, deterministic=args.frames is not None, traffic=args.traffic,
                seed=args.seed, style=args.style, weather=args.weather, cops=not args.no_cops, trains=not args.no_train,
                touch=args.touch or on_android, no_joy=args.no_joy, debug_input=args.debug_input)
    game.overview = args.overview
    game.view3d = args.view == "3d"
    if args.heat:
        game.town.add_heat(args.heat)
    show_menu = args.players is None and args.vs is None and not args.no_menu and args.frames is None and not args.autodrive
    try:
        game.run(frames=args.frames, screenshot=args.screenshot, autodrive=args.autodrive, menu=show_menu,
                 mode=args.vs or "%dp" % (args.players or 1))
    except Exception:
        show_crash(write_crash_log())             # Batocera and Android hide errors: file + on-screen copy
        raise


if __name__ == "__main__":
    main()
