#!/usr/bin/env python3
"""Bake the map for the native C++ game (github.com/jeremylegere-wq/amherst-run-native) into one binary file.

    python tools/bake_native.py                      # -> dist/amherst.amr
    python tools/bake_native.py --out some/where.amr

The map is loaded exactly as the Python game loads it (World.load: LiDAR heights, map edits, parking lots, extras,
cul-de-sacs, custom buildings, graded roads and overpass decks), so every fix lands in the bake and the C++ game ports
none of that code. Polygons are triangulated here too.

File format (little-endian; the C++ loader is src/world/map_file.cpp in the native repository):

    "AMR1"  u32 version  u32 chunk count
    then per chunk: 4-byte tag, u32 payload length, payload. Readers skip tags they do not know.

    META  f32 bounds[4] (x0 y0 x1 y1), f32 spawn x y heading, str attribution, str source version
    NAME  u32 n, n x str                                  (street names; str = u32 length + UTF-8 bytes)
    TERR  f32 x0 y0 step, u32 nx ny, f32 base unit, u16[nx*ny] heights (h = base + unit * v, rows south to north)
    ROAD  u32 n, per road: u8 type (0 lane 1 side 2 main), u8 service (0 none 1 driveway 2 track 3 other),
          u8 flags (1 one-way, 2 bridge, 4 lift/deck, 8 tunnel, 16 turnaround), u8 lanes, f32 width, f32 speed km/h,
          u32 name, u32 points, points x f32 (x y)
    SPAN  u32 n, per deck: u32 road index, f32 width, f32 lift, u32 points, points x f32 (x y h-above-ground)
    BLDG  u32 n, per building: f32 wall height, f32 roof height, u8 roof (0 flat 1 gable 2 hip 3 cone 4 mansard),
          u8 flags (1 ridge across, 2 landmark), u8 wall rgb[3], u8 roof rgb[3], u8 pad,
          u32 points, points x f32 (x y), u32 triangles, triangles x u16[3] (footprint, indices into its points)
    POLY  u32 n, per area: u8 kind (0 water 1 park 2 lot 3 land use), u8 rgb[3], u32 points, points x f32 (x y),
          u32 triangles, triangles x u16[3]

Version 1. Bump VERSION whenever the layout changes; the C++ loader refuses versions it does not know.
"""
import argparse
import math
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VERSION = 1
TYPES = {"lane": 0, "side": 1, "main": 2}
SERVICE = {None: 0, "driveway": 1, "track": 2}
ROOFS = {None: 0, "flat": 0, "gable": 1, "hip": 2, "cone": 3, "mansard": 4}
POLY_KIND = {"water": 0, "park": 1, "lot": 2, "area": 3}
HEIGHT_UNIT = 0.005                       # metres per step of the u16 heights (0 .. 327 m above the lowest point)


def _str(s):
    b = (s or "").encode("utf-8")
    return struct.pack("<I", len(b)) + b


def _chunk(tag, payload):
    assert len(tag) == 4
    return tag.encode("ascii") + struct.pack("<I", len(payload)) + payload


def _clean(points):
    """Polygon points without a repeated closing point or zero-length edges."""
    out = []
    for p in points:
        p = (float(p[0]), float(p[1]))
        if not out or math.dist(p, out[-1]) > 1e-3:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) <= 1e-3:
        out.pop()
    return out


def _area2(pts):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def triangulate(points):
    """Ear clipping. Returns [(i, j, k)] counter-clockwise triangles indexing `points` ([] if it cannot)."""
    n = len(points)
    if n < 3:
        return []
    idx = list(range(n))
    if _area2(points) < 0:
        idx.reverse()                                   # work counter-clockwise

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    tris, guard = [], 0
    while len(idx) > 3 and guard < 4 * n * n:
        guard += 1
        m = len(idx)
        for k in range(m):
            i, j, l = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = points[i], points[j], points[l]
            if cross(a, b, c) <= 1e-9:
                continue                                 # reflex or flat corner
            if any(inside(points[q], a, b, c) for q in idx if q not in (i, j, l)):
                continue
            tris.append((i, j, l))
            del idx[k]
            break
        else:                                            # no ear (self-touching outline): fan what is left
            for k in range(1, len(idx) - 1):
                tris.append((idx[0], idx[k], idx[k + 1]))
            return tris
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def _poly_payload(pts, tris):
    out = struct.pack("<I", len(pts)) + b"".join(struct.pack("<ff", x, y) for x, y in pts)
    return out + struct.pack("<I", len(tris)) + b"".join(struct.pack("<HHH", *t) for t in tris)


def _rgb(c, default):
    c = c if c else default
    return tuple(max(0, min(255, int(v))) for v in c[:3])


def bake(world, source=""):
    """The .amr file's bytes for a loaded World."""
    from game.render3d import STYLES
    st = STYLES["street"]                             # the game's default look
    chunks = []
    x0, y0, x1, y1 = world.bounds
    sx, sy, sh = world.spawn()
    from game import config
    chunks.append(_chunk("META", struct.pack("<4f3f", x0, y0, x1, y1, sx, sy, sh) + _str(config.ATTRIBUTION)
                         + _str(source)))
    names, name_ix = [], {}
    for r in world.roads:
        nm = r.get("name") or ""
        if nm not in name_ix:
            name_ix[nm] = len(names)
            names.append(nm)
    chunks.append(_chunk("NAME", struct.pack("<I", len(names)) + b"".join(_str(n) for n in names)))
    t = world.terrain
    if t is not None:
        lo, hi = min(t.h), max(t.h)
        if (hi - lo) / HEIGHT_UNIT > 65535:
            raise ValueError("terrain range %.1f m does not fit the u16 heights" % (hi - lo))
        q = [int(round((v - lo) / HEIGHT_UNIT)) for v in t.h]
        chunks.append(_chunk("TERR", struct.pack("<3f2I2f", t.x0, t.y0, t.step, t.nx, t.ny, lo, HEIGHT_UNIT)
                             + struct.pack("<%dH" % len(q), *q)))
    lifted = {id(r) for sp in world.spans for r in sp.get("roads", [sp["road"]])}
    road_ix = {}
    body = [struct.pack("<I", len(world.roads))]
    for i, r in enumerate(world.roads):
        road_ix[id(r)] = i
        flags = ((1 if r.get("oneway") else 0) | (2 if r.get("bridge") else 0) | (4 if id(r) in lifted else 0)
                 | (8 if r.get("tunnel") else 0) | (16 if r.get("turnaround") else 0))
        pts = r["points"]
        body.append(struct.pack("<4B2f2I", TYPES.get(r.get("type"), 0), SERVICE.get(r.get("service"), 3), flags,
                                min(255, int(r.get("lanes") or 0)), float(r.get("width", 7.0)),
                                float(r.get("speed") or 50), name_ix[r.get("name") or ""], len(pts)))
        body.append(b"".join(struct.pack("<ff", p[0], p[1]) for p in pts))
    chunks.append(_chunk("ROAD", b"".join(body)))
    body = [struct.pack("<I", len(world.spans))]
    for sp in world.spans:
        body.append(struct.pack("<I2fI", road_ix[id(sp["road"])], float(sp["width"]), float(sp["lift"] or 0),
                                len(sp["points"])))
        body.append(b"".join(struct.pack("<3f", p[0], p[1], h) for p, h in zip(sp["points"], sp["h"])))
    chunks.append(_chunk("SPAN", b"".join(body)))
    mats = st.get("materials", {})
    slate = st.get("slate", (96, 100, 112))
    body, count, dropped = [], 0, 0
    for b in world.buildings:
        if b.get("removed"):
            continue
        pts = _clean(b["points"])
        tris = triangulate(pts)
        if not tris or len(pts) > 65535:
            dropped += 1
            continue
        mat = mats.get(b.get("material")) or [(176, 84, 68)]
        wall = _rgb(b.get("colour"), mat[0])
        roof = _rgb(b.get("roof_colour"), slate)
        flags = (1 if b.get("ridge_across") else 0) | (2 if b.get("landmark") else 0)
        body.append(struct.pack("<2f2B3B3BB", float(b.get("height") or 6.0), float(b.get("roof_height") or 0.0),
                                ROOFS.get(b.get("roof"), 0), flags, *wall, *roof, 0) + _poly_payload(pts, tris))
        count += 1
    chunks.append(_chunk("BLDG", struct.pack("<I", count) + b"".join(body)))
    polys = []
    for kind, group, col in (("water", world.water, st["water"]), ("park", world.parks, st.get("park", st["grass"])),
                             ("lot", world.lots, st["road"]["side"]),
                             ("area", world.areas, None)):
        for p in group:
            pts = _clean(p["points"])
            tris = triangulate(pts)
            if not tris or len(pts) > 65535:
                continue
            if col is not None:
                c = col
            else:                                        # land use: the same blend the Python renderer draws
                from game.render3d import AREA_COLOURS, _lerp_rgb
                c = _lerp_rgb(AREA_COLOURS.get(p.get("kind"), AREA_COLOURS["grass"]), st["park"], 0.35)
            polys.append(struct.pack("<4B", POLY_KIND[kind], *_rgb(c, st["grass"])) + _poly_payload(pts, tris))
    chunks.append(_chunk("POLY", struct.pack("<I", len(polys)) + b"".join(polys)))
    data = b"AMR1" + struct.pack("<II", VERSION, len(chunks)) + b"".join(chunks)
    return data, {"roads": len(world.roads), "spans": len(world.spans), "buildings": count, "dropped": dropped,
                  "polygons": len(polys), "bytes": len(data)}


def read_chunks(data):
    """{tag: payload} of a baked file (for tests and checks)."""
    if data[:4] != b"AMR1":
        raise ValueError("not an Amherst Run map file")
    version, n = struct.unpack_from("<II", data, 4)
    out, off = {"_version": version}, 12
    for _ in range(n):
        tag = data[off:off + 4].decode("ascii")
        (length,) = struct.unpack_from("<I", data, off + 4)
        out[tag] = data[off + 8:off + 8 + length]
        off += 8 + length
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "amherst.amr"))
    args = ap.parse_args(argv)
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from game import __version__
    from game.world import World
    world = World.load(args.map)
    data, info = bake(world, source="amherst-run " + __version__)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, args.out)
    print("wrote %s: %d roads, %d overpass decks, %d buildings (%d dropped), %d areas, %.1f MB"
          % (args.out, info["roads"], info["spans"], info["buildings"], info["dropped"], info["polygons"],
             info["bytes"] / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
