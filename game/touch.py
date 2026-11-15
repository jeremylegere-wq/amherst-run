"""On-screen touch controls for phones/tablets (Android via Pydroid 3, or any touchscreen).

Buttons are laid out in window pixels, so they sit over the whole screen (including any black
bars beside the 16:9 game picture). Every frame the state is recomputed from where the fingers
are, so sliding a thumb from one button to another works.

Left thumb: LEFT / RIGHT.  Right thumb: GAS, BRAKE, HAND (handbrake).
Top right: VIEW (3D / top-down), MAP, RESET.
"""
import pygame

# name -> label
HELD = {"left": "<", "right": ">", "gas": "GAS", "brake": "BRAKE", "hand": "HAND"}
ONESHOT = {"view": "VIEW", "map": "MAP", "reset": "RESET"}


class TouchControls:
    def __init__(self):
        self.pointers = {}          # pointer id -> (x, y) in window pixels
        self._finger_seen = False   # once real finger events arrive, synthesised mouse events are ignored
        self.pressed = set()        # button names currently under a finger
        self._prev = set()
        self._size = None
        self.rects = {}
        self._fonts = {}

    # --- layout ------------------------------------------------------------
    def layout(self, w, h):
        if self._size == (w, h):
            return
        self._size = (w, h)
        u = h / 10.0                 # one layout unit = a tenth of the screen height
        m = 0.4 * u
        r = {}
        # left thumb: steering
        r["left"] = pygame.Rect(m, h - m - 2.8 * u, 2.8 * u, 2.8 * u)
        r["right"] = pygame.Rect(m + 3.1 * u, h - m - 2.8 * u, 2.8 * u, 2.8 * u)
        # right thumb: pedals
        gas_w = 3.0 * u
        r["gas"] = pygame.Rect(w - m - gas_w, h - m - 4.4 * u, gas_w, 4.4 * u)
        r["brake"] = pygame.Rect(w - m - gas_w - 0.3 * u - 2.4 * u, h - m - 2.4 * u, 2.4 * u, 2.4 * u)
        r["hand"] = pygame.Rect(w - m - gas_w - 0.3 * u - 2.4 * u, h - m - 2.4 * u - 0.3 * u - 1.6 * u,
                                2.4 * u, 1.6 * u)
        # top right: small system buttons
        bw, bh = 1.9 * u, 0.9 * u
        x = w - m - bw
        for name in ("reset", "map", "view"):
            r[name] = pygame.Rect(x, m, bw, bh)
            x -= bw + 0.25 * u
        self.rects = r
        self._fonts = {"big": pygame.font.Font(None, max(14, int(1.1 * u))),
                       "mid": pygame.font.Font(None, max(12, int(0.8 * u))),
                       "small": pygame.font.Font(None, max(12, int(0.55 * u)))}

    # --- events ------------------------------------------------------------
    def handle_event(self, e, window_size):
        """Feed every pygame event through here. Finger events are used when the device sends them;
        mouse events that SDL synthesises from touches are ignored so nothing is counted twice."""
        w, h = window_size
        t = e.type
        if t == getattr(pygame, "WINDOWFOCUSLOST", -1):
            self.pointers.clear()                    # never leave a button stuck when the app loses focus
        elif t in (pygame.FINGERDOWN, pygame.FINGERMOTION):
            self._finger_seen = True
            for k in [k for k in self.pointers if k[0] == "m"]:
                del self.pointers[k]
            self.pointers[("f", e.finger_id)] = (e.x * w, e.y * h)
        elif t == pygame.FINGERUP:
            self.pointers.pop(("f", e.finger_id), None)
        elif t in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            if getattr(e, "touch", False) or self._finger_seen:
                return
            if t == pygame.MOUSEBUTTONUP:
                self.pointers.pop(("m", 0), None)
            elif t == pygame.MOUSEBUTTONDOWN or (t == pygame.MOUSEMOTION and e.buttons[0]):
                self.pointers[("m", 0)] = e.pos

    def update(self, window_size):
        """Recompute pressed buttons. Returns the one-shot buttons that were just tapped."""
        self.layout(*window_size)
        now = set()
        for pos in self.pointers.values():
            for name, rect in self.rects.items():
                if rect.collidepoint(pos):
                    now.add(name)
        tapped = [n for n in ONESHOT if n in now and n not in self._prev]
        self.pressed = now
        self._prev = now
        return tapped

    # --- controls ----------------------------------------------------------
    def steer(self):
        return float(("right" in self.pressed) - ("left" in self.pressed))

    def throttle(self):
        return "gas" in self.pressed

    def brake(self):
        return "brake" in self.pressed

    def handbrake(self):
        return "hand" in self.pressed

    # --- drawing -----------------------------------------------------------
    def draw(self, surf):
        self.layout(*surf.get_size())
        for name, rect in self.rects.items():
            down = name in self.pressed
            label = HELD.get(name) or ONESHOT[name]
            shape = pygame.Surface(rect.size, pygame.SRCALPHA)
            fill = (255, 200, 40, 120) if down else (20, 20, 40, 90)
            pygame.draw.rect(shape, fill, shape.get_rect(), border_radius=int(rect.height * 0.18))
            pygame.draw.rect(shape, (255, 255, 255, 170), shape.get_rect(), width=3,
                             border_radius=int(rect.height * 0.18))
            font = self._fonts["small"] if name in ONESHOT else self._fonts["mid"] if name in ("brake", "hand") else self._fonts["big"]
            text = font.render(label, True, (255, 255, 255))
            shape.blit(text, text.get_rect(center=shape.get_rect().center))
            surf.blit(shape, rect.topleft)
