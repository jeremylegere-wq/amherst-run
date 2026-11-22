#!/usr/bin/env python3
"""Regenerate the README screenshots in docs/images (run before a release when the look has changed).

    python tools/readme_shots.py            # all of them
    python tools/readme_shots.py lidar      # just one (names below)

Every picture is the real renderer at 320x180, scaled 3x with nearest-neighbour. Street-level shots use the game's
chase camera; "raised" shots put the camera 30-55 m back and up to show roofs and towers. The LiDAR picture needs the
tile cache that tools/fetch_heights.py leaves in data/.lidar_cache (it is skipped without it).
"""
import math
import os
import subprocess
import sys
import tempfile
import types

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((320, 180))

from game import config as C  # noqa: E402
from game import render3d as R  # noqa: E402
from game.car import player_car  # noqa: E402
from game.town import Town  # noqa: E402
from game.world import World  # noqa: E402

OUT = os.path.join(ROOT, "docs", "images")
SCALE = 3
WORLD = World.load(os.path.join(ROOT, "data", "amherst_map.json"))
RENDER = {}


def renderer(style="street", weather="clear"):
    r = RENDER.setdefault(style, R.Renderer3D(WORLD, style))
    r.set_weather(weather)
    return r


def find(name):
    """Index of a building by its custom name or OSM name."""
    for i, b in enumerate(WORLD.buildings):
        tags = b.get("tags", {})
        if tags.get("custom") == name or tags.get("name") == name:
            return i
    raise KeyError(name)


def centre(i):
    pts = WORLD.buildings[i]["points"]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def street(x, y, heading_deg, traffic=26, seed=3, style="street", weather="clear", heat=0.0, seconds=4.0):
    """Chase-camera frame of the player's car at (x, y), with traffic (and police when heat > 0)."""
    car = player_car(0, x, y, math.radians(heading_deg))
    car.z = WORLD.ground(x, y)
    WORLD.warm_woods(x, y, 150.0)                            # streamed trees in view, as in the game
    town = Town(WORLD, seed=seed, traffic=traffic, cops=heat > 0)
    if heat:
        town.add_heat(heat)
    for _ in range(int(60 * seconds)):
        town.update(1 / 60, car)
    cam = R.ChaseCamera(car, WORLD)
    for _ in range(60):
        cam.update(car, 1 / 30)
    surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
    renderer(style, weather).render(surf, car, cam, others=town.cars, t=town.time)
    return surf, town


def raised(i, bearing, back=55.0, up=28.0, t=12.0):
    """Camera `back` metres from building i towards compass `bearing` and `up` metres high, looking at it."""
    tx, ty = centre(i)
    b = math.radians(bearing)
    cx, cy = tx + math.sin(b) * back, ty - math.cos(b) * back
    gz = WORLD.ground(tx, ty)
    cam = types.SimpleNamespace(x=cx, y=cy, z=gz + up, yaw=math.atan2(ty - cy, tx - cx), pitch=math.atan2(up - 8.0, back))
    car = player_car(0, cx, cy, cam.yaw)
    car.z = -100.0                                           # keep the player's car out of the picture
    surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
    renderer().render(surf, car, cam, t=t)
    return surf


def look_at(tx, ty, bearing, back, up, look_z=4.5, t=12.0):
    """Camera `back` metres from point (tx, ty) towards compass `bearing`, `up` metres high, looking at it."""
    b = math.radians(bearing)
    cx, cy = tx + math.sin(b) * back, ty - math.cos(b) * back
    gz = WORLD.ground(tx, ty)
    WORLD.warm_woods(cx, cy, 150.0)
    cam = types.SimpleNamespace(x=cx, y=cy, z=gz + up, yaw=math.atan2(ty - cy, tx - cx), pitch=math.atan2(up - look_z, back))
    car = player_car(0, cx, cy, cam.yaw)
    car.z = -100.0
    surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
    renderer().render(surf, car, cam, t=t)
    return surf


def save(name, surf, scale=SCALE):
    path = os.path.join(OUT, name + ".png")
    pygame.image.save(pygame.transform.scale(surf, (surf.get_width() * scale, surf.get_height() * scale)), path)
    print("wrote", os.path.relpath(path, ROOT))


def grid(tiles, cols):
    w, h = tiles[0].get_size()
    rows = (len(tiles) + cols - 1) // cols
    out = pygame.Surface((w * cols, h * rows))
    out.fill((16, 16, 24))
    for k, t in enumerate(tiles):
        out.blit(t, ((k % cols) * w, (k // cols) * h))
    return out


def game_frame(*args):
    """A frame from the real game loop (HUD included), via --screenshot."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "f.png")
        subprocess.run([sys.executable, "-m", "game.main", "--frames", "200", "--screenshot", path] + list(args),
                       cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return pygame.image.load(path)


# ------------------------------------------------------------------------------------------- the pictures
def shot_downtown():
    save("downtown", street(416.3, -880.9, -67)[0])


def shot_heritage():
    save("heritage", raised(find("Mrs. Pugsley's Emporium"), 200))      # the old post office (OSM keeps a shop name)


def shot_churches():
    save("churches", raised(find("First Baptist Church"), 250))


def shot_start():
    x, y, h = WORLD.spawn()
    save("start", street(x, y, math.degrees(h), traffic=0)[0])


def shot_houses():
    save("houses", street(1814.0, -1447.1, -144, traffic=6)[0])


def shot_victorian():
    save("victorian", raised(find("177 Victoria St E - turret"), 285, back=24, up=7))


def shot_greek_revival():
    save("greek_revival", raised(find("233 Victoria St E - wing"), 322, back=36, up=6))


def shot_school():
    save("school", raised(find("Hickman St school"), 234, back=38, up=10))


def shot_bank():
    save("bank", raised(find("Old Bank of Montreal"), 70, back=34, up=12))


def shot_chase():
    for seed in range(1, 25):                                # wait for a police car to be close and in front
        x, y, h = 416.3, -880.9, math.radians(-67)
        car = player_car(0, x, y, h)
        car.z = WORLD.ground(x, y)
        town = Town(WORLD, seed=seed, traffic=20)
        town.add_heat(3.0)
        for _ in range(60 * 30):
            town.update(1 / 60, car)
            ahead = [c for c in town.police if 8 < (c.x - x) * math.cos(h) + (c.y - y) * math.sin(h) < 28
                     and abs(-(c.x - x) * math.sin(h) + (c.y - y) * math.cos(h)) < 4.0]
            if ahead:
                cam = R.ChaseCamera(car, WORLD)
                for _ in range(60):
                    cam.update(car, 1 / 30)
                surf = pygame.Surface((C.INTERNAL_W, C.INTERNAL_H))
                renderer().render(surf, car, cam, others=town.cars, t=town.time)
                return save("chase", surf)
    print("chase: no police car came into view; kept the old picture")


def shot_weather():
    tiles = [street(416.3, -880.9, -67, weather=w)[0] for w in ("clear", "overcast", "fog", "golden", "snow")]
    tiles.append(street(416.3, -880.9, -67, style="retro")[0])
    save("weather", grid(tiles, 3), scale=2)


def shot_splitscreen():
    save("splitscreen", game_frame("--players", "4", "--autodrive"))


def shot_battle():
    save("battle", game_frame("--vs", "battle"))


def shot_dam():
    save("dam", look_at(4451.0, 1962.0, 262, 34, 3))


def shot_lighthouse():
    save("lighthouse", look_at(-3335.0, -3212.0, 30, 24, 3))


def shot_murals():
    # the Highlanders mural on the wall facing Ratchford and Havelock Streets; the Mystery mural on LaPlanche St
    save("murals", grid([look_at(506.8, -890.7, 116, 24, 3), look_at(400.4, -983.4, 25, 28, 3)], 2), scale=2)


def shot_parking():
    save("parking", look_at(1356.0, 1593.0, 200, 60, 16, look_z=0.0))


def shot_top():
    save("top", game_frame("--no-menu", "--view", "top", "--autodrive"))


def shot_lidar():
    """The LiDAR rooftop heights downtown with the map's building outlines on top (how heights were measured)."""
    cache = os.path.join(ROOT, "data", ".lidar_cache")
    if not os.path.isdir(cache):
        print("lidar: no data/.lidar_cache (run tools/fetch_heights.py first); skipped")
        return
    import numpy as np
    import cog
    import fetch_heights as FH
    dsm = cog.COG(FH.BASE % "dsm", cache_dir=os.path.join(cache, "dsm"))
    dtm = cog.COG(FH.BASE % "dtm", cache_dir=os.path.join(cache, "dtm"))
    cx, cy, rx, ry, s = 420.0, -870.0, 80.0, 45.0, 6
    gx, gy = np.meshgrid(np.arange(cx - rx, cx + rx, 0.5), np.arange(cy - ry, cy + ry, 0.5))
    m = WORLD.meta
    X, Y = FH.to_3979(gx.ravel(), gy.ravel() + 3.0, m["origin_lat"], m["origin_lon"])     # outlines sit ~3 m north
    hag = (dsm.sample(X, Y) - dtm.sample(X, Y)).reshape(gx.shape)
    v = np.clip(np.nan_to_num(hag), 0, 16) / 16.0
    rgb = np.stack([30 + v * 225, 30 + v * 200, 60 + v * 80], axis=-1).astype(np.uint8)
    img = pygame.transform.scale(pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2))), (int(2 * rx * s), int(2 * ry * s)))
    P = lambda x, y: ((x - cx + rx) * s, (y - cy + ry) * s)   # noqa: E731
    for b in WORLD.buildings:
        pts = [P(*p) for p in b["points"]]
        if any(0 <= q[0] <= img.get_width() and 0 <= q[1] <= img.get_height() for q in pts):
            pygame.draw.polygon(img, (90, 200, 255) if not b.get("custom") else (255, 110, 90), pts, 2)
    font = pygame.font.Font(None, 30)
    img.blit(font.render("LiDAR height above ground (bright = tall), map outlines in blue", True, (255, 255, 255)), (12, 10))
    pygame.draw.line(img, (255, 255, 255), (12, img.get_height() - 16), (12 + 20 * s, img.get_height() - 16), 4)
    img.blit(font.render("20 m", True, (255, 255, 255)), (20 + 20 * s, img.get_height() - 28))
    path = os.path.join(OUT, "lidar.png")
    pygame.image.save(img, path)
    print("wrote", os.path.relpath(path, ROOT))


SHOTS = {k[5:]: v for k, v in sorted(globals().items()) if k.startswith("shot_")}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name in (sys.argv[1:] or SHOTS):
        SHOTS[name]()
