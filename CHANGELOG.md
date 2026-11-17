# Changelog

All notable changes to Amherst Run are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (0.x while the game is still being tuned).

When preparing a release: move the items under "Unreleased" into a new `## [X.Y.Z] - YYYY-MM-DD` section,
set `__version__` in `game/__init__.py` to `X.Y.Z`, and update the link references at the bottom.

## [Unreleased]

### Added
- Real building heights and roof shapes from LiDAR (NRCan HRDEM, 2020 Nova Scotia survey): `tools/fetch_heights.py`
  measures every building (4,956 of 5,160) and fits flat, gable (either direction) or hip roofs; the game applies
  `data/building_heights.json` under the hand edits and over the zoning guesses. `tools/cog.py` reads the province-wide
  cloud GeoTIFFs tile by tile with the standard library + numpy (no new dependency).
- Roofs can run across a building (`ridge_across`), for cross-gabled houses.
- Heritage buildings modelled from the Canadian Register of Historic Places (facts only): Court House (54 Victoria St E,
  no tower), old post office (50 Victoria St E) with the clock tower, Dominion Building in light grey sandstone, Bank of
  Nova Scotia (79), 1897 sandstone shop (91), railway station (hip roof), Armoury (finally found: building tagged
  military by Acadia St), Trinity-St. Stephen's (castellated bell tower), First Baptist (twin towers, red sandstone),
  Christ Church (no steeple). New building settings `tower`, `steeple`, `storeys`, `shopfront`.
- Buildings modelled from reference photos: 233 Victoria St E (two-storey Classical Revival main house = OSM building,
  plus a storey-and-a-half wing with a dormer and a garage wing), Moffatt House (96 Church St: mansard roof, three
  dormers, two-storey bay, porch), 177 Victoria St E (white Queen Anne with a stone turret and round bay under cone
  roofs, a wrap-around veranda, hipped roof with a dormer).
- New building parts: polygon footprints (`sides`), `cone` roofs, `dormers`, `plinth` base courses, `+wrap` verandas.
- Shop fronts on downtown blocks within 70 m: display windows between piers, a door, a sign band and upper-storey windows.
- House types (`game/archetypes.py`): garage, mini-home, bungalow, cape, two-storey, apartment, picked from LiDAR height,
  roof pitch, footprint and zoning. Within 45 m houses get foundations, trimmed windows per storey, a front door on the
  street side, wall-coloured gable ends with attic windows and front verandas. `"arch"` in map_edits.json sets a type by
  hand. Gable ends are now drawn in the wall colour on every building, and family homes no longer get graffiti.

## [0.1.0] - 2026-11-15
First public release.

### Added
- The game now starts in a driveway in a residential street off Willow St, nose towards a hand-modelled house: light blue siding, steep shingle gable roof, brick chimney, wooden deck, red shed, paved
  driveway, big maples (map_edits.json + custom_buildings.json).
- Building `chimney` setting (gable/hip roofs); custom buildings can be as low as 0.5 m (decks, hedges, fences).
- `map_edits.json` takes a hand-written `spawn` (lat/lon/bearing) and `props.add` (trees); the editor keeps them.
- `tools/bench_town.py --at X,Y` parks the player somewhere other than the spawn (use 394.6,-835.8 for downtown).
- Real house numbers: parcel addresses come from the Nova Scotia Civic Address File (`tools/fetch_addresses.py`,
  `data/addresses.json`, ~90% of drops), falling back to made-up numbers.
- The parcel hub is the historic Dominion Building (98 Victoria St E, now the Town Hall).
- Weather and time of day: overcast, coastal fog, golden hour and snow (`--weather`, F4 cycles), as style data on top of
  both styles. `tools/bench_town.py` takes `--style` and `--weather`.
- Traffic lights, stop signs and right of way for AI traffic (`game/junctions.py`). Cars stop on red/yellow at
  OpenStreetMap signals (same cycle as the drawn signal heads), make a full stop at OSM stop signs, give way from the
  minor road (lane < side < main, or the stem of a T), take turns at equal 4-ways, give way to oncoming traffic when
  turning left, and do not enter a junction whose exit is jammed. Police and players are not bound by it.
- 2, 3 and 4 player split screen. With 3 players, player 1 gets the whole top half. Each player drives their own
  original vehicle: boxy retro SUV (yellow, white roof), compact crossover (white), mid-size SUV (grey), quad cab pickup
  (black). Sizes, weight and power differ (`MODELS` in `game/car.py`). Pads go to the last players first.
- Bumper hop and drift boost (LB/RB, Left/Right Shift): hop, steer at speed to start a power slide, hold to charge
  (blue, orange, purple sparks), release for a boost with a flame out of the back. Works in 1 player too.
- Map editor (`python tools/map_editor.py`): move, reshape, delete and add buildings and roads with the mouse, find and
  fix buildings that sit on roads or inside each other. Edits go to `data/map_edits.json` and survive re-downloading the
  map. `--check` and `--fix-all` work without a window. See docs/EDITOR.md.
- Start screen: **1 Player** (the full game) or **2 Player** (split screen free roam, no police, no jobs, no damage), with
  keyboard, gamepad and mouse/touch. ESC returns to it. `--players 1|2` or `--no-menu` skips it.
- Two player split screen: each player has a chase camera and a half-width view (`game/twoplayer.py`). Player 1 uses
  W/A/S/D + Space (R respawns); player 2 uses arrows + Right Ctrl or Keypad 0 (Backspace respawns). With two gamepads
  pad 1 drives player 1 and pad 2 drives player 2; with one pad it drives player 2. Traffic is kept around both players.
- A freight train now runs along the real rail line every few minutes (`game/train.py`): a red locomotive and 6-11 cars.
  It is solid and shoves cars out of the way. `--no-train` turns it off.
- Real woods: `python tools/fetch_landcover.py` downloads the NS Topographic Database land cover (treed areas, tree lines,
  orchards; Open Government Licence - Nova Scotia) into `data/landcover.json`, and the game fills those areas with trees
  (`game/landcover.py`). Without the file nothing changes. Prop budget raised from 11,000 to 15,000.
- Parcel runs now name a made-up house number (odd/even by side, ~9 m per lot) on the street, e.g. "34 Victoria St". These are not real addresses.
- Cop-free mode: `--no-cops` (or press C in game). No police, no wanted level, no busting; Getaway jobs and court-house
  fines are switched off while it is on.
- Zoning-based building looks: `tools/zoning_from_pdf.py` reads the town's zoning map (PDF, registered to our roads) into
  `data/zoning.json`; `game/zoning.py` gives plain OSM buildings a consistent look per zone (clapboard homes with shingle
  roofs in General Residential, low vinyl mini homes, brick downtown / mixed use / institutional, corrugated box stores
  in Highway Commercial, sheet-metal sheds in Industrial, pale units in the Business Park, the mall in Comprehensive
  Development). Landmarks, buildings with real height/levels and anything you built are never changed. `--no-zoning` turns it off.
- Three new building styles from photos: `brick_supermarket`, `ribbed_shopping_mall` (175 m wide), `grey_box_store`;
  new `corrugated` material. Builder width/depth limit raised from 80 m to 200 m.
- Street detail: Canadian-style road paint by road class, tan gravel roads, concrete and red-brick sidewalks, zebra
  crosswalks, stop bars and stop signs, signal heads that cycle, rail crossing signs, hydrants, benches and bins.
  Stops, signals, crossings and rail crossings come from OpenStreetMap nodes (`marks` in the map file); roads now carry
  NSRN `rc` (road class), `surface` and `lanes`. See `game/streetdetail.py`.
- 28 building styles from photos of real Amherst buildings (`data/building_styles.json`): use them in build mode
  (they follow the presets) or with `"style"` in `custom_buildings.json`.
- Hills: real ground heights. `tools/fetch_elevation.py` downloads them into `data/elevation.json` (also run by
  `update_map.py`); the game draws the land as shaded terrain and puts roads, buildings, trees, markers, overpasses and
  the camera on it. Cars roll downhill and labour uphill. With no file the world stays flat.
- Real streets from the Nova Scotia Road Network (NSRN): about 800 roads with names, one-ways and highway
  overpasses. `tools/nsrn_to_roads.py` rebuilds them; `data/nsrn_amherst_extract.csv` is the small Amherst slice
  of the provincial file, and `tools/osm_to_map.py` applies it automatically.
- GTA-style round minimap that rotates with the car and shows streets, highways, buildings, water, parks, police and
  job targets. The whole-town map (M) now names the streets and gold-marks the highways.
- Street-name sign and a "MAX" speed-limit sign on the HUD.
- Three highway overpasses: Highway 104 over Highway 2 (Exit 4), Highway 6 over Highway 104 (Exit 3) and
  MacDonald Rd over Highway 104. Cars rise up the ramps, cars on different levels do not collide, and the camera
  follows.
- Your own buildings: `data/custom_buildings.json`, presets, gable/hip/mansard roofs, an in-game build mode (B) and
  `python -m game.builder` to check a file. See `docs/BUILDING.md`.
- `data/speed_overrides.json` to set real posted limits by street name.
- Retro open-world driving game set in Amherst, Nova Scotia: arcade car physics, a 3D polygon chase view in
  a cel-shaded "street" style (plus the original flat-shaded `retro` style), top-down and whole-town map views.
- Map pipeline from OpenStreetMap (`tools/fetch_osm.py`, `tools/osm_to_map.py`) with real landmarks
  (Court House, Victoria Square, churches, museum, armoury, wind turbines) and a bundled Amherst map.
- Living town: traffic on the real road network, police chases, wanted level, busted/wrecked states, radar.
- Jobs generated from the road graph: Parcel Run, Getaway, Heritage Tour and paying fines at the Court House.
- Widescreen 16:9 (320x180) fullscreen picture, never stretched.
- Xbox-style controller support (steer, throttle/brake, handbrake, view, map, respawn, quit).
- Android support through Pydroid 3 (`play_android.py`) with on-screen touch controls.
- Batocera launcher (`AmherstRun.sh`).
- `--version`, `--no-joy`, `--touch` and `--debug-input` command-line options.
- GitHub Actions CI and a tag-driven release workflow.

### Changed
- The bundled map now covers downtown Amherst (Court House, churches, banks, Town Hall, train station) with NSRN streets.
- `update_map.py` re-downloads OpenStreetMap and rebuilds the map in one step.
- Traffic obeys speed limits (50 km/h in town, 80 on rural arterials, 100 on Highway 104) with a little variation
  per driver. The NSRN has no speed field, so these limits are estimates from road class and distance from downtown.
- Map roads now come from the NSRN instead of OpenStreetMap (buildings, parks and landmarks still come from OSM).
- AI traffic steers and changes speed smoothly instead of snapping between targets.

### Fixed
- `tools/fetch_elevation.py` crashed on its first real run (`Surface.convert` needs a window). Real elevation is now
  downloaded (`data/elevation.json`) and on by default; `--flat` turns it off. Terrain lookups are faster.
- Loading the map took ~3 s longer with the 70 building edits (each edit rescanned every building); now 0.07 s.
- Cars and props next to a wall no longer get painted behind it (or show through it) when seen at a slant.
- 70 buildings that sat on roads in the real Amherst map were pushed clear (`data/map_edits.json`, made with
  `tools/map_editor.py --fix-all`). 10 are left for hand editing.
- Traffic no longer rear-ends a queue: braking for a stopped car ahead is no longer smoothed (it lagged ~0.5 s).
- Two human cars hitting each other crashed the game (`Car` had no `kind`). Fixed, with a regression test.
- On Batocera the Xbox pad numbers its buttons from 1 (A=1, Start=8), so pressing A on the start screen hit the "B = quit"
  button and the game closed with no error. Button numbers now come from SDL's controller config (`game/padmap.py`).
- Errors are now written to `amherst-run-crash.log` (game folder, home, /userdata) and shown on screen (Batocera and Android hide them), and 2 player/menu code no longer
  depends on newer pygame calls (`get_instance_id`, `FINGERDOWN`).
- Buildings, cars and trees drew through each other: the far-to-near sort of scene objects had been lost from the renderer.
  It is back, with a test (`test_objects_are_painted_far_to_near`) so it cannot disappear unnoticed.

- The sandstone-corner bank entry in the landmark file matched every bank; it now matches by name only.
- Buildings no longer draw through one another or through cars: each wall piece is depth-sorted on its own.

[Unreleased]: https://github.com/jeremylegere-wq/amherst-run/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jeremylegere-wq/amherst-run/releases/tag/v0.1.0
