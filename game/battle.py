"""Battle and VS race: two players, split screen, item boxes. Builds on the split-screen free roam in game/twoplayer.py
(same cars, cameras and physics), so free roam itself is untouched.

Modes
  balloon   Balloon battle downtown: three balloons each, trailing behind the car. A shot, a slick or a hard ram pops
            one (then 1.5 s of safety). Last car with a balloon left wins.
  sprint    VS race: both cars start side by side at a random spot and race to a random Amherst landmark (Victoria
            Square, the Court House, the Dominion Building, the mall, the Pumping Station dam, the border lighthouse),
            marked by a tall light beacon. Items slow the rival down; first within 15 m of the beacon wins.

Controls (battle modes only; free roam keeps its own)
  Player 1: W/A/S/D drive, Space hop and drift, E or Left Shift use the item
  Player 2: arrow keys drive, Right Shift or Enter hop and drift, / or Right Ctrl use the item
  Gamepads: left stick or D-pad, LB/RB or A hop and drift, X or B use the item, Start = rematch when it is over
  Tab: split the screen top/bottom (default) or left/right.  Enter / Start after a win: rematch.

Hold the hop while steering at speed to power slide; let go for a mini-turbo (game/car.py).
"""
import math
import random

import pygame

from . import config as C
from . import items as I
from . import padmap
from . import sfx
from .car import player_car
from .twoplayer import HALF_H, HALF_W, INK, TAGS, TwoPlayer, pad_axis

BALLOONS = 3
HIT_SAFE = 1.5           # seconds of safety after losing a balloon
SPIN_TIME = 1.2
SPIN_RATE = 9.0          # rad/s while spinning out
RAM_SPEED = 11.0         # m/s closing speed for a plain ram to pop a balloon
GHOST_TIME, TURBO_TIME = 6.0, 2.0
FINISH = 15.0            # metres from the beacon that wins a sprint
ARENA = (416.0, -880.0)  # downtown, by Victoria Square
ARENA_RADIUS = 650.0
BATTLE_TRAFFIC = 8
BALLOON_COLOURS = ((90, 170, 255), (255, 120, 90), (120, 230, 120), (240, 210, 80))


def read_battle_keys(k, scheme):
    """(throttle, brake, steer, handbrake, hop, fire) for keyboard player `scheme` in battle (0 = WASD, 1 = arrows)."""
    if scheme == 0:
        return (bool(k[pygame.K_w]), bool(k[pygame.K_s]), float(k[pygame.K_d] - k[pygame.K_a]), False,
                bool(k[pygame.K_SPACE]), bool(k[pygame.K_e] or k[pygame.K_LSHIFT]))
    if scheme == 1:
        return (bool(k[pygame.K_UP]), bool(k[pygame.K_DOWN]), float(k[pygame.K_RIGHT] - k[pygame.K_LEFT]), False,
                bool(k[pygame.K_RSHIFT] or k[pygame.K_RETURN] or k[pygame.K_KP_ENTER]),
                bool(k[pygame.K_SLASH] or k[pygame.K_RCTRL]))
    return False, False, 0.0, False, False, False


def read_battle_pad(pad):
    ax, ay = pad_axis(pad, 0), pad_axis(pad, 1)
    try:
        if pad.get_numhats():
            hx, hy = pad.get_hat(0)
            ax = float(hx) if hx else ax
            ay = float(-hy) if hy else ay
        b = padmap.BTN
        hop = bool(pad.get_button(b["lb"]) or pad.get_button(b["rb"]) or pad.get_button(b["a"]))
        fire = bool(pad.get_button(b["x"]) or pad.get_button(b["b"]))
    except Exception:
        hop = fire = False
    return ay < -0.18, ay > 0.18, ax, False, hop, fire


def sprint_targets(world):
    """[(label, x, y)] of the landmarks a VS race can end at (those this map has)."""
    out = []
    for p in getattr(world, "parks", []):
        if p.get("name") == "Victoria Square":
            pts = p["points"]
            out.append(("VICTORIA SQUARE", sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts)))
    mall, mall_area = None, 1500.0
    for b in world.buildings:
        pts = b["points"]
        cx, cy = sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts)
        label = b.get("label") or b.get("tags", {}).get("name", "")
        if b.get("landmark") == "courthouse":
            out.append(("COURT HOUSE", cx, cy))
        elif "Dominion" in label or b.get("role") == "post_office":
            out.append(("DOMINION BUILDING", cx, cy))
        if b.get("zone") == "C":
            area = abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2
            if area > mall_area:
                mall, mall_area = (cx, cy), area
    if mall:
        out.append(("THE MALL", mall[0], mall[1]))
    for p in getattr(world, "props", []):
        if p["kind"] == "dam":
            out.append(("PUMPING STATION DAM", p["x"], p["y"]))
        elif p["kind"] == "lighthouse":
            out.append(("BORDER LIGHTHOUSE", p["x"], p["y"]))
    seen, uniq = set(), []
    for t in out:
        if t[0] not in seen:
            seen.add(t[0])
            uniq.append(t)
    return uniq


class Racer:
    """Battle state of one player."""

    def __init__(self):
        self.balloons = BALLOONS
        self.item = None            # held item name
        self.roulette = 0.0         # seconds of roulette left
        self.shown = None           # item shown in the roulette window right now
        self.orbit = 0              # triple pucks still circling
        self.spin = 0.0
        self.safe = 0.0
        self.ghost = 0.0
        self.fire_held = False
        self.out = False


class Battle(TwoPlayer):
    def __init__(self, game, mode="balloon", players=2, seed=None):
        self._game_ref = game                                  # _start_spots runs before TwoPlayer sets self.game
        self.mode = mode
        self.rng = random.Random(seed if seed is not None else random.randrange(1 << 30))
        self.split = "rows"                                   # top/bottom; Tab toggles left/right
        self.graph = game.town.graph
        self.target = None
        self._starts = self._start_spots(players)
        super().__init__(game, players)
        self.rects = self._layout()
        self.racers = [Racer() for _ in self.cars]
        self.base_palettes = [dict(c.palette) for c in self.cars]
        self.shots, self.slicks = [], []
        centre = self.arena if mode == "balloon" else self._race_centre()
        reach = ARENA_RADIUS if mode == "balloon" else math.hypot(self._starts[0][0] - self.target[1],
                                                                   self._starts[0][1] - self.target[2]) / 2 + 300.0
        self.boxes = I.box_sites(self.graph, centre, reach, spacing=I.BOX_SPACING if mode == "balloon" else 110.0)
        self.time = 0.0
        self.winner = None
        self.banner = ("BALLOON BATTLE!" if mode == "balloon" else "RACE TO " + self.target[0], 3.0)
        game.town.traffic_target = BATTLE_TRAFFIC

    # --- setup ---------------------------------------------------------------
    def _start_spots(self, n):
        """(x, y, heading) per player: two junctions facing each other downtown, or side by side for a race."""
        g = self.graph
        if self.mode == "balloon":
            self.arena = self._arena()
            cx, cy = self.arena
            nodes = [i for i in range(len(g.nodes)) if g.out[i]
                     and 90.0 < math.hypot(g.nodes[i][0] - cx, g.nodes[i][1] - cy) < 260.0]
            self.rng.shuffle(nodes)
            spots = []
            for i in nodes:
                x, y = g.nodes[i]
                if all(math.hypot(x - s[0], y - s[1]) > 140.0 for s in spots):
                    spots.append((x, y, math.atan2(cy - y, cx - x)))
                if len(spots) == n:
                    break
            while len(spots) < n:
                x, y, h = self.game_spawn()
                spots.append((x + 6.0 * len(spots), y, h))
            return spots
        targets = sprint_targets(self.game_world())
        if not targets:
            targets = [("THE START", *self.game_spawn()[:2])]
        self.target = self.rng.choice(targets)
        _l, tx, ty = self.target
        nodes = [i for i in range(len(g.nodes)) if g.out[i]
                 and 1200.0 < math.hypot(g.nodes[i][0] - tx, g.nodes[i][1] - ty) < 2600.0]
        if not nodes:
            nodes = [i for i in range(len(g.nodes)) if g.out[i]]
        i = self.rng.choice(nodes)
        e = g.edges[g.out[i][0]]
        h = math.atan2(e.dy, e.dx)
        x, y = g.nodes[i]
        x, y = x + e.dx * 8.0, y + e.dy * 8.0
        rx, ry = -math.sin(h), math.cos(h)
        return [(x + rx * side, y + ry * side, h) for side in (-1.6, 1.6, -1.6, 1.6)[:n]]

    def _arena(self):
        """Downtown Amherst; on another map (the sample town) the start point, wherever junctions are."""
        g = self.graph
        if any(len(g.out[n]) >= 3 and math.hypot(x - ARENA[0], y - ARENA[1]) < 300.0 for n, (x, y) in enumerate(g.nodes)):
            return ARENA
        x, y, _h = self.game_spawn()
        return (x, y)

    def game_world(self):
        return self._game_ref.world

    def game_spawn(self):
        return self._game_ref.world.spawn()

    def _race_centre(self):
        sx, sy, _h = self._starts[0]
        return ((sx + self.target[1]) / 2, (sy + self.target[2]) / 2)

    def _spawn(self, i):
        x, y, h = self._starts[i]
        car = player_car(i, x, y, h)
        car.z = self._game_ref.world.ground(x, y)
        return car

    def _layout(self):
        W, H = C.INTERNAL_W, C.INTERNAL_H
        if self.n != 2:
            return self.rects
        if self.split == "rows":
            return [(0, 0, W, HALF_H), (0, HALF_H, W, HALF_H)]
        return [(0, 0, HALF_W, H), (HALF_W, 0, HALF_W, H)]

    def rematch(self):
        """A fresh battle in place (same mode, new start spots and target)."""
        g = self.game
        fresh = Battle(g, self.mode, self.n)
        fresh.split = self.split
        fresh.rects = fresh._layout()
        g.two = fresh

    # --- input ---------------------------------------------------------------
    def read_inputs(self):
        k = pygame.key.get_pressed()
        out = []
        for i in range(self.n):
            t, b, s, h, hop, fire = read_battle_keys(k, i)
            pad = self.pad_for(i)
            if pad is not None:
                pt, pb, ps, ph, phop, pfire = read_battle_pad(pad)
                t, b, hop, fire = t or pt, b or pb, hop or phop, fire or pfire
                if s == 0.0:
                    s = ps
            out.append((t, b, s, h, hop, fire))
        return out

    def handle_event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_TAB and self.n == 2:
                self.split = "cols" if self.split == "rows" else "rows"
                self.rects = self._layout()
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.winner is not None:
                self.rematch()
        elif e.type == pygame.JOYBUTTONDOWN and e.button == padmap.BTN["start"] and self.winner is not None:
            self.rematch()

    # --- simulation ----------------------------------------------------------
    def step(self, dt, inputs):
        self.time += dt
        drive = []
        for i, (car, r) in enumerate(zip(self.cars, self.racers)):
            inp = inputs[i] if i < len(inputs) else (False, False, 0.0, False, False, False)
            if r.out or r.spin > 0.0 or self.winner is not None:
                inp = (False, r.out or self.winner is not None, 0.0, False, False, False)
            drive.append(inp)
        super().step(dt, [d[:5] for d in drive])
        for i, (car, r) in enumerate(zip(self.cars, self.racers)):
            r.safe = max(0.0, r.safe - dt)
            if r.spin > 0.0:
                r.spin = max(0.0, r.spin - dt)
                car.heading += SPIN_RATE * dt
                damp = math.exp(-2.5 * dt)
                car.vx *= damp
                car.vy *= damp
            if r.ghost > 0.0:
                r.ghost = max(0.0, r.ghost - dt)
                car.boost_t = max(car.boost_t, 0.1)
                hue = (self.time * 3.0 + i) % 1.0
                car.palette = dict(self.base_palettes[i], body=_rainbow(hue), roof=_rainbow((hue + 0.3) % 1.0))
            elif car.palette is not self.base_palettes[i]:
                car.palette = self.base_palettes[i]
            self._roulette(r, dt)
            fire = drive[i][5]
            if fire and not r.fire_held and not r.out and self.winner is None:
                self._use_item(i)
            r.fire_held = fire
        self._boxes(dt)
        self._move_shots(dt)
        self._slick_hits(dt)
        self._rams()
        self._check_win()
        if self.banner:
            text, left = self.banner
            self.banner = (text, left - dt) if left > dt else None

    def _roulette(self, r, dt):
        if r.roulette <= 0.0:
            return
        before = int(r.roulette * 12)
        r.roulette -= dt
        if int(max(0.0, r.roulette) * 12) != before:
            r.shown = I.ITEMS[(before + id(r)) % len(I.ITEMS)]
            sfx.play("tick")
        if r.roulette <= 0.0:
            r.roulette = 0.0
            r.item = I.pick_item(self.rng)
            r.shown = r.item
            if r.item == "triple":
                r.orbit = 3
            sfx.play("item")

    def _boxes(self, dt):
        for b in self.boxes:
            if not b.present:
                b.wait = max(0.0, b.wait - dt)
                continue
            for car, r in zip(self.cars, self.racers):
                if r.out or r.item or r.roulette > 0.0:
                    continue
                if (car.x - b.x) ** 2 + (car.y - b.y) ** 2 < I.BOX_REACH ** 2:
                    b.wait = I.BOX_RESPAWN
                    r.roulette = I.ROULETTE_TIME
                    break

    def _use_item(self, i):
        car, r = self.cars[i], self.racers[i]
        kind = r.item
        if kind is None:
            return
        if kind in ("puck", "seeker"):
            self.shots.append(I.fire(kind, car, i))
            sfx.play("launch")
            r.item = None
        elif kind == "triple":
            if r.orbit > 0:
                self.shots.append(I.fire("puck", car, i))
                sfx.play("launch")
                r.orbit -= 1
            if r.orbit <= 0:
                r.item = None
        elif kind == "slick":
            self.slicks.append(I.drop_slick(car, i))
            r.item = None
        elif kind == "turbo":
            car.boost_t = max(car.boost_t, TURBO_TIME)
            fx, fy = car.forward
            car.vx += fx * 4.0
            car.vy += fy * 4.0
            sfx.play("boost")
            r.item = None
        elif kind == "ghost":
            r.ghost = GHOST_TIME
            sfx.play("boost")
            r.item = None
        if r.item is None:
            r.shown = None

    def _move_shots(self, dt):
        town_cars = self.game.town.cars
        keep = []
        for s in self.shots:
            rivals = [(j, c) for j, c in enumerate(self.cars)
                      if not self.racers[j].out and (j != s.owner or s.age > I.OWNER_SAFE * 2)]
            bounces = s.bounces
            shielded = [j for j, r in enumerate(self.racers) if r.orbit and j != s.owner]
            res = I.step_shot(s, self.game.world, dt, [(j, c) for j, c in rivals if j not in shielded])
            if s.bounces > bounces:
                sfx.play("ricochet")
            if res == "gone":
                continue
            if isinstance(res, tuple):
                self._hurt(res[1], spin=True)
                continue
            blocked = False
            for j, (car, r) in enumerate(zip(self.cars, self.racers)):
                reach = I.ORBIT_RADIUS + I.ORBIT_BLOCK / 2
                if r.orbit and j != s.owner and (car.x - s.x) ** 2 + (car.y - s.y) ** 2 < reach * reach:
                    blocked = True                         # one of the circling pucks takes the hit
                    r.orbit -= 1
                    if r.orbit <= 0 and r.item == "triple":
                        r.item = r.shown = None
                    break
            if blocked or any((c.x - s.x) ** 2 + (c.y - s.y) ** 2 < 4.0 for c in town_cars):
                sfx.play("ricochet")
                continue                                  # stopped by an orbiting puck, or broke on a town car
            keep.append(s)
        self.shots = keep

    def _slick_hits(self, dt):
        keep = []
        for sl in self.slicks:
            sl.age += dt
            sl.life -= dt
            if sl.life <= 0.0:
                continue
            hit = False
            for j, car in enumerate(self.cars):
                if j == sl.owner and sl.age < I.SLICK_SAFE:
                    continue
                if (car.x - sl.x) ** 2 + (car.y - sl.y) ** 2 < I.SLICK_RADIUS ** 2 and not self.racers[j].out:
                    if self._hurt(j, spin=True):
                        hit = True
            if not hit:
                keep.append(sl)
        self.slicks = keep

    def _rams(self):
        for i in range(self.n):
            for j in range(i + 1, self.n):
                a, b = self.cars[i], self.cars[j]
                ra, rb = self.racers[i], self.racers[j]
                if ra.out or rb.out:
                    continue
                dx, dy = b.x - a.x, b.y - a.y
                d = math.hypot(dx, dy)
                if d > 3.4 or d < 1e-6:
                    continue
                ux, uy = dx / d, dy / d
                va = a.vx * ux + a.vy * uy                   # a's speed towards b
                vb = -(b.vx * ux + b.vy * uy)                # b's speed towards a
                for att, vic, v_att, v_vic, r_att in ((i, j, va, vb, ra), (j, i, vb, va, rb)):
                    car = self.cars[att]
                    strong = r_att.ghost > 0.0 or car.boost_t > 0.0
                    if v_att > v_vic and (strong or v_att + v_vic > RAM_SPEED):
                        self._hurt(vic, spin=strong)
                        break

    def _hurt(self, i, spin=False):
        """Pop one of player i's balloons (and spin them out). False if they could not be hurt right now."""
        r = self.racers[i]
        if r.ghost > 0.0 or r.safe > 0.0 or r.out:
            return False
        if spin:
            r.spin = SPIN_TIME
            sfx.play("spin")
        r.safe = HIT_SAFE
        if self.mode == "balloon":
            r.balloons -= 1
            sfx.play("pop")
            if r.balloons <= 0:
                r.out = True
        return True

    def _check_win(self):
        if self.winner is not None:
            return
        if self.mode == "balloon":
            alive = [i for i, r in enumerate(self.racers) if not r.out]
            if len(alive) <= 1:
                self.winner = alive[0] if alive else -1
        else:
            _l, tx, ty = self.target
            for i, car in enumerate(self.cars):
                if math.hypot(car.x - tx, car.y - ty) < FINISH:
                    self.winner = i
                    break
        if self.winner is not None:
            sfx.play("win")

    # --- drawing -------------------------------------------------------------
    def extras(self, viewer=None):
        """Things the renderer draws in 3D for this battle: balloons, boxes, shots, slicks, orbiting pucks. A player's
        own balloons are left out of their own view (they would hang between the camera and the car; the HUD counts
        them), the rival sees them."""
        out = []
        for i, (car, r) in enumerate(zip(self.cars, self.racers)):
            if self.mode == "balloon" and r.balloons > 0 and i != viewer and not (r.safe > 0.0 and int(self.time * 10) % 2):
                bx, by = car.forward
                for k in range(r.balloons):
                    side = (k - (r.balloons - 1) / 2) * 0.9
                    x = car.x - bx * 2.6 - by * side
                    y = car.y - by * 2.6 + bx * side
                    bob = 0.15 * math.sin(self.time * 3.0 + k)
                    out.append({"kind": "balloon", "x": x, "y": y, "z": 2.9 + bob + 0.25 * (k % 2),
                                "ax": car.x - bx * 1.6, "ay": car.y - by * 1.6, "colour": BALLOON_COLOURS[i]})
            for ox, oy in I.orbit_points(car, r.orbit, self.time):
                out.append({"kind": "puck", "x": ox, "y": oy, "colour": I.COLOURS["puck"]})
        for b in self.boxes:
            if b.present:
                out.append({"kind": "box", "x": b.x, "y": b.y, "spin": self.time * 1.6})
        for s in self.shots:
            out.append({"kind": s.kind, "x": s.x, "y": s.y, "colour": I.COLOURS[s.kind], "spin": self.time * 8})
        for sl in self.slicks:
            out.append({"kind": "slick", "x": sl.x, "y": sl.y, "r": I.SLICK_RADIUS})
        return out

    def markers(self):
        if self.mode != "sprint":
            return []
        _l, tx, ty = self.target
        return [{"x": tx, "y": ty, "radius": FINISH, "colour": (255, 220, 60)}]

    def draw(self):
        g = self.game
        s, r3d = g.screen, g.r3d
        trains = g.train.units()
        markers = self.markers()
        for i, (x, y, w, h) in enumerate(self.rects):
            extras = self.extras(viewer=i)
            sub = s.subsurface((x, y, w, h))
            r3d.set_viewport(w, h)
            others = list(g.town.cars) + [c for j, c in enumerate(self.cars) if j != i]
            r3d.render(sub, self.cars[i], self.cams[i], others=others, t=g.town.time, trains=trains,
                       markers=markers, extras=extras)
        r3d.set_viewport(C.INTERNAL_W, C.INTERNAL_H)
        W, H = C.INTERNAL_W, C.INTERNAL_H
        if self.n == 2 and self.split == "rows":
            pygame.draw.rect(s, INK, (0, HALF_H - 1, W, 2))
        elif self.n == 2:
            pygame.draw.rect(s, INK, (HALF_W - 1, 0, 2, H))
        else:
            pygame.draw.rect(s, INK, (0, HALF_H - 1, W, 2))
            pygame.draw.rect(s, INK, (HALF_W - 1, 0 if self.n == 4 else HALF_H, 2, H if self.n == 4 else HALF_H))
        for i in range(self.n):
            self._battle_hud(i)
        self._centre_text()
        if g.show_fps:
            g._outlined("%4.1f fps" % g.clock.get_fps(), g.tiny_font, (W - 50, H - 12), (255, 255, 255))

    def _centre_text(self):
        g = self.game
        W, H = C.INTERNAL_W, C.INTERNAL_H
        if self.winner is not None:
            msg = "DRAW!" if self.winner < 0 else "PLAYER %d WINS!" % (self.winner + 1)
            col = (255, 255, 255) if self.winner < 0 else TAGS[self.winner]
            surf = g.banner_font.render(msg, True, col)
            g._outlined(msg, g.banner_font, ((W - surf.get_width()) // 2, H // 2 - 14), col)
            sub = "ENTER / START: REMATCH     ESC: MENU"
            g._outlined(sub, g.tiny_font, ((W - g.tiny_font.size(sub)[0]) // 2, H // 2 + 10), (255, 255, 255))
        elif self.banner:
            text, _left = self.banner
            g._outlined(text, g.small_font, ((W - g.small_font.size(text)[0]) // 2, H // 2 - 6), (252, 222, 48))

    def _battle_hud(self, i):
        g, s = self.game, self.game.screen
        x0, y0, w, h = self.rects[i]
        car, r = self.cars[i], self.racers[i]
        # item window, top left
        box = pygame.Rect(x0 + 4, y0 + 4, 20, 20)
        pygame.draw.rect(s, INK, box.inflate(2, 2), border_radius=3)
        pygame.draw.rect(s, (40, 46, 70), box, border_radius=3)
        pygame.draw.rect(s, TAGS[i], box, 1, border_radius=3)
        shown = r.shown if r.roulette > 0.0 else r.item
        if shown:
            draw_icon(s, shown, box.center, r.orbit if shown == "triple" else 3)
            if r.roulette <= 0.0:
                g._outlined(I.NAMES[shown], g.tiny_font, (box.right + 4, box.y + 5), (255, 255, 255))
        g._outlined("P%d" % (i + 1), g.tiny_font, (x0 + 5, box.bottom + 3), TAGS[i])
        # balloons or distance, top right
        if self.mode == "balloon":
            for k in range(BALLOONS):
                cx = x0 + w - 10 - k * 11
                col = BALLOON_COLOURS[i] if k < r.balloons else (60, 64, 84)
                pygame.draw.circle(s, INK, (cx, y0 + 11), 5)
                pygame.draw.circle(s, col, (cx, y0 + 11), 4)
                pygame.draw.line(s, INK, (cx, y0 + 16), (cx, y0 + 20))
            if r.out:
                g._outlined("OUT", g.small_font, (x0 + w // 2 - 12, y0 + h // 2 - 6), (255, 90, 90))
        else:
            _l, tx, ty = self.target
            d = math.hypot(tx - car.x, ty - car.y)
            label = "%.1f km" % (d / 1000.0) if d >= 1000.0 else "%d m" % d
            g._outlined(label, g.small_font, (x0 + w - 8 - g.small_font.size(label)[0], y0 + 4), (255, 220, 60))
            cam = self.cams[i]
            ang = math.atan2(ty - car.y, tx - car.x) - cam.yaw       # 0 = straight ahead
            cx, cy = x0 + w - 18, y0 + 26
            tip = (cx + 8 * math.sin(ang), cy - 8 * math.cos(ang))
            left = (cx + 5 * math.sin(ang - 2.4), cy - 5 * math.cos(ang - 2.4))
            right = (cx + 5 * math.sin(ang + 2.4), cy - 5 * math.cos(ang + 2.4))
            pygame.draw.polygon(s, (255, 220, 60), [tip, left, right])
            pygame.draw.polygon(s, INK, [tip, left, right], 1)
        # speed, bottom left
        small = h < 120
        kmh = "%3d" % int(car.speed * 3.6)
        font = g.small_font if small else g.hud_font
        g._outlined(kmh, font, (x0 + 5, y0 + h - (16 if small else 26)), (255, 150, 30))
        self._boost_bar(s, car, x0 + w // 2, y0 + h - 8)
        # radar, bottom right: you in the middle facing up, the rival(s) and the beacon
        rad = 16
        cx, cy = x0 + w - rad - 4, y0 + h - rad - 4
        pygame.draw.circle(s, INK, (cx, cy), rad + 1)
        pygame.draw.circle(s, (30, 52, 44), (cx, cy), rad)
        scale = rad / 250.0
        yaw = self.cams[i].yaw

        def to_radar(px, py):
            dx, dy = px - car.x, py - car.y
            f = dx * math.cos(yaw) + dy * math.sin(yaw)
            rt = -dx * math.sin(yaw) + dy * math.cos(yaw)
            vx, vy = rt * scale, -f * scale
            L = math.hypot(vx, vy)
            if L > rad - 2:
                vx, vy = vx * (rad - 2) / L, vy * (rad - 2) / L
            return int(cx + vx), int(cy + vy)
        if self.mode == "sprint":
            pygame.draw.circle(s, (255, 220, 60), to_radar(self.target[1], self.target[2]), 2)
        for j, other in enumerate(self.cars):
            if j != i:
                pygame.draw.circle(s, TAGS[j], to_radar(other.x, other.y), 2)
        pygame.draw.polygon(s, TAGS[i], [(cx, cy - 3), (cx - 2, cy + 2), (cx + 2, cy + 2)])


def _rainbow(h):
    """A saturated colour around the colour wheel (h in 0..1)."""
    k = h * 6.0
    i, f = int(k) % 6, k - int(k)
    q, t = int(255 * (1 - f)), int(255 * f)
    return ((255, t, 0), (q, 255, 0), (0, 255, t), (0, q, 255), (t, 0, 255), (255, 0, q))[i]


def draw_icon(s, kind, centre, count=3):
    """The item's picture in the HUD window (16 px)."""
    x, y = centre
    col = I.COLOURS[kind]
    if kind == "puck":
        pygame.draw.ellipse(s, INK, (x - 7, y - 4, 14, 9))
        pygame.draw.ellipse(s, col, (x - 6, y - 3, 12, 7))
    elif kind == "seeker":
        pygame.draw.circle(s, INK, (x, y), 7)
        pygame.draw.circle(s, col, (x, y), 6)
        pygame.draw.circle(s, (255, 255, 255), (x, y), 3, 1)
    elif kind == "slick":
        pygame.draw.ellipse(s, (120, 110, 150), (x - 8, y - 4, 16, 9))
        pygame.draw.ellipse(s, col, (x - 7, y - 3, 14, 7))
    elif kind == "turbo":
        pygame.draw.rect(s, INK, (x - 4, y - 7, 9, 14))
        pygame.draw.rect(s, col, (x - 3, y - 6, 7, 12))
        pygame.draw.rect(s, (255, 255, 255), (x - 3, y - 2, 7, 3))
    elif kind == "ghost":
        pygame.draw.circle(s, INK, (x, y - 1), 7)
        pygame.draw.circle(s, col, (x, y - 1), 6)
        pygame.draw.rect(s, col, (x - 6, y, 12, 6))
        for k in range(3):
            pygame.draw.circle(s, (40, 46, 70), (x - 4 + k * 4, y + 6), 2)
        pygame.draw.circle(s, INK, (x - 2, y - 2), 1)
        pygame.draw.circle(s, INK, (x + 2, y - 2), 1)
    elif kind == "triple":
        for k in range(max(1, count)):
            a = k * 2 * math.pi / 3 - math.pi / 2
            px, py = int(x + 5 * math.cos(a)), int(y + 5 * math.sin(a))
            pygame.draw.circle(s, INK, (px, py), 4)
            pygame.draw.circle(s, col, (px, py), 3)
