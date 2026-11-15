"""Turn the Town of Amherst zoning map (PDF) into data/zoning.json: a coarse grid of zone codes in game metres.

Usage (offline tool; needs numpy + pygame only, plus poppler's pdftoppm to rasterise the PDF):

    python tools/zoning_from_pdf.py ZONING.pdf            # rasterises at 400 dpi, writes data/zoning.json
    python tools/zoning_from_pdf.py page.png              # or give an already rasterised 400 dpi PNG

The PDF is a flat raster in NAD83(CSRS) / UTM zone 20N with a wrong scale bar, so it was registered to the road network
by template matching (one-off, checked by overlaying our roads on the page). REGISTRATION below is that result for the
2025.11.24 edition at 400 dpi (3400 x 4400 px). A different edition needs re-registering: change REGISTRATION.

Zone colours are read from the legend swatches; every pixel is matched to the nearest swatch colour. The result is
approximate (road gaps are filled from neighbours, thin flood-plain strips can be lost) - it only drives building looks.
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PATH = os.path.join(ROOT, "data", "amherst_map.json")
OUT_PATH = os.path.join(ROOT, "data", "zoning.json")

# page pixel = (E - E0)/S - LX*2/S + 102   (see register notes in the module docstring)
REGISTRATION = {"s": 1.49, "loc": (1948, 1095), "E0": 400000.0, "N0": 5070000.0, "res": 2.0, "offset": (102, 102),
                "dpi": 400, "size": (3400, 4400)}

MAP_AREA = (104, 104, 3307, 3518)   # page pixels of the map frame (legend and title sit below it)
CELL = 10.0           # metres per grid cell
FILL_CELLS = 4        # road gaps up to this many cells are filled from the nearest zoned neighbour
TOLERANCE = 14.0      # max RGB distance to count as a legend colour

# code -> (name, legend swatch pixel on the 400 dpi page). One-letter codes keep the JSON small.
ZONES = {
    "C": ("CDD Comprehensive Development District", (1815, 3707)),
    "D": ("DT Downtown Commercial", (1815, 3802)),
    "F": ("F Flood Plain", (1815, 3896)),
    "R": ("RG General Residential", (1815, 3991)),
    "H": ("CH Highway Commercial", (1815, 4083)),
    "M": ("M Industrial", (1815, 4173)),
    "B": ("BP Business Park", (2614, 3709)),
    "I": ("I Institutional", (2614, 3804)),
    "U": ("MU Mixed Use", (2614, 3896)),
    "T": ("RM Mini Home Residential", (2614, 3993)),
    "N": ("CN Neighbourhood Commercial", (2614, 4085)),
    "O": ("O Open Space", (2614, 4178)),
}
NONE = "-"


def fwd(lat, lon):
    """Lat/lon (degrees, numpy arrays ok) -> UTM zone 20N (E, N) on GRS80, Krueger series."""
    a, f, k0, lon0 = 6378137.0, 1 / 298.257222101, 0.9996, -63.0
    n = f / (2 - f)
    big_a = a / (1 + n) * (1 + n * n / 4 + n ** 4 / 64)
    alpha = [n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16, 13 * n ** 2 / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240]
    e = math.sqrt(f * (2 - f))
    p, lam = np.radians(lat), np.radians(lon - lon0)
    t = np.sinh(np.arctanh(np.sin(p)) - e * np.arctanh(e * np.sin(p)))
    xi = np.arctan2(t, np.cos(lam))
    eta = np.arctanh(np.sin(lam) / np.sqrt(1 + t * t))
    east = 500000 + k0 * big_a * (eta + sum(alpha[j] * np.cos(2 * (j + 1) * xi) * np.sinh(2 * (j + 1) * eta)
                                            for j in range(3)))
    north = k0 * big_a * (xi + sum(alpha[j] * np.sin(2 * (j + 1) * xi) * np.cosh(2 * (j + 1) * eta)
                                   for j in range(3)))
    return east, north


def game_to_page(x, y, meta):
    """Game metres (x east, y south) -> pixel (px, py) on the 400 dpi page."""
    r = 6371000.0
    lat = meta["origin_lat"] - np.degrees(y / r)
    lon = meta["origin_lon"] + np.degrees(x / (r * math.cos(math.radians(meta["origin_lat"]))))
    east, north = fwd(lat, lon)
    g = REGISTRATION
    lx, ly = g["loc"]
    u = (east - g["E0"] - lx * g["res"]) / g["s"]
    v = (g["N0"] + 10000 - ly * g["res"] - north) / g["s"]
    return u + g["offset"][0], v + g["offset"][1]


def load_rgb(path):
    import pygame
    surf = pygame.image.load(path)
    return np.transpose(pygame.surfarray.array3d(surf), (1, 0, 2)).astype(np.int16)   # [row, col, rgb]


def rasterise(pdf):
    d = tempfile.mkdtemp(prefix="zoning_")
    base = os.path.join(d, "page")
    subprocess.check_call(["pdftoppm", "-r", str(REGISTRATION["dpi"]), "-png", "-singlefile", pdf, base])
    return base + ".png"


def classify(img):
    """Label every pixel with an index into `codes` (or 254 = light background, 255 = unknown)."""
    codes = list(ZONES)
    sw = np.array([img[ZONES[c][1][1], ZONES[c][1][0]] for c in codes], dtype=np.float32)
    h, w, _ = img.shape
    best = np.full((h, w), 1e9, dtype=np.float32)
    lab = np.full((h, w), 255, dtype=np.uint8)
    for i, col in enumerate(sw):
        d = np.sqrt(((img - col) ** 2).sum(axis=2))
        m = (d < best) & (d < TOLERANCE)
        best[m] = d[m]
        lab[m] = i
    light = (img.min(axis=2) > 228) & ((img.max(axis=2) - img.min(axis=2)) < 30) & (lab == 255)
    lab[light] = 254
    return codes, lab


def build(img, meta):
    codes, lab = classify(img)
    h, w = lab.shape
    # cells whose centre lands on the page
    gx0, gy0, gx1, gy1 = [int(v // CELL) * CELL for v in meta["bounds"]]
    xs = np.arange(gx0, gx1 + CELL, CELL) + CELL / 2
    ys = np.arange(gy0, gy1 + CELL, CELL) + CELL / 2
    gx, gy = np.meshgrid(xs, ys)
    px, py = game_to_page(gx, gy, meta)
    mx0, my0, mx1, my1 = MAP_AREA
    inside = (px >= mx0) & (py >= my0) & (px < mx1) & (py < my1)       # the map frame, not the legend
    rows = np.where(inside.any(axis=1))[0]
    cols = np.where(inside.any(axis=0))[0]
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    px, py, inside = px[r0:r1, c0:c1], py[r0:r1, c0:c1], inside[r0:r1, c0:c1]
    nz = len(codes)
    counts = np.zeros(px.shape + (nz + 1,), dtype=np.int16)      # last bin = light background
    for dy in (-2, 0, 2):
        for dx in (-2, 0, 2):
            ix = np.clip(np.rint(px + dx).astype(int), 0, w - 1)
            iy = np.clip(np.rint(py + dy).astype(int), 0, h - 1)
            v = lab[iy, ix]
            for k in range(nz):
                counts[..., k] += (v == k)
            counts[..., nz] += (v == 254)
    zone = counts[..., :nz].argmax(axis=2)
    zn = counts[..., :nz].max(axis=2)
    bg = counts[..., nz]
    grid = np.full(px.shape, "?", dtype="<U1")
    for k, c in enumerate(codes):
        grid[(zone == k) & (zn >= 3) & (zn >= bg)] = c
    grid[((bg > zn) | (zn < 3)) & (zn + bg >= 3) & (bg > 0)] = NONE
    grid[~inside] = NONE
    grid = fill_gaps(grid)
    grid = fill_specks(grid)
    return grid, (gx0 + c0 * CELL, gy0 + r0 * CELL)


def fill_gaps(grid):
    """Unknown ('?') cells (road lines, labels, hatching) take the most common zone among nearby known cells."""
    h, w = grid.shape
    out = grid.copy()
    for _ in range(FILL_CELLS):
        unknown = np.argwhere(out == "?")
        if not len(unknown):
            break
        nxt = out.copy()
        for r, c in unknown:
            seen = {}
            for rr in range(max(0, r - 1), min(h, r + 2)):
                for cc in range(max(0, c - 1), min(w, c + 2)):
                    v = out[rr, cc]
                    if v not in ("?", NONE):
                        seen[v] = seen.get(v, 0) + 1
            if seen:
                nxt[r, c] = max(seen, key=seen.get)
        out = nxt
    out[out == "?"] = NONE
    return out


def fill_specks(grid):
    """Road lines are light, so a few cells inside a zone read as 'not zoned'. Give them the zone around them."""
    h, w = grid.shape
    for _ in range(3):
        out = grid.copy()
        for r, c in np.argwhere(grid == NONE):
            seen = {}
            for rr in range(max(0, r - 1), min(h, r + 2)):
                for cc in range(max(0, c - 1), min(w, c + 2)):
                    v = grid[rr, cc]
                    if v != NONE:
                        seen[v] = seen.get(v, 0) + 1
            if seen and sum(seen.values()) >= 5:
                out[r, c] = max(seen, key=seen.get)
        grid = out
    return grid


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    src = argv[1]
    png = rasterise(src) if src.lower().endswith(".pdf") else src
    with open(MAP_PATH) as f:
        meta = json.load(f)["meta"]
    img = load_rgb(png)
    if img.shape[1] != REGISTRATION["size"][0] or img.shape[0] != REGISTRATION["size"][1]:
        print("warning: page is %dx%d, registration was made for %dx%d" % (img.shape[1], img.shape[0],
                                                                         *REGISTRATION["size"]))
    grid, (x0, y0) = build(img, meta)
    keep = np.argwhere(grid != NONE)
    r0, c0 = keep.min(axis=0)
    r1, c1 = keep.max(axis=0) + 1
    grid = grid[r0:r1, c0:c1]
    doc = {"_about": "Zone code per %g m cell from the Town of Amherst zoning map (2025.11.24, Prov. of NS). Row 0 is "
                     "the northern-most row; x grows east, y grows south. '-' = not zoned. Made by "
                     "tools/zoning_from_pdf.py." % CELL,
           "cell": CELL, "x0": x0 + float(c0) * CELL, "y0": y0 + float(r0) * CELL,
           "zones": {c: ZONES[c][0] for c in ZONES},
           "rows": ["".join(r) for r in grid]}
    with open(OUT_PATH, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    tally = {}
    for r in doc["rows"]:
        for ch in r:
            tally[ch] = tally.get(ch, 0) + 1
    print("wrote %s: %d x %d cells of %g m" % (OUT_PATH, grid.shape[1], grid.shape[0], CELL))
    for c, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print("  %s %-42s %6.2f km2" % (c, ZONES.get(c, ("not zoned",))[0], n * CELL * CELL / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
