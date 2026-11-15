"""Start screen: pick 1 Player (the full game) or 2, 3 or 4 Player (split screen, free roam, no police).

The picture behind the menu is the real town seen from a slowly turning camera above Victoria Square.
Keyboard (arrows/WASD + Enter/Space), gamepad (D-pad or stick + A/Start) and mouse or touch all work.
"""
import math

import pygame

from . import config as C
from . import padmap
from .car import Car

OPTIONS = (
    ("1 PLAYER", "1p", "The full game: jobs, police, traffic and the train"),
    ("2 PLAYER", "2p", "Split screen free roam. No police at all"),
    ("3 PLAYER", "3p", "Player 1 gets the top half, 2 and 3 share the bottom"),
    ("4 PLAYER", "4p", "Four way split screen. Bumpers hop and drift for a boost"),
    ("QUIT", None, ""),
)
YELLOW = (252, 222, 48)
ORANGE = (255, 150, 30)
INK = (16, 20, 28)
WHITE = (250, 250, 250)


class _Cam:
    def __init__(self):
        self.x = self.y = 0.0
        self.z = 14.0
        self.yaw = 0.0
        self.pitch = 0.18


def rect_of(index, count=len(OPTIONS)):
    """Clickable rectangle of option `index` in the 320x180 picture."""
    return pygame.Rect(70, 62 + index * 17, 180, 15)


class Menu:
    def __init__(self, game):
        self.game = game
        self.index = 0
        self.t = 0.0
        self._held = set()                       # controller directions already used (edge detection)

    # --- input ---------------------------------------------------------------
    def move(self, step):
        self.index = (self.index + step) % len(OPTIONS)

    def handle_event(self, e):
        """Returns ("choose", mode) / ("quit",) / None for one pygame event."""
        if e.type == pygame.QUIT:
            return ("quit",)
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_ESCAPE, getattr(pygame, "K_AC_BACK", pygame.K_ESCAPE)):
                return ("quit",)
            if e.key in (pygame.K_UP, pygame.K_w):
                self.move(-1)
            elif e.key in (pygame.K_DOWN, pygame.K_s):
                self.move(1)
            elif e.key in (pygame.K_1, pygame.K_KP1):
                return ("choose", "1p")
            elif e.key in (pygame.K_2, pygame.K_KP2):
                return ("choose", "2p")
            elif e.key in (pygame.K_3, pygame.K_KP3):
                return ("choose", "3p")
            elif e.key in (pygame.K_4, pygame.K_KP4):
                return ("choose", "4p")
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                return self.choose()
        elif e.type == pygame.JOYBUTTONDOWN:
            if e.button in (padmap.BTN["a"], padmap.BTN["start"]):
                return self.choose()
            if e.button in (padmap.BTN["b"], padmap.BTN["back"]):          # B or Back
                return ("quit",)
        elif e.type == pygame.JOYHATMOTION:
            if e.value[1] > 0:
                self.move(-1)
            elif e.value[1] < 0:
                self.move(1)
        elif e.type == pygame.JOYAXISMOTION and e.axis == 1:
            key = "up" if e.value < -0.6 else "down" if e.value > 0.6 else None
            if key is None:
                self._held.clear()
            elif key not in self._held:
                self._held = {key}
                self.move(-1 if key == "up" else 1)
        elif e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, getattr(pygame, "FINGERDOWN", -1)):
            pos = self._to_picture(e)
            if pos is not None:
                for i in range(len(OPTIONS)):
                    if rect_of(i).collidepoint(pos):
                        self.index = i
                        if e.type != pygame.MOUSEMOTION:
                            return self.choose()
        return None

    def choose(self):
        mode = OPTIONS[self.index][1]
        return ("choose", mode) if mode else ("quit",)

    def _to_picture(self, e):
        """Window position of a mouse/touch event -> position in the 320x180 picture (None if outside)."""
        ww, wh = self.game.window.get_size()
        if e.type == getattr(pygame, "FINGERDOWN", -1):
            px, py = e.x * ww, e.y * wh
        else:
            px, py = e.pos
        k = min(ww / C.INTERNAL_W, wh / C.INTERNAL_H)
        ox, oy = (ww - C.INTERNAL_W * k) / 2, (wh - C.INTERNAL_H * k) / 2
        x, y = (px - ox) / k, (py - oy) / k
        return (x, y) if 0 <= x < C.INTERNAL_W and 0 <= y < C.INTERNAL_H else None

    # --- drawing -------------------------------------------------------------
    def draw(self, dt):
        g = self.game
        self.t += dt
        s = g.screen
        r3d = g.r3d
        r3d.set_viewport(C.INTERNAL_W, C.INTERNAL_H)
        cam = _Cam()
        x, y, _h = g.world.spawn()
        ang = self.t * 0.12
        cam.x, cam.y = x + math.cos(ang) * 70.0, y + math.sin(ang) * 70.0
        cam.z = g.world.ground(cam.x, cam.y) + 26.0
        cam.pitch = 0.3
        cam.yaw = ang + math.pi                                     # look at the square
        prop = Car(cam.x - math.cos(cam.yaw) * 400.0, cam.y - math.sin(cam.yaw) * 400.0, 0.0)    # parked far behind the camera
        r3d.render(s, prop, cam, others=(), t=self.t, trains=g.train.units())
        shade = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H), pygame.SRCALPHA)
        shade.fill((10, 16, 40, 90))
        s.blit(shade, (0, 0))
        self._title(s)
        for i, (label, _mode, _help) in enumerate(OPTIONS):
            self._option(s, i, label, i == self.index)
        hint = OPTIONS[self.index][2]
        if hint:
            self._text(s, g.small_font, hint, (C.INTERNAL_W // 2, 154), WHITE, centre=True)
        n = len(g.pads)
        if n >= 2:
            line = "%d gamepads found. LB/RB = hop + drift boost" % n
        elif n == 1:
            line = "1 gamepad found: it drives the LAST player (keyboard: WASD + arrows)"
        else:
            line = "No gamepad: P1 WASD+Shift, P2 arrows+RShift"
        self._text(s, g.tiny_font, line, (C.INTERNAL_W // 2, 165), (210, 220, 240), centre=True)
        self._text(s, g.tiny_font, "Map data (c) OpenStreetMap contributors", (C.INTERNAL_W // 2, 173),
                   (180, 190, 210), centre=True)

    def _title(self, s):
        g = self.game
        self._text(s, g.shout_font, "AMHERST RUN", (C.INTERNAL_W // 2, 22), YELLOW, centre=True, outline=INK)
        self._text(s, g.small_font, "Amherst, Nova Scotia", (C.INTERNAL_W // 2, 46), WHITE, centre=True)

    def _option(self, s, i, label, selected):
        g = self.game
        r = rect_of(i)
        if selected:
            pygame.draw.rect(s, INK, r.inflate(4, 4))
            pygame.draw.rect(s, ORANGE, r)
            self._text(s, g.small_font, label, r.center, INK, centre=True)
            blink = int(self.t * 3) % 2 == 0
            if blink:
                pygame.draw.polygon(s, YELLOW, [(r.left - 12, r.centery - 5), (r.left - 12, r.centery + 5), (r.left - 4, r.centery)])
        else:
            pygame.draw.rect(s, (30, 36, 60), r)
            pygame.draw.rect(s, (96, 108, 140), r, 1)
            self._text(s, g.small_font, label, r.center, (200, 208, 230), centre=True)

    @staticmethod
    def _text(s, font, msg, pos, colour, centre=False, outline=None):
        img = font.render(msg, False, colour)
        rect = img.get_rect()
        if centre:
            rect.center = pos
        else:
            rect.topleft = pos
        if outline is not None:
            edge = font.render(msg, False, outline)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                s.blit(edge, rect.move(dx, dy))
        s.blit(img, rect)
