"""In-game build mode (key B): drive down a street and drop buildings beside you.

A green ghost building follows the car on its right (or left) side with its front facing the street. Cycle
presets, turn it, switch sides, then place it. Placed buildings are saved straight into data/custom_buildings.json
(as latitude/longitude), so they are there next time too. See docs/BUILDING.md.
"""

from .builder import (DEFAULT_PATH, PRESETS, STYLES, compass_of, load_doc, make_building, resolve, save_doc, unproject)

GHOST_COLOUR = (120, 255, 150)
GAP = 1.5                      # metres between the kerb and the building front
ORDER = [("preset", k) for k in PRESETS] + [("style", k) for k in STYLES]   # types to cycle through


class BuildMode:
    def __init__(self, world, renderer, path=None):
        self.world, self.r3d = world, renderer
        self.path = path or getattr(world, "custom_path", None) or DEFAULT_PATH
        self.doc = load_doc(self.path)
        self.active = False
        self.preset_i = 0
        self.turn = 0.0                    # extra rotation in degrees
        self.side = 1                      # 1: build on the right of the car, -1: on the left
        self.ghost = None                  # world index of the preview building
        self.placed = []                   # (world index, spec) placed this session, for undo
        self.problem = ""
        self.message = ""

    @property
    def preset(self):
        """Name of the selected building type (a preset or a style)."""
        return ORDER[self.preset_i][1]

    @property
    def key(self):
        """{"preset": name} or {"style": name}: how a spec asks for the selected type."""
        kind, name = ORDER[self.preset_i]
        return {kind: name}

    # ------------------------------------------------------------ controls
    def toggle(self):
        self.active = not self.active
        if not self.active:
            self._drop_ghost()
            self.message = ""
        return self.active

    def cycle(self, d):
        self.preset_i = (self.preset_i + d) % len(ORDER)

    def rotate(self, deg):
        self.turn = (self.turn + deg) % 360.0

    def flip(self):
        self.side = -self.side

    # ------------------------------------------------------------ placement maths
    def _spec(self, car):
        settings, _ = resolve(self.key)
        rx, ry = car.right
        road = self.world.road_at(car.x, car.y, getattr(car, "z", 0.0))
        half = (road["width"] / 2.0) if road else 4.5
        off = half + GAP + settings["depth"] / 2.0
        x, y = car.x + rx * self.side * off, car.y + ry * self.side * off
        facing = (compass_of(-rx * self.side, -ry * self.side) + self.turn) % 360.0
        return {**self.key, "x": x, "y": y, "facing": round(facing, 1)}

    def _build(self, car):
        return make_building(self._spec(car), self.world.meta, self.world.roads)

    def update(self, car):
        """Move the ghost to the car (call once per frame while active)."""
        if not self.active:
            return
        b, warns = self._build(car)
        self.problem = warns[0] if warns else ""
        b["colour"] = list(GHOST_COLOUR)
        b["ghost"] = True
        b.pop("material", None)
        if self.ghost is None:
            self.ghost = self.world.add_building(b)
        else:
            self.world.set_building(self.ghost, b)
        self.r3d.refresh_building(self.ghost)

    def place(self, car):
        """Keep the ghost as a real building and save it. Returns True if placed."""
        if not self.active or self.ghost is None:
            return False
        b, warns = self._build(car)
        if warns:
            self.message = "Can't place: " + warns[0]
            return False
        spec = self._spec(car)
        lat, lon = unproject(self.world.meta, spec.pop("x"), spec.pop("y"))
        spec.update({"name": "%s %d" % (self.preset, len(self.doc["buildings"]) + 1),
                     "lat": round(lat, 6), "lon": round(lon, 6)})
        self.world.set_building(self.ghost, b)
        self.r3d.refresh_building(self.ghost)
        self.doc["buildings"].append(spec)
        self.placed.append((self.ghost, spec))
        self.ghost = None                                  # the next update() makes a fresh ghost
        self._save("Placed " + spec["name"])
        return True

    def undo(self):
        if not self.placed:
            self.message = "Nothing to undo"
            return False
        idx, spec = self.placed.pop()
        self.world.remove_building(idx)
        self.r3d.refresh_building(idx)
        if spec in self.doc["buildings"]:
            self.doc["buildings"].remove(spec)
        self._save("Removed " + spec["name"])
        return True

    # ------------------------------------------------------------ helpers
    def _drop_ghost(self):
        if self.ghost is not None:
            self.world.remove_building(self.ghost)
            self.r3d.refresh_building(self.ghost)
            self.ghost = None

    def _save(self, msg):
        try:
            save_doc(self.path, self.doc)
            self.message = msg
        except OSError as e:
            self.message = "Could not save: %s" % e

    def hud_lines(self):
        s, _ = resolve(self.key)
        lines = ["BUILD: %s  %dx%d m  %s roof   (%d saved)" % (self.preset.replace("_", " ")[:28], s["width"], s["depth"], s["roof"],
                                                                 len(self.doc["buildings"])),
                 "[ ] type   , . turn   X side   ENTER place   BKSP undo   B done"]
        note = self.problem and ("! " + self.problem) or self.message
        if note:
            lines.append(note)
        return lines
