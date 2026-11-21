"""Downtown murals as flat shapes painted on a wall (game/render3d.py draws them; map_edits.json says which wall).

These are this game's own simplified panels that point at each real mural's subject and layout, not copies of the
artworks: at 320x180 a wall mural is a handful of coloured shapes anyway.

Shapes use wall coordinates: u from 0 (left edge, seen from outside) to 1 (right edge), v from 0 (bottom) to 1 (top).
  ("rect", u0, v0, u1, v1, colour)
  ("poly", [(u, v), ...], colour)
  ("disc", u, v, radius_in_v, colour)       (a circle, kept round on the wall)
  ("letters", u0, v0, u1, v1, colour, n)    (a line of n blocky letters: the title, too small to read anyway)
"""

MYSTERY = [   # "The Great Amherst Mystery" (1878-79): the poltergeist story of the Teed cottage on Princess St
    ("rect", 0.0, 0.0, 1.0, 1.0, (58, 54, 104)),                    # night-blue ground
    ("letters", 0.08, 0.86, 0.92, 0.95, (232, 206, 150), 16),       # the arched title
    ("letters", 0.10, 0.87, 0.90, 0.94, (150, 60, 50), 16),
    ("disc", 0.16, 0.66, 0.13, (250, 190, 70)),                     # left roundel: a sunburst
    ("disc", 0.16, 0.66, 0.09, (240, 120, 60)),
    ("disc", 0.83, 0.64, 0.14, (226, 168, 172)),                    # right roundel: blossoms
    ("disc", 0.78, 0.68, 0.03, (250, 250, 250)), ("disc", 0.87, 0.61, 0.03, (250, 250, 250)),
    ("disc", 0.84, 0.70, 0.025, (120, 170, 150)),
    ("disc", 0.5, 0.55, 0.22, (222, 180, 170)),                     # the large central roundel
    ("poly", [(0.36, 0.24), (0.64, 0.24), (0.6, 0.6), (0.4, 0.6)], (92, 132, 204)),   # the girl's blue dress
    ("rect", 0.29, 0.5, 0.37, 0.56, (236, 196, 170)),               # raised hands
    ("rect", 0.63, 0.5, 0.71, 0.56, (236, 196, 170)),
    ("disc", 0.5, 0.67, 0.065, (236, 196, 170)),                    # face
    ("poly", [(0.43, 0.68), (0.5, 0.75), (0.57, 0.68), (0.56, 0.72), (0.5, 0.77), (0.44, 0.72)], (82, 58, 48)),   # hair
    ("rect", 0.36, 0.02, 0.62, 0.2, (240, 222, 130)),               # the yellow cottage
    ("poly", [(0.34, 0.2), (0.49, 0.3), (0.64, 0.2)], (150, 110, 80)),
    ("rect", 0.42, 0.05, 0.47, 0.14, (110, 80, 60)), ("rect", 0.52, 0.05, 0.57, 0.14, (110, 80, 60)),
    ("rect", 0.06, 0.02, 0.14, 0.3, (150, 120, 110)),               # townsfolk standing at the bottom
    ("disc", 0.1, 0.33, 0.03, (230, 196, 170)),
    ("rect", 0.72, 0.02, 0.82, 0.32, (176, 104, 84)),
    ("disc", 0.77, 0.35, 0.035, (230, 196, 170)),
    ("rect", 0.86, 0.02, 0.95, 0.28, (112, 130, 160)),
    ("disc", 0.905, 0.31, 0.03, (230, 196, 170)),
]

HIGHLANDERS = [   # North Nova Scotia Highlanders memorial (WWII): framed panel, "lest we forget" in spirit
    ("rect", 0.0, 0.0, 1.0, 1.0, (244, 244, 240)),                  # white frame
    ("rect", 0.04, 0.12, 0.96, 0.84, (172, 204, 232)),              # winter sky
    ("rect", 0.04, 0.12, 0.96, 0.38, (226, 236, 246)),              # snow
    ("letters", 0.08, 0.88, 0.92, 0.96, (24, 24, 28), 18),          # the top line
    ("letters", 0.12, 0.03, 0.88, 0.09, (24, 24, 28), 15),          # the bottom line
    ("rect", 0.28, 0.64, 0.46, 0.76, (250, 250, 250)),              # Nova Scotia flag: white with a blue saltire
    ("poly", [(0.28, 0.64), (0.30, 0.64), (0.46, 0.76), (0.44, 0.76)], (30, 80, 170)),
    ("poly", [(0.44, 0.64), (0.46, 0.64), (0.30, 0.76), (0.28, 0.76)], (30, 80, 170)),
    ("rect", 0.27, 0.40, 0.28, 0.77, (90, 80, 70)),                 # its pole
    ("disc", 0.78, 0.70, 0.1, (40, 40, 48)),                        # the regimental badge
    ("disc", 0.78, 0.70, 0.06, (220, 220, 226)),
    ("rect", 0.40, 0.14, 0.64, 0.46, (150, 74, 54)),                # the brick drill hall and its two towers
    ("rect", 0.40, 0.46, 0.47, 0.56, (150, 74, 54)), ("rect", 0.57, 0.46, 0.64, 0.56, (150, 74, 54)),
    ("rect", 0.44, 0.24, 0.48, 0.34, (60, 60, 70)), ("rect", 0.56, 0.24, 0.60, 0.34, (60, 60, 70)),
    ("rect", 0.30, 0.12, 0.66, 0.2, (70, 82, 60)),                  # soldiers in ranks
    ("rect", 0.06, 0.12, 0.16, 0.52, (54, 76, 48)),                 # the piper
    ("rect", 0.06, 0.12, 0.16, 0.26, (120, 50, 50)),                # his kilt
    ("disc", 0.11, 0.55, 0.035, (230, 196, 170)),
    ("rect", 0.80, 0.14, 0.82, 0.42, (250, 250, 250)),              # white cross
    ("rect", 0.75, 0.32, 0.87, 0.34, (250, 250, 250)),
    ("disc", 0.74, 0.18, 0.035, (214, 40, 40)), ("disc", 0.86, 0.22, 0.035, (214, 40, 40)),   # poppies
    ("disc", 0.9, 0.15, 0.03, (214, 40, 40)), ("disc", 0.7, 0.24, 0.03, (214, 40, 40)),
]

DESIGNS = {"mystery": MYSTERY, "highlanders": HIGHLANDERS}
