"""Road grading: smooth road profiles written into the ground, so every road flows the way real roads do.

The LiDAR ground (data/elevation.json) shows the land as it is: stream valleys, ditches and the cut a highway makes
under an overpass. Real roads bridge or fill those and cut through short humps. So, at load time:

  1. every road's ground profile is sampled every STEP metres; dips narrower than FILL metres are filled (closing),
     humps narrower than CUT metres are cut (opening), and the result is smoothed over SMOOTH metres;
  2. the ground under each road (its half width + EDGE) is set to its profile and blended into the land over BLEND
     metres. Busier roads go first and keep their surface; each quieter class grades from the ground as the busier
     ones left it, so their ends meet. Overpass decks are not written: the road below keeps its own level under them;
  3. each overpass (game/world.py spans) then gets its deck heights from its own graded profile: the deck carries the
     embankment level straight across, and the clearance above the road below comes out of the real ground.

Uses numpy (pygame + numpy are the game's only dependencies).
"""
import math

import numpy as np

STEP = 4.0            # metres between profile samples
FILL = 60.0           # metres: dips narrower than this are filled (bridges, culverts); wider ones the road follows
CUT = 30.0            # metres: humps narrower than this are cut
MAX_FILL = 6.0        # metres: the most a road is ever raised above the ground (no causeways)
SMOOTH = 28.0         # metres: moving average over the profile
EDGE = 3.0            # metres beyond the road edge that take the road's height
BLEND = 12.0          # metres over which that fades back into the land
ORDER = {"lane": 0, "side": 1, "main": 2}
SKIP_SERVICE = ("driveway", "track")
CHUNK = 25            # profile samples per piece when writing a long road (100 m)


def _samples(points, step=STEP):
    out = [tuple(points[0])]
    for a, b in zip(points, points[1:]):
        n = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / step)))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return np.array(out)


def _run(h, k, fn):
    """Sliding max (fn=np.max) or min over windows of k samples, centred, edges padded."""
    if k <= 1 or len(h) < 2:
        return h.copy()
    half = k // 2
    pad = np.concatenate([np.full(half, h[0]), h, np.full(half, h[-1])])
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * half + 1)
    return fn(win, axis=1)


def profile(ground):
    """The graded profile of a road from its raw ground heights (one per STEP metres)."""
    h = np.asarray(ground, dtype=np.float64)
    if len(h) < 3:
        return h.copy()
    kf, kc, ks = int(FILL / STEP) | 1, int(CUT / STEP) | 1, int(SMOOTH / STEP) | 1
    filled = np.minimum(_run(_run(h, kf, np.max), kf, np.min), h + MAX_FILL)   # closing: fills narrow dips
    cut = _run(_run(filled, kc, np.min), kc, np.max)        # opening: cuts narrow humps
    if len(cut) >= ks:
        half = ks // 2
        pad = np.concatenate([np.full(half, cut[0]), cut, np.full(half, cut[-1])])
        cut = np.convolve(pad, np.ones(ks) / ks, mode="valid")
    cut[0], cut[-1] = h[0], h[-1]                           # the ends meet the roads they join
    return cut


def grade(terrain, roads, spans=()):
    """Grade `roads` into `terrain` (in place) and set the overpass heights of `spans`. Returns (roads graded, nodes)."""
    orig = np.frombuffer(terrain.h, dtype=np.float32).astype(np.float64).reshape(terrain.ny, terrain.nx)
    target = orig.copy()
    weight = np.ones_like(orig)                              # 1 = untouched land, 0 = the road's own height
    lifted = {id(r) for sp in spans for r in sp.get("roads", [sp["road"]])}
    todo = [r for r in roads if r.get("service") not in SKIP_SERVICE and not r.get("tunnel") and len(r["points"]) > 1]
    count = 0
    cur = orig
    for rank in sorted({ORDER.get(r.get("type"), 0) for r in todo}, reverse=True):
        # busiest first: highways, then streets, then lanes. Each class reads the ground as the classes above left it,
        # so a street's ends meet the highway's graded level, and never overwrites their surface.
        for r in todo:
            if ORDER.get(r.get("type"), 0) != rank or id(r) in lifted:
                continue                                      # (a deck: the road below keeps the ground)
            pts = _samples(r["points"])
            g = _bilinear_live(terrain, orig, target, weight, pts)  # the ground as every road so far left it
            if r.get("bridge"):                               # a bridge: straight from one end to the other
                p = np.linspace(g[0], g[-1], len(g))
            else:
                p = profile(g)
            radius = r.get("width", 7.0) / 2.0 + EDGE
            for a in range(0, len(pts) - 1, CHUNK):          # in pieces: a small grid around each
                b = min(len(pts), a + CHUNK + 1)
                _write(terrain, pts[a:b], p[a:b], radius, target, weight)
            count += 1
        cur = target * (1.0 - weight) + orig * weight
    final = cur
    from array import array
    h = array("f")
    h.frombytes(final.astype(np.float32).ravel().tobytes())
    terrain.h = h
    for sp in spans:
        _span_heights(terrain, sp, orig)
    return count, int((weight < 1.0).sum())


def _bilinear(terrain, grid, pts):
    """Heights of the grid (ny x nx numpy array, terrain's layout) at points (n x 2), bilinear, edges clamped."""
    fx = np.clip((pts[:, 0] - terrain.x0) / terrain.step, 0.0, terrain.nx - 1.000001)
    fy = np.clip((pts[:, 1] - terrain.y0) / terrain.step, 0.0, terrain.ny - 1.000001)
    i, j = fx.astype(int), fy.astype(int)
    tx, ty = fx - i, fy - j
    a, b = grid[j, i], grid[j, np.minimum(i + 1, terrain.nx - 1)]
    c, d = grid[np.minimum(j + 1, terrain.ny - 1), i], grid[np.minimum(j + 1, terrain.ny - 1), np.minimum(i + 1, terrain.nx - 1)]
    top = a + (b - a) * tx
    return top + (c + (d - c) * tx - top) * ty


def _bilinear_live(terrain, orig, target, weight, pts):
    """_bilinear on the ground as graded so far (target mixed with orig by weight), computed only where sampled."""
    fx = np.clip((pts[:, 0] - terrain.x0) / terrain.step, 0.0, terrain.nx - 1.000001)
    fy = np.clip((pts[:, 1] - terrain.y0) / terrain.step, 0.0, terrain.ny - 1.000001)
    i, j = fx.astype(int), fy.astype(int)
    i1, j1 = np.minimum(i + 1, terrain.nx - 1), np.minimum(j + 1, terrain.ny - 1)

    def at(jj, ii):
        w = weight[jj, ii]
        return target[jj, ii] * (1.0 - w) + orig[jj, ii] * w
    tx, ty = fx - i, fy - j
    a, b, c, d = at(j, i), at(j, i1), at(j1, i), at(j1, i1)
    top = a + (b - a) * tx
    return top + (c + (d - c) * tx - top) * ty


def _write(terrain, pts, prof, radius, target, weight):
    """Set the nodes near the polyline `pts` to the profile `prof` (nearest sample), blending out over BLEND."""
    reach = radius + BLEND
    x0, y0 = pts[:, 0].min() - reach, pts[:, 1].min() - reach
    x1, y1 = pts[:, 0].max() + reach, pts[:, 1].max() + reach
    i0 = max(0, int((x0 - terrain.x0) / terrain.step))
    i1 = min(terrain.nx - 1, int((x1 - terrain.x0) / terrain.step) + 1)
    j0 = max(0, int((y0 - terrain.y0) / terrain.step))
    j1 = min(terrain.ny - 1, int((y1 - terrain.y0) / terrain.step) + 1)
    if i1 < i0 or j1 < j0:
        return
    ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1))
    X, Y = terrain.x0 + ii * terrain.step, terrain.y0 + jj * terrain.step
    # nearest profile sample to each node, all at once (samples are STEP apart, nodes 12.5 m: close enough)
    d = np.hypot(X.ravel()[:, None] - pts[None, :, 0], Y.ravel()[:, None] - pts[None, :, 1])
    k = d.argmin(axis=1)
    best = d[np.arange(len(k)), k].reshape(X.shape) - STEP / 2.0
    val = np.asarray(prof)[k].reshape(X.shape)
    near = best < reach
    u = np.clip((best - radius) / BLEND, 0.0, 1.0)
    w = u * u * (3.0 - 2.0 * u)
    sub_w = weight[j0:j1 + 1, i0:i1 + 1]
    sub_t = target[j0:j1 + 1, i0:i1 + 1]
    core = near & (w <= 0.0) & (sub_w > 0.0)                 # this road's own surface, where no busier road is
    sub_t[core] = val[core]
    sub_w[core] = 0.0
    edge = near & (w > 0.0) & (w < sub_w)                     # its verge, where nothing stronger is already set
    sub_t[edge] = val[edge]
    sub_w[edge] = w[edge]


def _span_heights(terrain, sp, orig):
    """An overpass's heights above the graded ground. The deck is a straight line between its abutments (the
    LiDAR ground at its two ends: the embankment tops), at least `lift` above the ground everywhere under it; the
    ramps rise smoothly from their approach roads to meet it. Zero at the span's two ends."""
    old_pts, old_h = sp["points"], sp["h"]
    dense, dense_h = [tuple(old_pts[0])], [old_h[0]]        # every STEP metres: a long deck has only two points
    for (a, ha), (b, hb) in zip(zip(old_pts, old_h), zip(old_pts[1:], old_h[1:])):
        n = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / STEP)))
        for k in range(1, n + 1):
            dense.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
            dense_h.append(ha + (hb - ha) * k / n)
    sp["points"], sp["h"] = dense, dense_h
    pts = np.array(dense, dtype=np.float64)
    final = np.frombuffer(terrain.h, dtype=np.float32).astype(np.float64).reshape(terrain.ny, terrain.nx)
    ground = _bilinear(terrain, final, pts)
    raw = _bilinear(terrain, orig, pts)
    lift = float(sp.get("lift") or 0.0)
    deck = np.nonzero(np.array(sp["h"]) >= lift - 1e-6)[0]
    if len(deck) == 0:
        return
    d0, d1 = int(deck[0]), int(deck[-1])
    run = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])))])
    t0, t1 = max(raw[d0], ground[d0]), max(raw[d1], ground[d1])
    span = max(run[d1] - run[d0], 1e-6)
    line = t0 + (t1 - t0) * (run[d0:d1 + 1] - run[d0]) / span
    short = float(np.max(ground[d0:d1 + 1] + lift - line))
    if short > 0.0:                                           # not enough clearance: lift the whole deck
        line = line + short
        t0, t1 = t0 + short, t1 + short
    top = ground.copy()
    top[d0:d1 + 1] = line
    for a, b, t in ((0, d0, t0), (len(pts) - 1, d1, t1)):     # each ramp: from its approach up to the deck end
        if a == b:
            continue
        idx = np.arange(min(a, b), max(a, b) + 1)
        u = np.abs(run[idx] - run[a]) / max(abs(run[b] - run[a]), 1e-6)      # 0 at the approach, 1 at the deck
        s3 = u * u * (3.0 - 2.0 * u)
        top[idx] = ground[idx] * (1.0 - s3) + t * s3
    hs = np.maximum(0.0, top - ground)
    hs[0], hs[-1] = 0.0, 0.0
    sp["h"] = [round(float(v), 2) for v in hs]
