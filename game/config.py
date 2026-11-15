"""Global constants for Amherst Run."""

# Internal render resolution (scaled up with nearest-neighbour to the window)
INTERNAL_W = 320
INTERNAL_H = 180         # 16:9
DEFAULT_SCALE = 3
FULLSCREEN = True        # scale to fill the display; ignores DEFAULT_SCALE when True

RENDER_FPS = 30
PHYSICS_HZ = 60

ATTRIBUTION = "Map data (c) OpenStreetMap contributors"

# Small, fixed palette for the retro look (RGB)
PALETTE = {
    "grass":      (60, 110, 56),
    "grass_dark": (50, 96, 48),
    "water":      (52, 92, 168),
    "rail_bed":   (96, 80, 64),
    "rail":       (200, 196, 188),
    "road_main":  (88, 88, 96),
    "road_side":  (112, 112, 120),
    "road_lane":  (140, 132, 120),
    "road_edge":  (40, 40, 48),
    "road_line":  (232, 208, 72),
    "building":   (176, 84, 68),
    "building_roof": (204, 116, 92),
    "building_edge": (84, 36, 36),
    "car_body":   (244, 220, 60),
    "car_nose":   (232, 60, 52),
    "hud_text":   (248, 248, 248),
    "hud_shadow": (16, 16, 24),
}

# Pixels per metre in the follow-camera top-down view
TOPDOWN_ZOOM = 2.0
