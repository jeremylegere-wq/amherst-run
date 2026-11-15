"""GTA-style HUD map: a round heading-up minimap with streets, plus street-name and speed-limit helpers.

The minimap is drawn north-up into a square, rotated so the car always points up, then cut to a circle. Roads are
light ribbons with dark casings on a dark land, highways are gold, water/parks are tinted, buildings are blocks.
"""
import math

import pygame


RANGE = 120.0                  # metres from the car to the edge of the circle
SIZE = 66                      # diameter in pixels (at the 320x180 internal resolution)
INK = (22, 18, 40)

LAND = (58, 64, 82)
BLOCK = (74, 80, 100)
WATER = (86, 150, 214)
PARK = (84, 138, 98)
RAIL = (120, 124, 140)
ROAD = {                       # (casing, fill) per road class, drawn lowest first
    "lane": ((38, 42, 58), (150, 156, 176)),
    "side": ((38, 42, 58), (200, 206, 222)),
    "main": ((38, 42, 58), (250, 250, 255)),
}
HIGHWAY = ((60, 44, 18), (255, 208, 84))
OVERPASS = ((22, 18, 40), (255, 236, 150))
DEFAULT_LIMIT = {"main": 60, "side": 50, "lane": 30}
HOLD_SECONDS = 1.5             # keep showing a street name briefly when the road under the car has none


def road_limit(road):
    """Posted speed limit (km/h) of a road dict."""
    return road.get("speed") or DEFAULT_LIMIT.get(road.get("type"), 50)


def is_highway(road):
    return road.get("type") == "main" and road.get("speed", 0) >= 90


class StreetTracker:
    """Which street the car is on, and its limit. Holds the last name for a moment across unnamed bits."""

    def __init__(self):
        self.name = ""
        self.limit = None
        self.road = None
        self._since = 0.0

    def update(self, world, car, dt):
        road = world.road_at(car.x, car.y, getattr(car, "z", 0.0))
        self.road = road
        if road is not None:
            self.limit = road_limit(road)
            if road.get("name"):
                self.name, self._since = road["name"], 0.0
                return
        self._since += dt
        if self._since > HOLD_SECONDS:
            self.name = ""
            if road is None:
                self.limit = None


def rotation_degrees(heading):
    """pygame.transform.rotate angle (counter-clockwise) that turns a north-up map so `heading` points up."""
    return 90.0 + math.degrees(heading)


class Minimap:
    def __init__(self, world, font):
        self.world = world
        self.font = font
        self.side = int(math.ceil(SIZE * 1.5))
        self.base = pygame.Surface((self.side, self.side))
        self.mask = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
        pygame.draw.circle(self.mask, (255, 255, 255, 255), (SIZE // 2, SIZE // 2), SIZE // 2)
        self.k = (SIZE / 2.0 - 1.0) / RANGE
        self._ring = None

    # ------------------------------------------------------------------ map layer (north up)
    def _paint(self, car):
        s, w, k = self.base, self.world, self.k
        s.fill(LAND)
        half = self.side / 2.0 / k
        x0, y0, x1, y1 = car.x - half, car.y - half, car.x + half, car.y + half

        def sc(p):
            return ((p[0] - car.x) * k + self.side / 2.0, (p[1] - car.y) * k + self.side / 2.0)

        for item in w.visible(w.water, x0, y0, x1, y1):
            pygame.draw.polygon(s, WATER, [sc(p) for p in item["points"]])
        for item in w.visible(w.parks, x0, y0, x1, y1):
            pygame.draw.polygon(s, PARK, [sc(p) for p in item["points"]])
        for i in w.buildings_near(car.x, car.y, half):
            b = w.buildings[i]
            bx0, by0, bx1, by1 = b["bbox"]
            if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                continue
            pygame.draw.polygon(s, BLOCK, [sc(p) for p in b["points"]])
        for item in w.visible(w.rails, x0, y0, x1, y1):
            pygame.draw.lines(s, RAIL, False, [sc(p) for p in item["points"]], 1)

        roads = [r for r in w.visible(w.roads, x0, y0, x1, y1) if r.get("service") not in ("driveway", "private", "track")]
        order = {"lane": 0, "side": 1, "main": 2}
        roads.sort(key=lambda r: (1 if r.get("lift") else 0, 1 if is_highway(r) else 0, order.get(r["type"], 0)))
        for fill in (False, True):                              # all casings first so junctions merge cleanly
            for r in roads:
                pts = [sc(p) for p in r["points"]]
                if r.get("lift"):
                    casing, inner = OVERPASS
                elif is_highway(r):
                    casing, inner = HIGHWAY
                else:
                    casing, inner = ROAD.get(r["type"], ROAD["side"])
                wpx = max(1, int(round(r["width"] * k * (1.5 if r["type"] == "main" else 1.35))))
                if fill:
                    wpx = max(1, wpx - 2) if wpx > 3 else wpx
                    col = inner
                else:
                    wpx, col = wpx + (2 if wpx > 1 else 1), casing
                pygame.draw.lines(s, col, False, pts, wpx)
                if wpx > 3:                                     # round the joints on fat roads
                    for p in pts:
                        pygame.draw.circle(s, col, (int(p[0]), int(p[1])), wpx // 2)

    # ------------------------------------------------------------------ public
    def draw(self, surf, pos, car, town, markers, tracker=None):
        """Draw the minimap with its top-left corner at pos."""
        self._paint(car)
        rot = pygame.transform.rotate(self.base, rotation_degrees(car.heading))
        cx, cy = rot.get_width() // 2, rot.get_height() // 2
        disc = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
        disc.blit(rot, (0, 0), pygame.Rect(cx - SIZE // 2, cy - SIZE // 2, SIZE, SIZE))
        disc.blit(self.mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self._blips(disc, car, town, markers)
        c = SIZE // 2
        # player arrow, always pointing up
        pygame.draw.polygon(disc, INK, [(c, c - 6), (c + 5, c + 5), (c, c + 2), (c - 5, c + 5)])
        pygame.draw.polygon(disc, (255, 255, 255), [(c, c - 4), (c + 3, c + 3), (c, c + 1), (c - 3, c + 3)])
        surf.blit(disc, pos)
        centre = (pos[0] + c, pos[1] + c)
        pygame.draw.circle(surf, INK, centre, c + 1, 3)
        pygame.draw.circle(surf, (236, 238, 248), centre, c - 1, 1)
        # "N" marker rotates around the rim so you can always tell north
        a = -math.radians(rotation_degrees(car.heading)) - math.pi / 2
        nx, ny = centre[0] + math.cos(a) * (c + 1), centre[1] + math.sin(a) * (c + 1)
        label = self.font.render("N", False, (255, 255, 255))
        pygame.draw.circle(surf, (214, 52, 60), (int(nx), int(ny)), 5)
        pygame.draw.circle(surf, INK, (int(nx), int(ny)), 5, 1)
        surf.blit(label, label.get_rect(center=(int(nx), int(ny))))

    def _blips(self, disc, car, town, markers):
        c, k = SIZE // 2, self.k
        fx, fy = car.forward
        rx, ry = car.right
        flash = int(town.time * 6) % 2 == 0
        lim = SIZE / 2 - 3

        def to_disc(x, y):
            dx, dy = x - car.x, y - car.y
            return c + (dx * rx + dy * ry) * k, c - (dx * fx + dy * fy) * k

        for o in town.cars:
            sx, sy = to_disc(o.x, o.y)
            if math.hypot(sx - c, sy - c) > lim:
                continue
            if o.kind == "police":
                col = (240, 40, 40) if flash else (70, 110, 255)
                pygame.draw.circle(disc, INK, (int(sx), int(sy)), 3)
                pygame.draw.circle(disc, col, (int(sx), int(sy)), 2)
            else:
                pygame.draw.rect(disc, (120, 124, 150), (int(sx) - 1, int(sy) - 1, 2, 2))
        for mk in markers:                                      # job targets stick to the rim when far away
            sx, sy = to_disc(mk["x"], mk["y"])
            d = math.hypot(sx - c, sy - c)
            if d > lim:
                if mk["kind"] != "target":
                    continue
                sx, sy = c + (sx - c) / d * lim, c + (sy - c) / d * lim
            if mk["kind"] != "target" or flash:
                pygame.draw.circle(disc, INK, (int(sx), int(sy)), 4)
                pygame.draw.circle(disc, mk["colour"], (int(sx), int(sy)), 3)


def street_labels(world, to_screen, font, taken, bounds, max_labels=40):
    """Street names for the whole-town map: [(text, (x, y))] with no overlaps. Longest/biggest roads win."""
    best = {}
    for r in world.roads:
        name = r.get("name")
        if not name or r.get("bridge") or r.get("service") or r.get("ramp"):
            continue
        pts = r["points"]
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        rank = length * (3.0 if r["type"] == "main" else 1.0)
        if name not in best or rank > best[name][0]:
            half, run, mid = length / 2.0, 0.0, pts[0]
            for a, b in zip(pts, pts[1:]):                      # point halfway along the road
                seg = math.hypot(b[0] - a[0], b[1] - a[1])
                if run + seg >= half and seg > 0:
                    t = (half - run) / seg
                    mid = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                    break
                run += seg
            best[name] = (rank, mid)
    out = []
    for name, (_rank, mid) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        sx, sy = to_screen(mid)
        w, h = font.size(name)
        rect = pygame.Rect(int(sx - w / 2), int(sy - h / 2), w + 2, h)
        if not bounds.contains(rect) or rect.collidelist(taken) != -1:
            continue
        taken.append(rect)
        out.append((name, rect.topleft))
        if len(out) >= max_labels:
            break
    return out
