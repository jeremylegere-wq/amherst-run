# C++ port plan (homebrew: Xbox One Developer Mode, Android, Batocera, desktop)

Status: proposal, 22 Nov 2026. Nothing here is built yet. The Python game (v1.0.0) stays the reference and keeps
shipping while the port grows.

## Goal and limits

- A native C++ version of Amherst Run that runs at a steady 30 fps (60 where it can) on an Xbox One in Developer Mode,
  on mid-range Android phones, on Batocera and on desktops.
- Homebrew, not a store release: the Xbox build is a UWP package sideloaded onto consoles in Developer Mode. The Xbox
  Store no longer takes UWP games, and a store release would mean the GDK through ID@Xbox, which is out of scope.
- Same game, same look: the 320x180 internal picture scaled up with nearest-neighbour, the street (cel-shaded) and
  retro styles, the real Amherst map. All art, names and sounds stay original.

## Stack (each library needs Jeremy's OK before it is added; see "Dependencies")

| Part | Choice | Why |
|---|---|---|
| Language / build | C++17, CMake | Builds with Visual Studio (UWP), the Android NDK, GCC/Clang (Linux, Batocera, macOS) |
| Window, input, audio | **SDL2** (2.30.x) | The only library covering Xbox UWP, Android, Linux and desktops. SDL3 dropped UWP; its Xbox path is GDK only |
| Graphics | **OpenGL ES 3.0** | Native on Android and Batocera boards; on Xbox UWP SDL2 runs it through ANGLE (to Direct3D 11, inside the feature level 10.1 that UWP games get) |
| Maths | small in-house vec/mat header | Avoids a dependency; the game needs little |
| Text | in-house bitmap font from the HUD's existing look | No font library |
| Data | one baked binary file made by Python (below) | No JSON parser or numpy in the game |

Controller buttons come from SDL's GameController API (named buttons), which keeps the `game/padmap.py` rule: never
hard-code raw button numbers.

## Where the code lives

Two repositories on your GitHub, with this one as the data source:

- **This repository (`amherst-run`, Python)** keeps the map pipeline, the map data and the reference game, and gains
  `tools/bake_native.py` (data -> `amherst.amr`) and `tools/golden.py` (writes the parity test files below). Each
  release attaches `amherst.amr` and `golden.zip` as release files, next to the Python zip.
- **A new repository (for example `amherst-run-native`, C++)** holds the C++ game. It pins the map by version: a
  `MAP_VERSION` file names the `amherst-run` release whose `amherst.amr` and golden files it downloads (CI checks the
  SHA-256). Updating the map is a one-line change there, so a map fix never breaks the C++ build by surprise.

```
amherst-run-native/
  CMakeLists.txt
  MAP_VERSION         which amherst-run release's amherst.amr + golden files to use
  src/        core/ (maths, clock, input, file), world/, render/, sim/ (car, ai, junctions, town), game/ (modes, hud, menus)
  shaders/
  platform/   uwp/ (Visual Studio project, appx manifest), android/ (Gradle project from SDL's template)
  tests/      C++ unit tests + parity tests against the golden files
  tools/fetch_map.py  downloads and checks the pinned amherst.amr + golden files
```

The file format is the contract between the two: its version number goes up whenever the layout changes, and the
C++ loader refuses a file it does not understand.

## The baked map file (`amherst.amr`)

Everything `World.load` works out today is computed once in Python and written as a binary file, so the C++ game loads
in well under a second and the hard geometry code (grading, overpass decks, turnarounds, lot cutting, map edits) is
not ported at all.

- Little-endian, versioned header `AMR1`, then tagged chunks (`TAG`, length, payload); unknown chunks are skipped.
- Chunks: `META` (bounds, spawn, attribution), `TERR` (graded heights, int16 cm, 12.5 m grid), `ROAD` (polylines, type,
  width, one-way, speed, name index), `SPAN` (overpass decks and ramp heights), `GRPH` (road graph nodes and edges),
  `JUNC` (per-edge junction controls), `BLDG` (outlines, heights, roofs, colours, house type, landmark details),
  `PROP` (lamps, signs, poles, parked cars), `TREE` (LiDAR + woods trees, by 40 m cell), `LOTS`, `AREA`, `WATR`,
  `RAIL`, `ADDR` (civic numbers), `NAME` (string table).
- `tools/bake_native.py` loads the map exactly as the Python game does (`World.load`), so map edits, custom buildings
  and every fix land in the bake automatically. A test checks the bake round-trips (counts, bounds, sample heights).

## Parity testing

The Python tests describe how the game behaves. To keep the C++ game the same, Python writes golden files and C++
tests compare against them:

- car physics: a scripted 20 s input sequence -> positions/speeds every 0.1 s (tolerance a few cm);
- road graph: shortest paths between fixed pairs of nodes;
- junction rules: who may go, for recorded situations;
- heights: `height_at` on and off overpass decks at sample points;
- job generation with a fixed seed.

## Phases

Each phase ends with something you can run, and a commit; benchmark before and after renderer or AI work, as now.

**Phase 0 - toolchain spike (do first: it carries the risk)**
- New repository with the C++ skeleton: SDL2 window, GLES3 context, 320x180 render target scaled up, an Xbox pad moving a cube.
- Builds: Linux (this machine), Android APK (NDK, on Linux), Xbox UWP package. The UWP build needs **Windows with
  Visual Studio 2022 (UWP workload)**; GitHub Actions' Windows runners can build the package in CI.
- Deploy the package to the Xbox through Dev Home / the Device Portal; confirm it runs as a *Game* (not an App) so it
  gets up to 5 GB of memory and the larger CPU/GPU share.
- Done when: the same commit runs on Linux, a phone and the Xbox with the pad working.

**Phase 1 - drive the real map**
- `bake_native.py` + loader; terrain mesh in chunks; roads, overpasses, lots, water; extruded buildings with roofs;
  chase camera; car physics ported from `game/car.py` and `game/collision.py` with the parity test.
- A depth buffer replaces the painter's sort, wall-order nudging and hill clipping in `render3d.py`.
- Done when: you can drive from the start house to the Highway 104 U-turns on the Xbox at 30 fps or better.

**Phase 2 - the living town**
- Road graph queries, AI drivers, junction rules, traffic spawning, police and wanted level, damage, radar/minimap.
- Ported from `ai.py`, `junctions.py`, `town.py`, `roadgraph.py`, `minimap.py`.

**Phase 3 - the game**
- HUD, menus, pause, jobs (`missions.py`, real addresses), split screen 2-4 players (`twoplayer.py`), battle/VS mode
  and items (`battle.py`, `items.py`), the train, synthesized sounds (`sfx.py`).

**Phase 4 - the look**
- Street style as shaders: two-tone cel lighting, ink outlines, see-through hard shadows, fog bands, weather grades;
  house details, shop fronts, steeples, murals, trees (instanced), street detail, retro style switch.

**Phase 5 - phones**
- Touch controls (`touch.py`), Android back button, lifecycle (pause on background), a quality setting.

## Python module -> C++ mapping

| Python | C++ | Notes |
|---|---|---|
| `world.py`, `terrain.py`, `grading.py`, `turnarounds.py`, `mapedits.py`, `parking.py`, `extras.py`, `lidar*.py`, `landcover.py`, `zoning.py`, `builder.py`, `archetypes.py` | `world/` loader only | Their work happens in the bake |
| `render3d.py`, `streetdetail.py`, `props.py`, `murals.py` | `render/` | Rewritten for the GPU, not translated line by line |
| `car.py`, `collision.py` | `sim/car`, `sim/collision` | Straight port + parity test |
| `roadgraph.py`, `ai.py`, `junctions.py`, `town.py`, `train.py` | `sim/` | Straight port; graph comes baked |
| `missions.py`, `addresses.py` | `game/missions` | |
| `main.py`, `menu.py`, `twoplayer.py`, `battle.py`, `items.py`, `minimap.py`, `touch.py`, `sfx.py`, `padmap.py` | `game/`, `core/input` | `padmap.py` becomes SDL GameController |
| `buildmode.py` | later, maybe never | Editing stays in the Python tools |

## Dependencies (need approval)

- SDL2 2.30.x (zlib licence), vendored or as a CMake subproject.
- ANGLE only comes with SDL2's UWP setup; nothing extra to add by hand on the other platforms.
- No other libraries planned.

## Risks and open questions

- **Developer Mode access**: needs a Partner Center developer account (one-off fee) and the console switched to
  Developer Mode; players need their own Developer Mode consoles. Check Microsoft's current Dev Mode terms before
  Phase 0.
- **UWP builds need Windows.** Either a Windows PC with Visual Studio or CI on Windows runners.
- **ANGLE on Xbox**: SDL2's UWP + ANGLE path is older; Phase 0 proves it. Fallback: a small Direct3D 11 backend for
  the UWP build only.
- **SDL2 is in maintenance mode** (SDL3 is current). Fine for years, but new SDL features will not come to it.
- **Scope**: about 11,500 lines of game code. The bake removes roughly a third (world building); the renderer is the
  largest rewrite.
- **Two repositories**: map changes reach the C++ game only through a new `amherst-run` release and a
  `MAP_VERSION` bump. Decide when Python stops getting features (suggestion: after Phase 3, Python becomes the data
  pipeline and the reference only).
