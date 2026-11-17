"""Amherst Run map editor: fix streets and buildings with the mouse, add new buildings and roads, find overlaps.

    python tools/map_editor.py                 # opens data/amherst_map.json in a window
    python tools/map_editor.py --check         # just list the overlaps (no window)
    python tools/map_editor.py --fix-all       # move every building off the roads it sits on, save, no window

Nothing in the converted map is changed. Your edits are saved to data/map_edits.json (moved/deleted/reshaped
OpenStreetMap buildings and roads, new roads) and data/custom_buildings.json (buildings you add), and the game applies
them every time it loads. Re-downloading the map keeps them. See docs/EDITOR.md for the full key list (F1 in the editor).
"""
import argparse
import copy
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import mapedits as M  # noqa: E402
from game.builder import PRESETS, STYLES, centroid, compass_of, footprint, load_doc, make_building, nearest_road, project, save_doc, unproject  # noqa: E402

ORDER = [("preset", k) for k in PRESETS] + [("style", k) for k in STYLES]
MATERIALS = (None, "sandstone", "brick", "clapboard", "granite")
ROAD_TYPES = ("main", "side", "lane")
ROAD_DEFAULT = {"main": (12.0, 60), "side": (8.0, 50), "lane": (5.0, 30)}
HELP = (
    "MOUSE  left click: select / drag to move   drag a corner: reshape   Shift+click an edge: add a corner",
    "       right or middle drag (or WASD): pan   wheel: zoom",
    "SELECTED  Del: delete (or the picked corner)   arrows: nudge (Shift = 2 m)   [ ]: rotate (Shift = 15 deg)",
    "       PgUp/PgDn: building height   M: material   T: road type   + -: road width   E: road name",
    "ADD    B: new building (, . pick type, [ ] turn, click to place, Esc stop)   R: new road (click points, Enter)",
    "FIX    N / Shift+N: next / previous overlap   F: push the selected building off the road (nothing selected: all)",
    "VIEW   1 roads  2 buildings  3 lanes  4 land  5 problems   O: re-check   Ctrl+Z: undo   Ctrl+S: save   F1: help",
)
BG = (34, 52, 40)
COL = {"main": (236, 200, 90), "side": (190, 190, 196), "lane": (120, 124, 132)}


KEEP_SECTIONS = ("spawn", "props")      # map_edits.json sections the editor does not edit: saved back unchanged


def build_state(map_path, edits_path, custom_path):
    with open(map_path, encoding="utf-8") as f:
        data = json.load(f)
    for b in data["buildings"]:
        b["_ok"] = M.centre(b["points"])
        b["_orig"] = copy.deepcopy({k: v for k, v in b.items() if not k.startswith("_")})
    for r in data["roads"]:
        r["_ok"] = M.road_mid(r["points"])
        r["_orig"] = copy.deepcopy({k: v for k, v in r.items() if not k.startswith("_")})
    doc = M.load(edits_path)
    report = M.apply(data, doc, mark=True)
    customs = load_doc(custom_path)
    return data, doc, customs, report


class Editor:
    def __init__(self, map_path, edits_path, custom_path):
        self.map_path, self.edits_path, self.custom_path = map_path, edits_path, custom_path
        self.data, doc, self.custom_doc, report = build_state(map_path, edits_path, custom_path)
        self.kept = {k: doc[k] for k in KEEP_SECTIONS if doc and doc.get(k)}   # edited by hand, not in the editor
        self.meta = self.data["meta"]
        self.blds, self.roads = self.data["buildings"], self.data["roads"]
        self.customs = [{"spec": s, "b": None} for s in self.custom_doc.get("buildings", [])]
        for c in self.customs:
            self._rebuild(c)
        self.undo = []
        self.sel = None                      # ("b"|"r"|"c", index)
        self.vertex = None
        self.tool = None                     # None, "build", "road"
        self.build_i = 0
        self.build_turn = 0.0
        self.road_pts = []
        self.problems = []
        self.prob_i = -1
        self.layers = {"roads": True, "buildings": True, "lanes": True, "land": True, "problems": True}
        self.zoom = 1.6
        self.cx, self.cy = 0.0, 0.0
        self.drag = None
        self.message = "; ".join(report[:1]) + "   F1 = help"
        self.dirty = False
        self.typing = None
        self.help = False
        self._bb_all()
        self.recheck()

    # ------------------------------------------------------------------ data helpers
    def _rebuild(self, c):
        try:
            c["b"], _w = make_building(c["spec"], self.meta, self.data["roads"])
        except (ValueError, TypeError, KeyError):
            c["b"] = None

    def _bb_all(self):
        for b in self.blds:
            b["_bb"] = M.bbox(b["points"])
        for r in self.roads:
            r["_bb"] = M.bbox(r["points"])

    def item(self, ref):
        kind, i = ref
        return {"b": self.blds, "r": self.roads, "c": self.customs}[kind][i]

    def points_of(self, ref):
        it = self.item(ref)
        return it["b"]["points"] if ref[0] == "c" else it["points"]

    def push_undo(self, ref):
        kind, i = ref
        it = self.item(ref)
        snap = copy.deepcopy(it["spec"]) if kind == "c" else copy.deepcopy({k: v for k, v in it.items() if k != "_bb"})
        self.undo.append(("set", ref, snap))
        self.dirty = True

    def do_undo(self):
        if not self.undo:
            self.message = "Nothing to undo"
            return
        op = self.undo.pop()
        if op[0] == "set":
            _, ref, snap = op
            if ref[0] == "c":
                self.customs[ref[1]]["spec"] = snap
                self._rebuild(self.customs[ref[1]])
            else:
                coll = self.blds if ref[0] == "b" else self.roads
                coll[ref[1]].clear()
                coll[ref[1]].update(snap)
                coll[ref[1]]["_bb"] = M.bbox(coll[ref[1]]["points"])
        elif op[0] == "pop":
            coll = {"r": self.roads, "c": self.customs}[op[1]]
            coll.pop()
            self.sel = None
        self.message = "Undone"
        self.recheck()

    def touch(self, ref):
        """Call after changing an item's geometry."""
        kind, i = ref
        if kind == "b":
            self.blds[i]["_bb"] = M.bbox(self.blds[i]["points"])
        elif kind == "r":
            self.roads[i]["_bb"] = M.bbox(self.roads[i]["points"])

    def recheck(self):
        idx = M.Index(self.blds, self.roads, skip_lanes=not self.layers["lanes"])
        self.problems = idx.all_problems()
        self.index = idx

    # ------------------------------------------------------------------ view
    def to_screen(self, x, y, size):
        return ((x - self.cx) * self.zoom + size[0] / 2, (y - self.cy) * self.zoom + size[1] / 2)

    def to_world(self, sx, sy, size):
        return ((sx - size[0] / 2) / self.zoom + self.cx, (sy - size[1] / 2) / self.zoom + self.cy)

    def focus(self, x, y):
        self.cx, self.cy = x, y

    # ------------------------------------------------------------------ picking
    def pick(self, wx, wy):
        tol = 6.0 / self.zoom
        for i in range(len(self.customs) - 1, -1, -1):
            c = self.customs[i]
            if c["b"] is not None and M.inside(wx, wy, c["b"]["points"]):
                return ("c", i)
        best = None
        for i, b in enumerate(self.blds):
            if b.get("_deleted"):
                continue
            x0, y0, x1, y1 = b["_bb"]
            if x0 <= wx <= x1 and y0 <= wy <= y1 and M.inside(wx, wy, b["points"]):
                area = (x1 - x0) * (y1 - y0)
                if best is None or area < best[0]:
                    best = (area, i)
        if best:
            return ("b", best[1])
        near = None
        for j, r in enumerate(self.roads):
            if r.get("_deleted") or (r["type"] == "lane" and not self.layers["lanes"]):
                continue
            x0, y0, x1, y1 = r["_bb"]
            if wx < x0 - 20 or wx > x1 + 20 or wy < y0 - 20 or wy > y1 + 20:
                continue
            d = min(M.seg_dist(wx, wy, a[0], a[1], b2[0], b2[1]) for a, b2 in zip(r["points"], r["points"][1:])) \
                - r.get("width", 6.0) / 2.0
            if d < tol and (near is None or d < near[0]):
                near = (d, j)
        return ("r", near[1]) if near else None

    def vertex_at(self, wx, wy):
        if self.sel is None:
            return None
        tol = 7.0 / self.zoom
        for k, p in enumerate(self.points_of(self.sel)):
            if math.hypot(p[0] - wx, p[1] - wy) < tol:
                return k
        return None

    # ------------------------------------------------------------------ edit actions
    def move_points(self, ref, dx, dy):
        if ref[0] == "c":
            c = self.customs[ref[1]]
            x, y = (c["spec"]["x"], c["spec"]["y"]) if "x" in c["spec"] else project(self.meta, c["spec"]["lat"], c["spec"]["lon"])
            self._set_custom_pos(c, x + dx, y + dy)
            return
        for p in self.points_of(ref):
            p[0] += dx
            p[1] += dy
        self.touch(ref)

    def _set_custom_pos(self, c, x, y):
        lat, lon = unproject(self.meta, x, y)
        c["spec"].pop("x", None), c["spec"].pop("y", None)
        c["spec"]["lat"], c["spec"]["lon"] = round(lat, 7), round(lon, 7)
        self._rebuild(c)

    def rotate(self, deg):
        if self.sel is None or self.sel[0] == "r":
            return
        self.push_undo(self.sel)
        if self.sel[0] == "c":
            c = self.customs[self.sel[1]]
            facing = c["spec"].get("facing", c["b"] and self._facing_of(c))
            c["spec"]["facing"] = round((float(facing or 0) + deg) % 360.0, 1)
            self._rebuild(c)
        else:
            pts = self.points_of(self.sel)
            cx, cy = M.centre(pts)
            a = math.radians(deg)
            for p in pts:
                dx, dy = p[0] - cx, p[1] - cy
                p[0], p[1] = cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)
            self.touch(self.sel)

    def _facing_of(self, c):
        x, y = centroid(c["b"])
        near = nearest_road(self.roads, x, y)
        return compass_of(near[1][0] - x, near[1][1] - y) if near else 0.0

    def delete_selected(self):
        if self.sel is None:
            return
        kind, i = self.sel
        if self.vertex is not None and kind != "c" and len(self.points_of(self.sel)) > (2 if kind == "r" else 3):
            self.push_undo(self.sel)
            self.points_of(self.sel).pop(self.vertex)
            self.vertex = None
            self.touch(self.sel)
        else:
            self.push_undo(self.sel)
            if kind == "c":
                self.customs[i]["_deleted"] = True
                self.customs[i]["b"] = None
            else:
                self.item(self.sel)["_deleted"] = True
            self.sel = None
        self.recheck()

    def set_height(self, d):
        if self.sel and self.sel[0] in ("b", "c"):
            self.push_undo(self.sel)
            if self.sel[0] == "c":
                c = self.customs[self.sel[1]]
                h = c["spec"].get("height", c["b"]["height"])
                c["spec"]["height"] = round(max(2.0, min(60.0, h + d)), 1)
                self._rebuild(c)
            else:
                b = self.blds[self.sel[1]]
                h = b.get("height") or 6.0
                b["height"] = round(max(2.0, min(60.0, h + d)), 1)

    def cycle_material(self):
        if self.sel and self.sel[0] == "b":
            self.push_undo(self.sel)
            b = self.blds[self.sel[1]]
            cur = b.get("material")
            nxt = MATERIALS[(MATERIALS.index(cur) + 1) % len(MATERIALS)] if cur in MATERIALS else MATERIALS[1]
            if nxt:
                b["material"] = nxt
            else:
                b.pop("material", None)
            self.message = "Material: %s" % (nxt or "plain")

    def cycle_road_type(self):
        if self.sel and self.sel[0] == "r":
            self.push_undo(self.sel)
            r = self.roads[self.sel[1]]
            r["type"] = ROAD_TYPES[(ROAD_TYPES.index(r["type"]) + 1) % 3] if r["type"] in ROAD_TYPES else "side"
            r["width"], r["speed"] = ROAD_DEFAULT[r["type"]]
            self.message = "Road type: %s (%.0f m)" % (r["type"], r["width"])
            self.recheck()

    def road_width(self, d):
        if self.sel and self.sel[0] == "r":
            self.push_undo(self.sel)
            r = self.roads[self.sel[1]]
            r["width"] = round(max(3.0, min(30.0, r["width"] + d)), 1)
            self.recheck()

    def fix(self):
        """F: push the selected building off its roads, or every problem building when nothing is selected."""
        targets = []
        if self.sel and self.sel[0] == "b":
            targets = [self.sel[1]]
        elif self.sel is None:
            targets = sorted({p["building"] for p in self.problems if p["kind"] == "road"})
        if not targets:
            self.message = "Select a building to fix (or select nothing to fix all)"
            return
        fixed = stuck = trimmed = cut = 0
        for i in targets:
            ref = ("b", i)
            self.push_undo(ref)
            moved, still = M.push_clear(self.index, i)
            if moved > 0 and not still:
                fixed += 1
                self.touch(ref)
                continue
            self.undo.pop()
            # cannot slide it clear: cut back the driveways/lanes that run into it, then trim it to the street edge
            pts = self.blds[i]["points"]
            for j in self.index.roads_near(pts):
                road = self.roads[j]
                if road.get("type") != "lane" or self.index.intrusion(pts, j)[0] <= M.MIN_OVERLAP:
                    continue
                self.push_undo(("r", j))
                new = M.cut_road_outside(road["points"], [pts])
                if new is None:
                    road["_deleted"] = True
                else:
                    road["points"] = new
                self.index._along.pop(j, None)
                self.touch(("r", j))
                cut += 1
            if not any(self.index.intrusion(pts, j)[0] > M.MIN_OVERLAP for j in self.index.roads_near(pts)):
                fixed += 1
                continue
            self.push_undo(ref)
            if M.trim_clear(self.index, i):
                trimmed += 1
                fixed += 1
            else:
                stuck += 1
                self.undo.pop()
            self.touch(ref)
        gone = 0
        if self.sel is None:                                 # fix all: drop buildings that sit wholly inside another
            for p in self.problems:
                if p["kind"] == "building":
                    a, b = self.blds[p["building"]], self.blds[p["other"]]
                    for small, big in ((a, b), (b, a)):
                        if not small.get("_deleted") and M.swallowed(small["points"], big["points"]):
                            k = p["building"] if small is a else p["other"]
                            self.push_undo(("b", k))
                            small["_deleted"] = True
                            gone += 1
                            break
        self.message = "Fixed %d (%d trimmed to the street edge, %d driveways cut back), removed %d duplicate(s), " \
                       "could not fix %d" % (fixed, trimmed, cut, gone, stuck)
        self.recheck()

    # ------------------------------------------------------------------ adding
    def add_spec(self, x, y):
        kind, name = ORDER[self.build_i]
        spec = {kind: name, "name": "%s %d" % (name, len(self.customs) + 1)}
        lat, lon = unproject(self.meta, x, y)
        spec.update({"lat": round(lat, 7), "lon": round(lon, 7)})
        if self.build_turn:
            spec["facing"] = round(self.build_turn % 360.0, 1)
        return spec

    def ghost(self, wx, wy):
        spec = self.add_spec(wx, wy)
        try:
            return make_building(spec, self.meta, self.roads)[0]
        except (ValueError, TypeError, KeyError):
            return None

    def place_building(self, wx, wy):
        spec = self.add_spec(wx, wy)
        self.customs.append({"spec": spec, "b": None})
        self._rebuild(self.customs[-1])
        self.undo.append(("pop", "c"))
        self.dirty = True
        self.sel = ("c", len(self.customs) - 1)
        self.message = "Placed %s" % spec["name"]

    def finish_road(self):
        if len(self.road_pts) >= 2:
            w, sp = ROAD_DEFAULT["side"]
            self.roads.append({"type": "side", "width": w, "name": "", "speed": sp, "rc": "LO",
                               "points": [[round(x, 1), round(y, 1)] for x, y in self.road_pts], "_new": True})
            self.roads[-1]["_bb"] = M.bbox(self.roads[-1]["points"])
            self.undo.append(("pop", "r"))
            self.sel = ("r", len(self.roads) - 1)
            self.dirty = True
            self.message = "Road added (T type, + - width, E name)"
        self.road_pts = []
        self.tool = None
        self.recheck()

    def snap(self, wx, wy):
        tol = 9.0 / self.zoom
        best = None
        for r in self.roads:
            if r.get("_deleted"):
                continue
            x0, y0, x1, y1 = r["_bb"]
            if wx < x0 - tol or wx > x1 + tol or wy < y0 - tol or wy > y1 + tol:
                continue
            for p in (r["points"][0], r["points"][-1]):
                d = math.hypot(p[0] - wx, p[1] - wy)
                if d < tol and (best is None or d < best[0]):
                    best = (d, p)
        return (best[1][0], best[1][1]) if best else (wx, wy)

    # ------------------------------------------------------------------ saving
    def save(self):
        doc = M.empty()
        doc.update(copy.deepcopy(self.kept))
        for b in self.blds:
            if "_ok" not in b:
                continue
            orig = b["_orig"]
            if b.get("_deleted"):
                doc["buildings"]["delete"].append([round(b["_ok"][0], 2), round(b["_ok"][1], 2)])
                continue
            rep = {}
            if b["points"] != orig["points"]:
                rep["points"] = [[round(p[0], 2), round(p[1], 2)] for p in b["points"]]
            for k in M.BUILDING_FIELDS:
                if b.get(k) != orig.get(k) and k in b:
                    rep[k] = b[k]
            if rep:
                rep["at"] = [round(b["_ok"][0], 2), round(b["_ok"][1], 2)]
                if b.get("_note"):
                    rep["_note"] = b["_note"]                  # where the change came from (register, photos...)
                doc["buildings"]["replace"].append(rep)
        for r in self.roads:
            if r.get("_new"):
                if not r.get("_deleted"):
                    add = {k: r[k] for k in M.ROAD_FIELDS if k in r}
                    add["points"] = [[round(p[0], 2), round(p[1], 2)] for p in r["points"]]
                    doc["roads"]["add"].append(add)
                continue
            orig = r["_orig"]
            if r.get("_deleted"):
                doc["roads"]["delete"].append([round(r["_ok"][0], 2), round(r["_ok"][1], 2)])
                continue
            rep = {}
            if r["points"] != orig["points"]:
                rep["points"] = [[round(p[0], 2), round(p[1], 2)] for p in r["points"]]
            for k in M.ROAD_FIELDS:
                if r.get(k) != orig.get(k) and k in r:
                    rep[k] = r[k]
            if rep:
                rep["at"] = [round(r["_ok"][0], 2), round(r["_ok"][1], 2)]
                if r.get("_note"):
                    rep["_note"] = r["_note"]
                doc["roads"]["replace"].append(rep)
        try:
            M.save(self.edits_path, doc)
            self.custom_doc["buildings"] = [c["spec"] for c in self.customs if not c.get("_deleted")]
            save_doc(self.custom_path, self.custom_doc)
            self.message = "Saved %d edits + %d own buildings" % (M.count(doc), len(self.custom_doc["buildings"]))
            self.dirty = False
        except OSError as e:
            self.message = "Could not save: %s" % e
        return doc


# ====================================================================== window
def run_gui(ed):
    import pygame
    pygame.init()
    screen = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
    pygame.display.set_caption("Amherst Run map editor")
    font = pygame.font.Font(None, 20)
    small = pygame.font.Font(None, 17)
    clock = pygame.time.Clock()
    start = next((l for l in ed.data.get("landmarks", []) if l.get("kind") == "cenotaph"), None)
    ed.focus(start["x"], start["y"]) if start else ed.focus(*M.centre([[0, 0], [1, 1]]))

    def txt(msg, pos, col=(240, 240, 240), f=font, bg=True):
        img = f.render(msg, True, col)
        if bg:
            pygame.draw.rect(screen, (14, 18, 24), img.get_rect(topleft=pos).inflate(8, 4))
        screen.blit(img, pos)

    running = True
    while running:
        size = screen.get_size()
        mx, my = pygame.mouse.get_pos()
        wx, wy = ed.to_world(mx, my, size)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.VIDEORESIZE:
                pass
            elif e.type == pygame.MOUSEWHEEL:
                before = ed.to_world(mx, my, size)
                ed.zoom = max(0.08, min(14.0, ed.zoom * (1.18 ** e.y)))
                after = ed.to_world(mx, my, size)
                ed.cx += before[0] - after[0]
                ed.cy += before[1] - after[1]
            elif e.type == pygame.MOUSEBUTTONDOWN:
                mx, my = e.pos
                wx, wy = ed.to_world(mx, my, size)
                if e.button in (2, 3):
                    ed.drag = ("pan", mx, my, ed.cx, ed.cy)
                elif e.button == 1:
                    if ed.tool == "build":
                        ed.place_building(wx, wy)
                    elif ed.tool == "road":
                        ed.road_pts.append(ed.snap(wx, wy))
                    else:
                        k = ed.vertex_at(wx, wy)
                        shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                        if k is not None:
                            ed.vertex = k
                            ed.push_undo(ed.sel)
                            ed.drag = ("vertex", k)
                        elif ed.sel is not None and shift and ed.sel[0] != "c" and _insert_vertex(ed, wx, wy):
                            pass
                        else:
                            hit = ed.pick(wx, wy)
                            ed.sel, ed.vertex = hit, None
                            if hit:
                                ed.push_undo(hit)
                                ed.drag = ("move", wx, wy)
            elif e.type == pygame.MOUSEBUTTONUP and e.button in (1, 2, 3):
                moved = ed.drag is not None and ed.drag[0] in ("move", "vertex")
                if moved and ed.undo and ed.drag[0] == "move":
                    pass
                ed.drag = None
                if moved:
                    ed.recheck()
            elif e.type == pygame.KEYDOWN:
                if ed.typing is not None:
                    if e.key == pygame.K_RETURN:
                        ed.push_undo(ed.sel)
                        ed.roads[ed.sel[1]]["name"] = ed.typing
                        ed.typing = None
                    elif e.key == pygame.K_ESCAPE:
                        ed.typing = None
                    elif e.key == pygame.K_BACKSPACE:
                        ed.typing = ed.typing[:-1]
                    elif e.unicode and e.unicode.isprintable():
                        ed.typing += e.unicode
                    continue
                ctrl = e.mod & pygame.KMOD_CTRL
                shift = e.mod & pygame.KMOD_SHIFT
                if ctrl and e.key == pygame.K_z:
                    ed.do_undo()
                elif ctrl and e.key == pygame.K_s:
                    ed.save()
                elif e.key == pygame.K_F1:
                    ed.help = not ed.help
                elif e.key == pygame.K_ESCAPE:
                    if ed.tool or ed.sel:
                        ed.tool, ed.sel, ed.road_pts, ed.vertex = None, None, [], None
                    else:
                        running = False
                elif e.key == pygame.K_b:
                    ed.tool = None if ed.tool == "build" else "build"
                    ed.sel = None
                elif e.key == pygame.K_r:
                    ed.tool, ed.road_pts, ed.sel = ("road", [], None)
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and ed.tool == "road":
                    ed.finish_road()
                elif e.key == pygame.K_BACKSPACE and ed.tool == "road" and ed.road_pts:
                    ed.road_pts.pop()
                elif e.key == pygame.K_DELETE:
                    ed.delete_selected()
                elif e.key == pygame.K_COMMA and ed.tool == "build":
                    ed.build_i = (ed.build_i - 1) % len(ORDER)
                elif e.key == pygame.K_PERIOD and ed.tool == "build":
                    ed.build_i = (ed.build_i + 1) % len(ORDER)
                elif e.key == pygame.K_LEFTBRACKET:
                    if ed.tool == "build":
                        ed.build_turn -= 15
                    else:
                        ed.rotate(-15 if shift else -5)
                elif e.key == pygame.K_RIGHTBRACKET:
                    if ed.tool == "build":
                        ed.build_turn += 15
                    else:
                        ed.rotate(15 if shift else 5)
                elif e.key == pygame.K_PAGEUP:
                    ed.set_height(0.5)
                elif e.key == pygame.K_PAGEDOWN:
                    ed.set_height(-0.5)
                elif e.key == pygame.K_m:
                    ed.cycle_material()
                elif e.key == pygame.K_t:
                    ed.cycle_road_type()
                elif e.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    ed.road_width(1.0)
                elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    ed.road_width(-1.0)
                elif e.key == pygame.K_e and ed.sel and ed.sel[0] == "r":
                    ed.typing = ed.roads[ed.sel[1]].get("name", "")
                elif e.key == pygame.K_f:
                    ed.fix()
                elif e.key == pygame.K_o:
                    ed.recheck()
                    ed.message = "%d problems" % len(ed.problems)
                elif e.key == pygame.K_n and ed.problems:
                    ed.prob_i = (ed.prob_i + (-1 if shift else 1)) % len(ed.problems)
                    p = ed.problems[ed.prob_i]
                    ed.focus(*p["at"])
                    ed.zoom = max(ed.zoom, 4.0)
                    ed.sel = ("b", p["building"])
                    ed.message = "Problem %d of %d: building %s" % (ed.prob_i + 1, len(ed.problems),
                                                                      "on a road" if p["kind"] == "road" else "inside another building")
                elif e.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                    name = ("roads", "buildings", "lanes", "land", "problems")[e.key - pygame.K_1]
                    ed.layers[name] = not ed.layers[name]
                    if name == "lanes":
                        ed.recheck()
                elif ed.sel and e.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
                    step = 2.0 if shift else 0.5
                    dx = (e.key == pygame.K_RIGHT) - (e.key == pygame.K_LEFT)
                    dy = (e.key == pygame.K_DOWN) - (e.key == pygame.K_UP)
                    ed.push_undo(ed.sel)
                    ed.move_points(ed.sel, dx * step, dy * step)
                    ed.recheck()
        # held keys: pan
        keys = pygame.key.get_pressed()
        if ed.typing is None:
            pan = 600.0 / ed.zoom / 30.0
            ed.cx += ((keys[pygame.K_d]) - (keys[pygame.K_a])) * pan
            ed.cy += ((keys[pygame.K_s]) - (keys[pygame.K_w])) * pan
        if ed.drag:
            if ed.drag[0] == "pan":
                ed.cx = ed.drag[3] - (mx - ed.drag[1]) / ed.zoom
                ed.cy = ed.drag[4] - (my - ed.drag[2]) / ed.zoom
            elif ed.drag[0] == "move" and ed.sel:
                dx, dy = wx - ed.drag[1], wy - ed.drag[2]
                ed.move_points(ed.sel, dx, dy)
                ed.drag = ("move", wx, wy)
            elif ed.drag[0] == "vertex" and ed.sel and ed.sel[0] != "c":
                p = ed.points_of(ed.sel)[ed.drag[1]]
                p[0], p[1] = wx, wy
                ed.touch(ed.sel)
        _draw(ed, screen, size, wx, wy, txt, small, font)
        pygame.display.flip()
        clock.tick(30)
    if ed.dirty:
        ed.save()                                   # never lose work: closing the window saves
    pygame.quit()


def _insert_vertex(ed, wx, wy):
    pts = ed.points_of(ed.sel)
    closed = ed.sel[0] == "b"
    segs = list(zip(range(len(pts)), pts, pts[1:] + (pts[:1] if closed else [])))
    best = min(((M.seg_dist(wx, wy, a[0], a[1], b[0], b[1]), i) for i, a, b in segs), default=None)
    if best and best[0] < 8.0 / ed.zoom:
        ed.push_undo(ed.sel)
        pts.insert(best[1] + 1, [wx, wy])
        ed.vertex = best[1] + 1
        ed.touch(ed.sel)
        return True
    return False


def _draw(ed, screen, size, wx, wy, txt, small, font):
    import pygame
    screen.fill(BG)
    W, H = size
    z = ed.zoom
    x0, y0 = ed.to_world(0, 0, size)
    x1, y1 = ed.to_world(W, H, size)

    def vis(bb):
        return not (bb[2] < x0 or bb[0] > x1 or bb[3] < y0 or bb[1] > y1)

    def S(p):
        return ((p[0] - ed.cx) * z + W / 2, (p[1] - ed.cy) * z + H / 2)

    if ed.layers["land"]:
        for key, col in (("water", (60, 104, 160)), ("parks", (60, 120, 66)), ("woods", (36, 78, 44))):
            for it in ed.data.get(key, []) if key != "woods" else _woods(ed):
                pts = it["points"]
                if vis(M.bbox(pts)):
                    pygame.draw.polygon(screen, col, [S(p) for p in pts])
    if ed.layers["roads"]:
        for r in sorted(ed.roads, key=lambda r: {"lane": 0, "side": 1, "main": 2}.get(r.get("type"), 1)):
            if r.get("_deleted") or not vis(r["_bb"]) or (r["type"] == "lane" and not ed.layers["lanes"]):
                continue
            w = max(1, int(r.get("width", 6.0) * z))
            col = COL.get(r["type"], COL["side"])
            if r.get("_new"):
                col = (120, 220, 255)
            pygame.draw.lines(screen, col, False, [S(p) for p in r["points"]], w)
    bad = {p["building"] for p in ed.problems} | {p["other"] for p in ed.problems if p["kind"] == "building"}
    if ed.layers["buildings"]:
        for i, b in enumerate(ed.blds):
            if b.get("_deleted") or not vis(b["_bb"]):
                continue
            col = (196, 120, 96) if b.get("material") in ("brick", "sandstone") else (176, 150, 130)
            if b.get("edited") or b.get("height") != b["_orig"].get("height"):
                col = (214, 176, 90)
            pts = [S(p) for p in b["points"]]
            pygame.draw.polygon(screen, col, pts)
            pygame.draw.polygon(screen, (60, 40, 40), pts, 1)
        for c in ed.customs:
            if c.get("_deleted") or c["b"] is None:
                continue
            pts = [S(p) for p in c["b"]["points"]]
            pygame.draw.polygon(screen, (80, 190, 190), pts)
            pygame.draw.polygon(screen, (20, 70, 70), pts, 2)
    if ed.layers["problems"]:
        for p in ed.problems:
            b = ed.blds[p["building"]]
            if vis(b["_bb"]):
                pygame.draw.polygon(screen, (255, 40, 40), [S(q) for q in b["points"]], 3)
            if p["kind"] == "road":
                sx, sy = S(p["at"])
                pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(sy)), max(3, int(2 * z)), 2)
    if ed.sel is not None:
        try:
            pts = ed.points_of(ed.sel)
            sp = [S(p) for p in pts]
            if ed.sel[0] == "r":
                pygame.draw.lines(screen, (255, 255, 0), False, sp, 3)
            else:
                pygame.draw.polygon(screen, (255, 255, 0), sp, 3)
            for k, p in enumerate(sp):
                if ed.sel[0] != "c":
                    pygame.draw.rect(screen, (255, 120, 0) if k == ed.vertex else (255, 255, 255),
                                     (p[0] - 4, p[1] - 4, 8, 8))
        except (IndexError, TypeError):
            ed.sel = None
    if ed.tool == "build":
        g = ed.ghost(wx, wy)
        if g:
            pygame.draw.polygon(screen, (120, 255, 150), [S(p) for p in g["points"]], 3)
    if ed.tool == "road" and ed.road_pts:
        pts = [S(p) for p in ed.road_pts] + [S(ed.snap(wx, wy))]
        pygame.draw.lines(screen, (120, 220, 255), False, pts, 3)
    # status
    lines = []
    if ed.tool == "build":
        lines.append("ADD BUILDING: %s   (, . type   [ ] turn   click = place   Esc = stop)" % ORDER[ed.build_i][1].replace("_", " "))
    elif ed.tool == "road":
        lines.append("NEW ROAD: click points (snaps to road ends)   Enter = finish   Backspace = undo point   Esc = cancel")
    elif ed.sel:
        lines.append(_describe(ed))
    lines.append("%d overlaps%s   %s" % (len(ed.problems), "  (red outlines, N = next)" if ed.problems else "",
                                           "UNSAVED - Ctrl+S" if ed.dirty else "saved"))
    if ed.message:
        lines.append(ed.message)
    if ed.typing is not None:
        lines.append("Road name: %s_   (Enter = ok, Esc = cancel)" % ed.typing)
    for i, ln in enumerate(lines):
        txt(ln, (8, 8 + i * 22))
    if ed.help:
        for i, ln in enumerate(HELP):
            txt(ln, (8, H - 24 * (len(HELP) - i) - 6), (255, 240, 180), small)
    else:
        txt("F1 = help", (W - 82, H - 24), (200, 210, 220), small)


def _woods(ed):
    return ed.data.get("woods") or []


def _describe(ed):
    kind, i = ed.sel
    if kind == "r":
        r = ed.roads[i]
        return "ROAD %s  %s  %.0f m wide   (T type, + - width, E name, drag corners, Del)" % (r.get("name") or "(no name)", r["type"], r["width"])
    if kind == "c":
        c = ed.customs[i]
        return "MY BUILDING %s   (drag, [ ] turn, PgUp/PgDn height, Del)" % c["spec"].get("name", "")
    b = ed.blds[i]
    return "BUILDING %s  height %s  material %s   (drag, [ ] turn, PgUp/PgDn height, M material, F fix, Del)" % (
        b["tags"].get("name", "") or b["tags"].get("building", ""), b.get("height", "auto"), b.get("material", "plain"))


# ====================================================================== command line
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=os.path.join(ROOT, "data", "amherst_map.json"))
    ap.add_argument("--check", action="store_true", help="list overlaps and exit")
    ap.add_argument("--fix-all", action="store_true", help="move buildings off roads, save, exit")
    ap.add_argument("--lanes", action="store_true", help="also check small service lanes")
    args = ap.parse_args()
    base = os.path.dirname(os.path.abspath(args.map))
    ed = Editor(args.map, os.path.join(base, M.EDITS_NAME), os.path.join(base, "custom_buildings.json"))
    if args.lanes:
        ed.layers["lanes"] = True
        ed.recheck()
    if args.check or args.fix_all:
        roadp = [p for p in ed.problems if p["kind"] == "road"]
        print("%d buildings on roads, %d inside other buildings" % (len({p["building"] for p in roadp}),
                                                                   sum(1 for p in ed.problems if p["kind"] == "building")))
        for p in ed.problems[:40]:
            b = ed.blds[p["building"]]
            print("  at (%.0f, %.0f) %s %s" % (p["at"][0], p["at"][1], p["kind"], b["tags"].get("name", "")))
        if args.fix_all:
            ed.sel = None
            ed.fix()
            ed.save()
            print(ed.message)
        return
    run_gui(ed)


if __name__ == "__main__":
    main()
