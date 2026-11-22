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
          u8 flags (1 one-way, 2 bridge, 4 lift/deck, 8 tunnel, 16 turnaround), u8 lanes, f32 width, f32 posted speed km/h (0: none posted),
          u32 name, u32 points, points x f32 (x y)
    SPAN  u32 n, per deck: u32 road index, f32 width, f32 lift, u32 points, points x f32 (x y h-above-ground)
    BLDG  u32 n, per building: f32 wall height, f32 roof height, u8 roof (0 flat 1 gable 2 hip 3 cone 4 mansard),
          u8 flags (1 ridge across, 2 landmark), u8 wall rgb[3], u8 roof rgb[3], u8 pad,
          u32 points, points x f32 (x y), u32 triangles, triangles x u16[3] (footprint, indices into its points)
    POLY  u32 n, per area: u8 kind (0 water 1 park 2 lot 3 land use), u8 rgb[3], u32 points, points x f32 (x y),
          u32 triangles, triangles x u16[3]
    PROP  u32 kinds, kinds x str (tree, lamp, pole, ...), u32 n, per prop: u8 kind, u8 colour index (trees),
          u8 rgb[3] (own colour, 0 0 0 if none), u8 flags (1: a segment follows), f32 x y,
          u16 height cm, u16 radius cm, u16 collision radius cm, i16 heading mrad, [f32 x2 y2 if flags & 1]
          Every prop of the map: the fixed ones (lamps, poles, signs, hydrants, gravestones, fences, parked-car blocks)
          and every tree (LiDAR or woods), planted cell by cell in one fixed order (plant_everything)
    GRPH  the road graph the AI drives on (game/roadgraph.py RoadGraph of the loaded roads, built exactly as the game
          builds it): u32 nodes, nodes x f64 (x y), u32 edges, per edge: u32 a b, u8 type (0 lane 1 side 2 main),
          u8 pad[3], f32 width, f32 speed km/h (posted), u32 name. Edge order is the game's; a node's outgoing edges
          are the edges starting at it, in that order.
    JNCT  the junction rules (game/junctions.py Junctions, classified as the game does, with the map's OSM signals and
          stop signs): u32 nodes, per node u8 is-junction, f64 box radius, f64 stopping distance from the node;
          u32 edges, per edge u8 control of the junction it drives into (0 priority 1 signal 2 stop 3 yield
          4 all-way), u8 signal phase (0 east-west, 1 north-south)
    HUBS  job hubs (game/missions.py MissionManager._find_hubs): u32 n, per hub: u8 role (0 deliveries 1 getaway
          2 tour 3 courthouse), f64 x y (at the kerb), str label
    TOUR  Heritage Tour spots (the landmarks _make_tour visits): u32 n, per spot: f64 x y (in the near lane), str label
    SPRT  VS race finishes (game/battle.py sprint_targets): u32 n, per landmark: f64 x y, str label
    PANT  road paint and sidewalks (game/streetdetail.py): u32 roads, per road (ROAD order) u8 marking (0 none
          1 double yellow 2 dashed yellow 3 dashed white 4 highway 5 edges), u8 sidewalk where not downtown (0 edge
          shoulder 1 concrete), u8 gravel; then u32 cells, cells x i32 (cx cy): the 40 m cells near downtown, where a
          concrete sidewalk is brick instead
    RAIL  the rail line: u32 ways, per way: u32 points, points x f32 (x y)     (drawn as rail beds)
    TRAN  the train's run (game/train.py Train: the ways stitched into one line, and the stretch either side of
          town it runs): u32 points, points x f64 (x y), f64 lo hi (metres along the line)
    BDET  building details, one entry per BLDG building in the same order (game/archetypes.py and the street
          style's _house / _shop_walls / extras in game/render3d.py, worked out here so the native game only builds
          geometry): u8 house kind (0 none 1 garage 2 mini-home 3 bungalow 4 cape 5 two-storey), u8 storeys,
          u8 flags (1 porch 2 sidelights 4 no front windows 8 shutters 16 plaque 32 clock tower 64 cornice
          128 own door colour), u8 steeple (0 none 1 spire 2 turret 3 twin), u8 landmark (0 none 1 court house
          2 civic 3 church 4 armoury 5 other), u8 dormers, i16 front wall, i16 wrap-around wall (indices into the
          outline: wall k runs from point k to k+1; -1 none), f32 door place along the front wall (0..1),
          u8 rgb[3] x 4 (door, shutters, plaque, plinth), f32 window height, f32 plinth height (0 none),
          f32 chimney place along the ridge (-1..1; -9 none), i8 dormer side (+1/-1 of the ridge's left normal),
          u8 shop storeys (0 from the height), u8 shop walls n, n x u16 (walls with a shop front)
    PARK  hand-placed parked cars (data/map_edits.json "cars"; game/render3d.py parked_cars): u32 n, per car:
          f32 x y heading (map radians), str model (game/car.py MODELS; "sedan" if unknown), u8 body rgb[3],
          u8 roof rgb[3]. Their collision circles are already in PROP (car_block)
    ADDR  real civic addresses (data/addresses.json, NS Civic Address File, OGL-NS): u32 n, per address: f32 x y,
          str number, u32 street (index into NAME)

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


HOUSE_KINDS = {"garage": 1, "minihome": 2, "bungalow": 3, "cape": 4, "two_storey": 5}
STEEPLES = {"none": 0, "spire": 1, "turret": 2, "twin": 3}
LANDMARKS = {"courthouse": 1, "civic": 2, "church": 3, "armoury": 4}


def _walls(pts):
    """(x0, y0, x1, y1, nx, ny) per outline edge k (point k to k+1), normals pointing out (game/render3d.py)."""
    area = _area2(pts)
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        nx, ny = (dy / L, -dx / L) if area > 0 else (-dy / L, dx / L)
        out.append((a[0], a[1], b[0], b[1], nx, ny))
    return out


def _details(world, i, b, pts):
    """The BDET entry of building i (outline pts as baked): what Renderer3D._house, _shop_walls and the building
    extras work out for the street style, so the native game draws the same doors, windows, porches and fronts."""
    from game import archetypes
    from game.render3d import SHOP_ZONES
    walls = _walls(pts)
    kind, storeys, flags, front, wrap, door = 0, 1, 0, -1, -1, 0.5
    door_rgb = shutters = plaque = plinth = (0, 0, 0)
    info = archetypes.classify(b, i)
    if info is not None and info["kind"] in HOUSE_KINDS:
        kind, storeys = HOUSE_KINDS[info["kind"]], int(info["storeys"])
        if b.get("front") is not None:                              # hand-set: compass bearing the front faces
            fb = math.radians(b["front"])
            fx, fy = math.sin(fb), -math.cos(fb)
            f = max(range(len(walls)), key=lambda k: walls[k][4] * fx + walls[k][5] * fy)
        else:
            f = archetypes.front_wall(walls, world.on_road)
        front = -1 if f is None else f
        door = b["door_at"] if b.get("door_at") is not None else 0.3 + 0.4 * archetypes._coin(i, 3)
        flags |= (1 if info["porch"] else 0) | (2 if b.get("sidelights") else 0)
        flags |= 4 if b.get("front_windows") is False else 0
        if b.get("door"):
            flags |= 128
            door_rgb = tuple(b["door"])
        if b.get("shutters"):
            flags |= 8
            shutters = tuple(b["shutters"])
        if b.get("plaque"):
            flags |= 16
            plaque = tuple(b["plaque"])
        if info.get("wrap") and f is not None:                      # the veranda turns the corner (as _house)
            n = len(walls)
            nbrs = [(f - 1) % n, (f + 1) % n]
            near = archetypes.front_wall([walls[k] for k in nbrs], world.on_road)
            wrap = nbrs[near] if near is not None else max(
                nbrs, key=lambda k: math.hypot(walls[k][2] - walls[k][0], walls[k][3] - walls[k][1]))
    has_ex = bool(b.get("material") or b.get("landmark") or b.get("roof"))
    landmark = b.get("landmark")
    lm = LANDMARKS.get(landmark, 5) if landmark else 0
    if has_ex and b.get("tower"):
        flags |= 32
    if b.get("material") in ("sandstone", "brick"):
        flags |= 64
    if b.get("plinth"):
        plinth = tuple(b["plinth"])
    shops = []
    downtown = b.get("material") in ("sandstone", "brick") and (b.get("zone") in SHOP_ZONES or b.get("zone") is None)
    if has_ex and (b.get("shopfront") or (b.get("shopfront") is None and downtown and not landmark)):
        for k, w in enumerate(walls):
            if math.hypot(w[2] - w[0], w[3] - w[1]) >= 3.0 and archetypes.front_wall([w], world.on_road, 9.0, 1.5) == 0:
                shops.append(k)
    chimney = -9.0
    if b.get("chimney") is not None and b.get("roof") in ("gable", "hip") and len(pts) == 4:
        chimney = float(b["chimney"])
    dormers, side = int(b.get("dormers") or 0), 1
    if dormers and len(pts) == 4:                                    # which roof slope faces the street (_dormer_frame)
        cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
        e1 = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
        e2 = (pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
        l1, l2 = math.hypot(*e1), math.hypot(*e2)
        e, hw = (e1, l2 / 2) if (l1 >= l2) != bool(b.get("ridge_across")) else (e2, l1 / 2)
        L = math.hypot(*e) or 1.0
        ux, uy = e[0] / L, e[1] / L
        vx, vy = -uy, ux
        if b.get("front") is not None:
            fb = math.radians(b["front"])
            side = 1 if vx * math.sin(fb) - vy * math.cos(fb) >= 0 else -1
        else:
            for s_ in (1, -1):
                wx, wy = cx + s_ * vx * hw, cy + s_ * vy * hw
                if archetypes.front_wall([(wx - ux, wy - uy, wx + ux, wy + uy, s_ * vx, s_ * vy)], world.on_road, 40.0) == 0:
                    side = s_
                    break
    steeple = STEEPLES.get(b.get("steeple", "spire"), 1) if landmark == "church" else 0
    out = struct.pack("<6B2hf", kind, storeys, flags, steeple, lm, min(255, dormers), front, wrap, float(door))
    out += struct.pack("<12B", *door_rgb, *shutters, *plaque, *plinth)
    out += struct.pack("<3f", float(b.get("window_h") or 1.3), float(b.get("plinth_h") or 1.6) if b.get("plinth") else 0.0,
                       chimney)
    out += struct.pack("<b2B", side, min(255, int(b.get("storeys") or 0)), len(shops))
    return out + b"".join(struct.pack("<H", k) for k in shops)


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
                                float(r.get("speed") or 0), name_ix[r.get("name") or ""], len(pts)))
        body.append(b"".join(struct.pack("<ff", p[0], p[1]) for p in pts))
    chunks.append(_chunk("ROAD", b"".join(body)))
    body = [struct.pack("<I", len(world.spans))]
    for sp in world.spans:
        body.append(struct.pack("<I2fI", road_ix[id(sp["road"])], float(sp["width"]), float(sp["lift"] or 0),
                                len(sp["points"])))
        body.append(b"".join(struct.pack("<3f", p[0], p[1], h) for p, h in zip(sp["points"], sp["h"])))
    chunks.append(_chunk("SPAN", b"".join(body)))
    from game.render3d import default_height
    mats = st.get("materials", {})
    slate = st.get("slate", (96, 100, 112))
    cols = st["buildings"]
    body, details, count, dropped = [], [], 0, 0
    for i, b in enumerate(world.buildings):
        if b.get("removed"):
            continue
        pts = _clean(b["points"])
        tris = triangulate(pts)
        if not tris or len(pts) > 65535:
            dropped += 1
            continue
        mat = mats.get(b.get("material"))                 # the colour the Python renderer picks (_prep_building)
        wall = _rgb(b.get("colour"), mat[i % len(mat)] if mat else cols[(i * 31) % len(cols)])
        height = b.get("height") or default_height(b, i, abs(_area2(pts)) / 2)
        roof = _rgb(b.get("roof_colour"), slate)
        flags = (1 if b.get("ridge_across") else 0) | (2 if b.get("landmark") else 0)
        body.append(struct.pack("<2f2B3B3BB", float(height), float(b.get("roof_height") or 0.0),
                                ROOFS.get(b.get("roof"), 0), flags, *wall, *roof, 0) + _poly_payload(pts, tris))
        details.append(_details(world, i, b, pts))
        count += 1
    chunks.append(_chunk("BLDG", struct.pack("<I", count) + b"".join(body)))
    chunks.append(_chunk("BDET", struct.pack("<I", count) + b"".join(details)))
    from game.car import MODELS
    parked = getattr(world, "parked", ())
    body = [struct.pack("<I", len(parked))]
    for c in parked:
        col = tuple(c.get("colour") or (90, 94, 102))
        body.append(struct.pack("<3f", float(c["x"]), float(c["y"]), float(c["heading"]))
                    + _str(c.get("model") if c.get("model") in MODELS else "sedan")
                    + struct.pack("<6B", *col, *tuple(c.get("roof_colour") or col)))
    chunks.append(_chunk("PARK", b"".join(body)))
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
    payload, nprops = _props_payload(world)
    chunks.append(_chunk("PROP", payload))
    from game.roadgraph import RoadGraph
    graph = RoadGraph(world.roads)
    for e in graph.edges:
        if e.name not in name_ix:
            name_ix[e.name] = len(names)
            names.append(e.name)
    body = [struct.pack("<I", len(graph.nodes)) + b"".join(struct.pack("<2d", x, y) for x, y in graph.nodes),
            struct.pack("<I", len(graph.edges))]
    for e in graph.edges:
        body.append(struct.pack("<2I4B2fI", e.a, e.b, TYPES.get(e.rtype, 1), 0, 0, 0, float(e.width), float(e.kmh),
                                name_ix[e.name]))
    chunks.append(_chunk("GRPH", b"".join(body)))
    from game.junctions import Junctions
    jn = Junctions(graph, getattr(world, "marks", ()))
    ctl = {None: 0, "signal": 1, "stop": 2, "yield": 3, "allway": 4}
    body = [struct.pack("<I", len(graph.nodes))]
    for n in range(len(graph.nodes)):
        body.append(struct.pack("<B2d", 1 if jn.is_junction[n] else 0, jn.box.get(n, 0.0), jn.stop_at.get(n, 0.0)))
    body.append(struct.pack("<I", len(graph.edges)))
    body.append(b"".join(struct.pack("<2B", ctl[jn.control.get(e)], jn.phase.get(e, 0)) for e in range(len(graph.edges))))
    chunks.append(_chunk("JNCT", b"".join(body)))
    hubs, spots = _jobs(world, graph)
    roles = {"deliveries": 0, "getaway": 1, "tour": 2, "courthouse": 3}
    chunks.append(_chunk("HUBS", struct.pack("<I", len(hubs)) + b"".join(
        struct.pack("<B2d", roles[h.role], h.x, h.y) + _str(h.label) for h in hubs)))
    chunks.append(_chunk("TOUR", struct.pack("<I", len(spots)) + b"".join(
        struct.pack("<2d", x, y) + _str(label) for label, x, y in spots)))
    from game import streetdetail as SD
    downtown = SD.Downtown(world.buildings)
    body = [struct.pack("<I", len(world.roads))]
    for r in world.roads:
        body.append(struct.pack("<3B", SD.marking(r), 1 if SD.sidewalk(r, False) == SD.CONCRETE else 0,
                                1 if r.get("surface") == "gravel" else 0))
    cells = sorted({(cx + i, cy + j) for cx, cy in downtown.cells for i in (-1, 0, 1) for j in (-1, 0, 1)})
    body.append(struct.pack("<I", len(cells)) + b"".join(struct.pack("<2i", cx, cy) for cx, cy in cells))
    chunks.append(_chunk("PANT", b"".join(body)))
    rails = [r["points"] for r in world.rails if len(r["points"]) >= 2]
    chunks.append(_chunk("RAIL", struct.pack("<I", len(rails)) + b"".join(
        struct.pack("<I", len(pts)) + b"".join(struct.pack("<2f", p[0], p[1]) for p in pts) for pts in rails)))
    from game.train import Train
    train = Train(world)
    chunks.append(_chunk("TRAN", struct.pack("<I", len(train.chain)) + b"".join(
        struct.pack("<2d", p[0], p[1]) for p in train.chain) + struct.pack("<2d", train.lo, train.hi)))
    from game.battle import sprint_targets
    targets = sprint_targets(world)
    chunks.append(_chunk("SPRT", struct.pack("<I", len(targets)) + b"".join(
        struct.pack("<2d", x, y) + _str(label) for label, x, y in targets)))
    addrs = []
    if getattr(world, "addresses", None) is not None:
        for cell in sorted(world.addresses.grid):
            addrs.extend(world.addresses.grid[cell])
    for _x, _y, _num, street in addrs:
        if street not in name_ix:
            name_ix[street] = len(names)
            names.append(street)
    chunks.append(_chunk("ADDR", struct.pack("<I", len(addrs)) + b"".join(
        struct.pack("<2f", x, y) + _str(num) + struct.pack("<I", name_ix[street]) for x, y, num, street in addrs)))
    chunks[1] = _chunk("NAME", struct.pack("<I", len(names)) + b"".join(_str(n) for n in names))
    chunks[1] = _chunk("NAME", struct.pack("<I", len(names)) + b"".join(_str(n) for n in names))
    data = b"AMR1" + struct.pack("<II", VERSION, len(chunks)) + b"".join(chunks)
    return data, {"roads": len(world.roads), "spans": len(world.spans), "buildings": count, "dropped": dropped,
                  "polygons": len(polys), "props": nprops, "bytes": len(data)}


def plant_everything(world):
    """Plant the trees of every prop cell of the map, row by row from the south-west, and keep them all.

    The Python game plants a cell's trees when you first come near it, avoiding trees already planted beside it, so
    which trees stand right at a cell's edge depends on the order you drove in. Planting in one fixed order gives one
    fixed forest: the baked map uses it, and so do the golden drives, so both games hit the same trees."""
    import game.world as W
    W.WOODS_CELLS_KEPT = 10 ** 9                       # keep every cell's trees (the game forgets old ones)
    if not getattr(world, "_streaming", False):
        return
    x0, y0, x1, y1 = world.bounds
    for gy in range(int(y0 // W.CELL) - 1, int(y1 // W.CELL) + 2):
        for gx in range(int(x0 // W.CELL) - 1, int(x1 // W.CELL) + 2):
            if (gx, gy) not in world._woods_made:
                world._make_woods(gx, gy)


def _props_payload(world):
    plant_everything(world)
    props = [p for cell in sorted(world._prop_grid) for p in world._prop_grid[cell]]
    kinds = sorted({p["kind"] for p in props})
    kix = {k: i for i, k in enumerate(kinds)}

    def cm(v):
        return max(0, min(65535, int(round(float(v or 0.0) * 100))))
    out = [struct.pack("<I", len(kinds)) + b"".join(_str(k) for k in kinds) + struct.pack("<I", len(props))]
    for p in props:
        seg = "x2" in p and "y2" in p
        rgb = _rgb(p.get("colour"), (0, 0, 0))
        head = max(-32767, min(32767, int(round(float(p.get("heading") or 0.0) * 1000))))
        out.append(struct.pack("<2B3BB2f3Hh", kix[p["kind"]], int(p.get("c") or 0) & 255, *rgb, 1 if seg else 0,
                               float(p["x"]), float(p["y"]), cm(p.get("h")), cm(p.get("r")), cm(p.get("cr")), head))
        if seg:
            out.append(struct.pack("<2f", float(p["x2"]), float(p["y2"])))
    return b"".join(out), len(props)


def _jobs(world, graph):
    """(hubs, tour spots) exactly as game/missions.py finds them."""
    from game.missions import MissionManager, _centroid

    class _Town:                                      # the bits of game/town.py MissionManager reads at start
        cops = True
    _Town.graph = graph
    mm = MissionManager(world, _Town())
    spots = []
    for b in world.buildings:                         # the same list _make_tour builds, as curb points
        if b.get("landmark") and b.get("label"):
            spots.append((b["label"], _centroid(b["points"])))
    for p in getattr(world, "parks", ()):
        if p.get("landmark") == "square":
            spots.append((p.get("label", "Square"), _centroid(p["points"])))
    for p in world.props:
        if p["kind"] in ("cenotaph", "lighthouse") and p.get("label"):
            spots.append((p["label"], (p["x"], p["y"])))
    out = []
    for label, (x, y) in spots:
        cx, cy = mm._curb_point(x, y)
        out.append((label, cx, cy))
    return mm.all_hubs, out


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
    print("wrote %s: %d roads, %d overpass decks, %d buildings (%d dropped), %d areas, %d props, %.1f MB"
          % (args.out, info["roads"], info["spans"], info["buildings"], info["dropped"], info["polygons"],
             info["props"], info["bytes"] / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
