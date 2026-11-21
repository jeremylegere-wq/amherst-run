"""Split screen for 2, 3 or 4 players: free roam, no police, no jobs, no damage. Just drive around Amherst together.

Screen layouts: 2 players = left/right halves, 3 players = player 1 gets the whole top half and players 2 and 3 share
the bottom, 4 players = four quarters. Each player has a chase camera and their own vehicle (boxy retro SUV, compact
crossover, mid-size SUV, quad cab pickup). Controls:
  * Player 1: W/A/S/D + Space (handbrake) + Left Shift (hop/drift), R respawn
  * Player 2: arrow keys + Right Ctrl or Keypad 0 (handbrake) + Right Shift (hop/drift), Backspace respawn
  * Gamepads: left stick or D-pad, A = handbrake, LB or RB = hop and drift, Start = respawn. Pads go to the LAST players
    first, so with two players and one pad it drives player 2, and the keyboard keeps player 1. With as many pads as
    players, pad 1 is player 1, and so on.
  * Hop (bumper) while steering at speed starts a power slide. Hold the bumper to charge it (blue, orange, purple
    sparks), let go for a speed boost.
"""
import math

import pygame

from . import config as C
from . import padmap
from .car import player_car
from .collision import move_and_slide, settle_height
from .minimap import StreetTracker
from .render3d import ChaseCamera

DEAD = 0.18
HALF_W = C.INTERNAL_W // 2
HALF_H = C.INTERNAL_H // 2
MAX_PLAYERS = 4
INK = (16, 20, 28)
TAGS = ((90, 170, 255), (255, 120, 90), (120, 230, 120), (240, 210, 80))   # blue, orange-red, green, gold


def pad_axis(pad, axis):
    try:
        v = pad.get_axis(axis)
    except Exception:
        return 0.0
    return v if abs(v) > DEAD else 0.0


def read_pad(pad):
    """(throttle, brake, steer, handbrake) from a gamepad: left stick or D-pad, A = handbrake."""
    ax, ay = pad_axis(pad, 0), pad_axis(pad, 1)
    try:
        if pad.get_numhats():
            hx, hy = pad.get_hat(0)
            if hx:
                ax = float(hx)
            if hy:
                ay = float(-hy)
        hb = bool(pad.get_button(padmap.BTN["a"]))
        hop = bool(pad.get_button(padmap.BTN["lb"]) or pad.get_button(padmap.BTN["rb"]))
    except Exception:
        hb = hop = False
    return ay < -DEAD, ay > DEAD, ax, hb, hop


def read_keys(k, scheme):
    """(throttle, brake, steer, handbrake, hop) for keyboard player `scheme` (0 = WASD, 1 = arrows, others none)."""
    if scheme == 0:
        return (bool(k[pygame.K_w]), bool(k[pygame.K_s]), float(k[pygame.K_d] - k[pygame.K_a]), bool(k[pygame.K_SPACE]),
                bool(k[pygame.K_LSHIFT]))
    if scheme == 1:
        return (bool(k[pygame.K_UP]), bool(k[pygame.K_DOWN]), float(k[pygame.K_RIGHT] - k[pygame.K_LEFT]),
                bool(k[pygame.K_RCTRL] or k[pygame.K_KP0]), bool(k[pygame.K_RSHIFT]))
    return False, False, 0.0, False, False


def layout(n):
    """Screen rectangles (x, y, w, h) of the players in the 320x180 picture."""
    W, H = C.INTERNAL_W, C.INTERNAL_H
    if n <= 2:
        return [(0, 0, HALF_W, H), (HALF_W, 0, HALF_W, H)][:max(n, 1)] if n == 2 else [(0, 0, W, H)]
    if n == 3:
        return [(0, 0, W, HALF_H), (0, HALF_H, HALF_W, HALF_H), (HALF_W, HALF_H, HALF_W, HALF_H)]
    return [(0, 0, HALF_W, HALF_H), (HALF_W, 0, HALF_W, HALF_H), (0, HALF_H, HALF_W, HALF_H),
            (HALF_W, HALF_H, HALF_W, HALF_H)]


class TwoPlayer:
    """The split-screen game for `players` (2-4) humans (the name is kept from when it only did two)."""

    def __init__(self, game, players=2):
        self.game = game
        self.n = max(2, min(MAX_PLAYERS, players))
        world = game.world
        self.pads = list(game.pads)
        self.rects = layout(self.n)
        self.cars = [self._spawn(i) for i in range(self.n)]
        self.cams = [ChaseCamera(c, world) for c in self.cars]
        self.streets = [StreetTracker() for _ in self.cars]
        game.town.set_cops(False)
        game.town.extra = self.cars[1:]
        game.car = self.cars[0]                     # the rest of the game (town, train) follows player 1 first
        game.cam = self.cams[0]

    # --- setup ---------------------------------------------------------------
    def _spawn(self, i):
        """Start grid: two players side by side; with 3-4 players two rows (the second row 7 m behind)."""
        x, y, h = self.game.world.spawn()
        if hasattr(self.game.world, "warm_woods"):
            self.game.world.warm_woods(x, y, 140.0)          # the trees in view are there from the first frame
        rx, ry = -math.sin(h), math.cos(h)
        if self.n == 2:
            side, back = (-2.6, 2.6)[i], 0.0
        else:
            side, back = (-1.7, 1.7)[i % 2], 7.0 * (i // 2)
        car = player_car(i, x + rx * side - math.cos(h) * back, y + ry * side - math.sin(h) * back, h)
        car.z = self.game.world.ground(car.x, car.y)
        return car

    def respawn(self, i):
        fresh = self._spawn(i)
        old = self.cars[i]
        old.x, old.y, old.heading, old.z = fresh.x, fresh.y, fresh.heading, fresh.z
        old.vx = old.vy = 0.0
        old.drift, old.charge, old.boost_t, old.hop_z, old.hop_vz = 0, 0.0, 0.0, 0.0, 0.0
        self.cams[i] = ChaseCamera(old, self.game.world)
        if i == 0:
            self.game.cam = self.cams[0]

    def pad_for(self, i):
        """Pads go to the last players first (so one pad + two players = pad drives player 2)."""
        k = min(len(self.pads), self.n)
        first = self.n - k
        if k and i >= first:
            return self.pads[i - first]
        return None

    # --- input ---------------------------------------------------------------
    def read_inputs(self):
        k = pygame.key.get_pressed()
        out = []
        for i in range(self.n):
            t, b, s, h, hop = read_keys(k, i)
            pad = self.pad_for(i)
            if pad is not None:
                pt, pb, ps, ph, phop = read_pad(pad)
                t, b, h, hop = t or pt, b or pb, h or ph, hop or phop
                if s == 0.0:
                    s = ps
            out.append((t, b, s, h, hop))
        return out

    @staticmethod
    def _pad_id(pad):
        for name in ("get_instance_id", "get_id"):               # older pygame only has get_id
            fn = getattr(pad, name, None)
            if fn is not None:
                try:
                    return fn()
                except Exception:
                    pass
        return None

    def handle_event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_r:
                self.respawn(0)
            elif e.key == pygame.K_BACKSPACE:
                self.respawn(1)
        elif e.type == pygame.JOYBUTTONDOWN and e.button == padmap.BTN["start"]:
            for i in range(self.n):
                pad = self.pad_for(i)
                ident = getattr(e, "instance_id", getattr(e, "joy", None))
                if pad is not None and self._pad_id(pad) == ident:
                    self.respawn(i)
                    break

    # --- simulation ----------------------------------------------------------
    def step(self, dt, inputs):
        g = self.game
        world, town = g.world, g.town
        for i, car in enumerate(self.cars):
            px, py = car.x, car.y
            car.power = 1.0
            inp = inputs[i]
            car.update(dt, *inp[:4], on_road=world.on_road(car.x, car.y), bumper=len(inp) > 4 and bool(inp[4]))
            move_and_slide(car, world, px, py, thorough=True)
            settle_height(car, world, dt)
        town.update(dt, self.cars[0], 0.0)
        town.damage = 0.0                                   # free roam: nothing breaks, nobody gets wrecked
        town.state = "playing"
        g.train.update(dt)
        if g.train.active:
            for car in self.cars:
                g.train.push_out(car)
            for c in town.cars:
                g.train.push_out(c)
        for i, car in enumerate(self.cars):
            self.streets[i].update(world, car, dt)

    def update_cams(self, dt):
        for car, cam in zip(self.cars, self.cams):
            cam.update(car, dt)

    # --- drawing -------------------------------------------------------------
    def draw(self):
        g = self.game
        s, r3d = g.screen, g.r3d
        trains = g.train.units()
        for i, (x, y, w, h) in enumerate(self.rects):
            sub = s.subsurface((x, y, w, h))
            r3d.set_viewport(w, h)
            others = list(g.town.cars) + [c for j, c in enumerate(self.cars) if j != i]
            r3d.render(sub, self.cars[i], self.cams[i], others=others, t=g.town.time, trains=trains)
        r3d.set_viewport(C.INTERNAL_W, C.INTERNAL_H)         # back to the full picture for everything else
        W, H = C.INTERNAL_W, C.INTERNAL_H
        if self.n == 2:
            pygame.draw.rect(s, INK, (HALF_W - 1, 0, 2, H))
        else:
            pygame.draw.rect(s, INK, (0, HALF_H - 1, W, 2))
            if self.n == 4:
                pygame.draw.rect(s, INK, (HALF_W - 1, 0, 2, H))
            else:
                pygame.draw.rect(s, INK, (HALF_W - 1, HALF_H, 2, HALF_H))
        for i in range(self.n):
            self._hud(i)
        if g.show_fps:
            g._outlined("%4.1f fps" % g.clock.get_fps(), g.tiny_font, (W // 2 - 22, H // 2 - 6 if self.n > 2 else H - 12),
                        (255, 255, 255))

    def _hud(self, i):
        g, s = self.game, self.game.screen
        x0, y0, w, h = self.rects[i]
        car = self.cars[i]
        small = h < 120
        kmh = int(car.speed * 3.6)
        font = g.small_font if small else g.hud_font
        g._outlined("%3d" % kmh, font, (x0 + 5, y0 + h - (16 if small else 26)), (255, 150, 30))
        nx = x0 + 5 + font.size("%3d" % kmh)[0] + 3
        g._outlined("km/h", g.tiny_font if small else g.small_font, (nx, y0 + h - (11 if small else 15)), (250, 250, 250))
        g._outlined("P%d" % (i + 1), g.small_font, (x0 + 5, y0 + 4), TAGS[i])
        self._boost_bar(s, car, x0 + w // 2, y0 + h - 8)
        name = self.streets[i].name
        if name:
            label = g.small_font.render(name, False, (255, 255, 255))
            lw, lh = label.get_width() + 10, label.get_height() + 4
            x, y = x0 + w - lw - 5, y0 + 4
            pygame.draw.rect(s, INK, (x - 1, y - 1, lw + 2, lh + 2), border_radius=3)
            pygame.draw.rect(s, (24, 118, 74), (x, y, lw, lh), border_radius=3)
            s.blit(label, (x + 5, y + 2))

    @staticmethod
    def _boost_bar(s, car, cx, y):
        """Three pips that fill blue, orange, purple as a power slide charges; they glow while boosting."""
        colours = ((70, 140, 255), (255, 150, 30), (190, 80, 255))
        if not car.drift and car.boost_t <= 0.0:
            return
        for k in range(3):
            r = pygame.Rect(cx - 21 + k * 15, y, 12, 5)
            lit = car.charge_level > k if car.drift else True
            pygame.draw.rect(s, INK, r.inflate(2, 2))
            pygame.draw.rect(s, colours[k] if lit else (50, 56, 76), r)
