# Changelog

All notable changes to Amherst Run are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (1.0.0 is the first version with the whole map drivable end to end).

When preparing a release: move the items under "Unreleased" into a new `## [X.Y.Z] - YYYY-MM-DD` section,
set `__version__` in `game/__init__.py` to `X.Y.Z`, and update the link references at the bottom.

## [Unreleased]

### Added
- `tools/golden.py` records police chases (`police.csv`: boxing in a parked player, two police chasing a driving
  one, standing down) for the native game's parity tests.
- The baked map carries the job hubs, the Heritage Tour's landmark spots and the 5,610 real civic addresses
  (`HUBS`, `TOUR`, `ADDR`), and `tools/golden.py` records drop-point addresses, route lengths and the tours from each
  tour hub (`jobs.tsv`) for the native game's job tests.
- The baked map carries the VS race finishes (`SPRT`), and `tools/golden.py` records the item box spots downtown
  and the flight of a puck and a seeker (`items.tsv`) for the native game's battle tests.
- The baked map carries the rail ways and the train's run (`RAIL`, `TRAN`), and `tools/golden.py` records train block
  positions and push-outs (`train.tsv`).

## [1.0.3] - 2026-11-22
Traffic no longer gets stuck at all-way junctions, and the native C++ game's map gains the road graph and junction
rules its traffic drives by.

### Added
- The baked map carries the road graph the traffic drives on (`GRPH`: nodes and directed edges exactly as
  `game/roadgraph.py` builds them), and `tools/golden.py` records A* routes, nearest-node lookups and three
  civilian-driver runs (`paths.csv`, `nearest.csv`, `traffic.csv`) for the native game's parity tests.
- The baked map carries the junction rules (`JNCT`: lights, stop signs, give-way and all-way junctions, classified
  as the game does), and the golden traffic runs drive under them, with cars converging on a junction with lights,
  one with a stop sign and an all-way one.

### Fixed
- Traffic at an all-way junction could wait forever: two cars at their stop lines each counted the other, standing
  across the junction on its exit road, as blocking the way out. A stopped car facing into the junction no longer
  counts (`game/junctions.py` `_exit_blocked`); before, such cars were removed after 20 s as jammed.

## [1.0.2] - 2026-11-22
A fuller map for the native C++ game: every tree and post, and golden drives for its car physics. The Python game
itself is unchanged.

### Added
- The baked map (`amherst.amr`) has every prop: about 455,000 trees and 10,000 lamps, poles, signs, hydrants,
  gravestones, fences and parked-car blocks, planted in one fixed order (`tools/bake_native.py` `plant_everything`)
  so the map file and the golden drives have the same trees.
- `tools/golden.py` also records six scripted drives of player 1's car (`drive.csv`: into a house, up an overpass,
  a handbrake turn, a power slide, a hill, into a tree) for the native game's physics parity test.

### Fixed
- The baked map now carries the wall colour and height the Python renderer actually uses (per-building material
  colours and default heights), so the native game's buildings match.

## [1.0.1] - 2026-11-22
The map for the native C++ game, and the plan for it. The game itself is unchanged.

### Added
- `tools/bake_native.py` bakes the loaded map (graded terrain, roads, overpass decks, buildings, areas, all
  triangulated) into one binary file, `amherst.amr`, for the native C++ game (amherst-run-native). `tools/golden.py`
  writes golden files of what the Python game answers (surface heights on and off the decks) for that game's parity
  tests. Releases attach both, with their checksums.
- `docs/CPP_PORT_PLAN.md`: the plan for the native C++ version (homebrew Xbox One, Android, Batocera).

## [1.0.0] - 2026-11-22
Version 1: the roads flow. Smooth graded roads, working overpasses and on-ramps, cul-de-sacs, and Highway 104
U-turns at the map edges.

### Added
- Cul-de-sacs where two-way roads just stop (53 on the map, at the map edge and at real dead ends): a paved turning
  circle with a loop road round it, so you and the town's traffic can turn back. A bulb is left out where it would land
  on a building or across another road; at the map edge the road is cut back so the circle fits inside
  (`game/turnarounds.py`).
- Highway 104 U-turns at both map edges: the outgoing carriageway runs on past its end and swings round into the
  incoming one, so traffic and you can head back the other way.
- `tools/road_check.py` drives a probe along every road and reports anything that stops a car, sudden steps and very
  steep grades.
- `--start X,Y` starts the game on the road nearest a map point (metres), for playtesting a spot.

### Changed
- Roads are graded into the LiDAR ground at load (`game/grading.py`): narrow dips (stream gullies, ditches) are filled,
  short humps cut, and each road's profile smoothed, so roads no longer dip and pick up again where the survey shows the
  ground under a bridge. Busier roads are graded first and the roads that join them meet their level, so junctions and
  on-ramps have no steps. This replaces the old blend of the smooth grid under overpasses.
- Overpass decks are straight between their embankments, at least their clearance above the road below, with smooth
  ramps; deck pieces that touch are one bridge (Nappan Rd). Long bridges that cross a road (Highway 104 over Highway 2
  and the marsh) are now decks too, so the road below no longer cuts a notch in them. Far deck pieces skip their
  barriers and are culled to the view like road pieces.
- Power poles that stood in roads (67 of them blocked a lane, including on the Exit 3 overpass approach) are moved to
  the verge, and traffic no longer spawns on overpass ramps.

## [0.4.0] - 2026-11-21
More of the real landscape: real trees and ground shape from the 2020 LiDAR survey, power lines, streams and land use.

### Added
- More of the real landscape from OpenStreetMap (`tools/fetch_osm_extras.py` -> `data/osm_extras.json`): power lines
  with their wooden poles and steel towers and the wires strung between them (1,615 on the map), rivers, streams and
  ditches as water ribbons under the roads, land use as ground colour (farm fields, wetlands, meadows, grass, golf
  courses, sports pitches with their lines, cemeteries with rows of gravestones), and fences, walls and hedges.
- Real ground shape from the 2020 LiDAR survey: heights every 12.5 m instead of 25 m from the bare-earth model
  (`tools/fetch_lidar_ground.py`, which reads the survey's 8 m overview: about 20 tiles for the whole map). Road cuts,
  the rail embankment, river banks and the dam's drop are real. The land is drawn in 25 m cells with the fine ones
  within 75 m (about 20 more polygons a frame). Under overpasses the older smooth grid is blended in, because the
  survey includes the bridge embankments while the game builds its own ramps and decks. `tools/cog.py` can now read a
  GeoTIFF's overview levels.
- Real trees from the LiDAR survey: about 460,000 tree tops (`tools/fetch_lidar_trees.py` -> `data/lidar_trees.json`,
  1.7 MB) replace the random woods and the random street trees wherever the survey covers the map. Each stands where a
  real tree does, at its real height (capped at 24 m), off the roads and 3 m clear of buildings; they are planted area
  by area as you drive, and the area around the start is planted before the first frame. Real woods are thinner than
  the random ones were, so there are fewer polygons a frame, and loading is faster (no 15,000 random street trees).

### Fixed
- Loading is faster: custom buildings only check the roads near them for overlaps, and the heights are decoded at once.
- Hand-placed and mapped scenery no longer uses up the street-tree budget (it pushed out about 5,600 trees).

## [0.3.1] - 2026-11-21
Two player battle and VS race modes, the country roads east of town, and more of Amherst's real places.
(Version 0.3.0 was tagged but never released: its release checks failed on a flaky test, fixed here.)

### Added
- Open parking lots: 73 surface lots from OpenStreetMap (`tools/fetch_parking.py` -> `data/parking.json`, 23.8 ha)
  are drawn as paved areas with painted stall lines up close and count as road to drive on; driveway roads that ran
  through them are cut back to stubs at the lot edges (the mall, Walmart, the Superstore, the regional high school).
- Two downtown murals as simplified original panels: the North Nova Scotia Highlanders memorial on the Town Hall's
  east wall, and The Great Amherst Mystery on the LaPlanche St wall facing the lot towards Victoria St (placed
  approximately). A building's `mural` (design, facing, width, bottom, top) paints it on the wall facing that way.
- Two-player BATTLE (balloon battle downtown) and VS RACE (race to a random landmark under a light beacon) on the
  start screen, or `--vs battle` / `--vs sprint`: item boxes at junctions with original items (puck, seeker, oil slick,
  turbo can, ghost mode, triple puck), balloons, spin-outs, rams, per-player HUD with item window, balloons or
  distance and arrow, speed and radar; Tab switches top/bottom and left/right split; synthesized sound effects.
- Traffic is lighter and smarter: fewer cars where there is less road (default 16 downtown, ~5 on rural roads), new
  cars appear 150-230 m away, and drivers keep a speed-scaled gap and see cars crossing their path (AI-vs-AI crashes
  downtown in 90 s: 29 -> 3). `tools/traffic_check.py` measures it.
- The Pumping Station dam on the river east of town (reference photo + LiDAR: a ~6 m drop along a 50 m crest): the
  spillway with its falling water and white water below, the sluice, gate piers with catwalk and red handwheels, and
  the timber-baffled fish ladder down the north bank. Solid along its crest.
- The border welcome lighthouse moved to its real spot at Highway 104 Exit 1 (the civic address point; it stood by the
  information centre 320 m away) and rebuilt: white octagonal tower, red gallery, lantern and cap, red-doored porch,
  granite planter, the blue-and-gold welcome sign facing the off-ramp, and two flags.
- Two more homes from reference photos: a brick-and-cream two-storey on Penny Lane (front gable, porch, teal shutters,
  attached garage with dormer, purple-leaf plum) and a foursquare on Harding Ave (sunporch, an 80s silver-blue wagon
  and a dark hatchback in the driveway, cargo trailer, rear garage).
- `plinth_h` (a brick ground floor under siding), `leaf` colour on hand-placed trees, a garage door takes the `door`
  colour, and a boxy 80s `wagon` car model for parked cars.
- The map reaches further north-east (Highway 6 out toward Warren, Tyndal Road, East Amherst): 167 more road pieces
  and 350 LiDAR-found homes and outbuildings. The land-cover woods are downloaded for the whole map, so they cover it.
- The old church on Hastings Rd (reference photos, LiDAR footprint): a white clapboard meeting house with its gable
  end and door to the road, a plaque over the door, tall side windows, a graveyard and its big trees. Easter egg: stop
  by the white fence out front.
- Hand-placed scenery in `map_edits.json` props: `horse`, `gravestone`, and `fence` (from `lat`/`lon` to
  `lat2`/`lon2`); a prop with a `caption` says it once when you stop beside it. House fields `front_windows`,
  `plaque`, `window_h`.
- The map now reaches east of town around the rural loop: Church St out to Highway 204, Hastings Rd round to
  Highway 6 and back in along Victoria St E (383 new road pieces, joined to the town's roads). `tools/extend_map.py`
  grows the map without moving its origin, so map edits, heights and addresses still line up, and a re-download
  (`update_map.py`) adds the area again.
- Rural homes from LiDAR: OpenStreetMap maps few buildings out there, so `tools/find_homes.py` finds the house at each
  civic address from the LiDAR roof surface (flat, building-height blobs with open ground around them; tree crowns and
  hedgerows are rejected): 451 homes and their garages, sheds and barns, then measured like the rest.
- Two hand-modelled homes from reference photos: a white Cape Cod on Norman St (green roof, two front dormers, navy
  shutters, door with sidelights, gravel driveway with a dark grey crossover parked in it and a white arbour) and a
  grey single-storey house on Hastings Rd (LiDAR footprint, deck and steps, gravel loop drive, trees around the clearing).
- Parked cars in `map_edits.json` (`"cars": {"add": [...]}`): drawn like any car and solid to drive into.
- House details you can set per building: `front` (the compass bearing the front faces), `door`, `door_at`,
  `sidelights`, `shutters`.
- `tools/fetch_heights.py --only-new` measures just the buildings the heights file does not have yet.

### Changed
- CI now also tests Batocera's exact versions (Python 3.11, pygame 2.5.2, numpy 1.24.4) and macOS, compiles every
  Python file, runs weekly on its own, and probes Python 3.14, a known gap (no pygame wheels yet: it passes with a
  warning until pygame can be installed there, then runs every check).
- The real woods (NSTDB land cover) now grow everywhere on the map, not just near the start: their trees are made
  per 40 m prop cell the first time the game looks there, instead of all at load. Before, the street trees used up
  the whole prop budget, so the woods got almost no trees and the rural loop was bare grass. Every tree site comes
  from a hash of its place on a global 8 m grid, thinned so no two stand within 5 m, so the same trees appear on every
  visit whichever way you arrive. They keep clear of roads, buildings, water, rail, overpasses and every fixed prop
  (hand trees included). At most 8 trees per cell. Cells next to the car are made at once (so you hit them); farther
  ones are made one per frame, nearest first. The 3,000 most recent cells stay in memory; older ones are forgotten
  and made again the same if you come back.
- Land outside the town's zoning map counts as residential, so rural homes get house colours and roofs.
- Low single-storey walls get (shorter) windows on the front instead of none, and doors stay below the eaves.

### Fixed
- A battle test could fail depending on where the random start put the two cars (a building between them); the
  battle tests now use a fixed seed and a clear straight road.
- Hand-placed trees kept their position but got random sizes; they keep the `h` and `r` you give them now.
- Clapboard houses (including the hand-modelled ones) could get graffiti tags.
- A door in the middle of a long wall could vanish where the wall is cut into pieces for drawing.

## [0.3.0] - 2026-11-21
Tagged but not released: the release checks failed on a flaky battle test. Everything is in 0.3.1.

## [0.2.1] - 2026-11-17
Fixes for hills, roads and street signs.

### Fixed
- With real elevation on, buildings, roads and props behind a hill no longer show through it, and walls sunk into a
  slope no longer show below the grass: a per-column hill horizon is worked out each frame and anything beyond a crest
  is clipped at it (about 1 ms a frame, and nothing on flat ground).
- Buildings on slopes sit on their highest corner, with the walls running down to the land on the downhill side,
  instead of being buried on the uphill side.
- Every building is off the roads: the map editor's fix-all now cuts driveways back to the building they run into and
  trims a building back to the street edge when it cannot be slid clear (0 buildings on roads on the real map).
- Stop signs, traffic-light poles and railway crossbucks no longer stand in the road at junctions (20 of 62 did):
  they step out to the side or back along their road until they are clear.
- The map editor dropped the `_note` lines (where a change came from) when it saved; they are kept now.

## [0.2.0] - 2026-11-17
Amherst, measured and rebuilt: real building heights and roofs from LiDAR, house types with close-up detail, and the
town's heritage buildings modelled from the Canadian Register of Historic Places and reference photos.

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
- Two demolished heritage buildings placed approximately from the register and reference photos: the 1906 Bank of
  Montreal (one tall storey of rough red sandstone with arched windows, beside the Dominion Building) and the c.1911
  Hickman St school (red brick on a white base, hipped roof, arched centre). Landmarks no longer get graffiti.
- New building parts: polygon footprints (`sides`), `cone` roofs, `dormers`, `plinth` base courses, `+wrap` verandas.
- Shop fronts on downtown blocks within 70 m: display windows between piers, a door, a sign band and upper-storey windows.
- House types (`game/archetypes.py`): garage, mini-home, bungalow, cape, two-storey, apartment, picked from LiDAR height,
  roof pitch, footprint and zoning. Within 45 m houses get foundations, trimmed windows per storey, a front door on the
  street side, wall-coloured gable ends with attic windows and front verandas. `"arch"` in map_edits.json sets a type by
  hand. Gable ends are now drawn in the wall colour on every building, and family homes no longer get graffiti.
- README: a new picture gallery and a "How Amherst was built" section (data layers, the LiDAR method, heritage
  sources, what wins over what). `tools/readme_shots.py` regenerates every README picture.

### Changed
- The clock tower is on the old post office (50 Victoria St E), not the Court House: the heritage register lists no
  tower on the 1888 Court House.
- Measured walls are typically 1.9 m lower than the old height guesses, so streets look lower and roofs more varied.
- A house's front door is found up to 50 m from a street (some heritage houses sit well back).

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

[Unreleased]: https://github.com/jeremylegere-wq/amherst-run/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/jeremylegere-wq/amherst-run/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/jeremylegere-wq/amherst-run/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/jeremylegere-wq/amherst-run/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/jeremylegere-wq/amherst-run/compare/v0.4.0...v1.0.0
[0.4.0]: https://github.com/jeremylegere-wq/amherst-run/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/jeremylegere-wq/amherst-run/compare/v0.2.1...v0.3.1
[0.3.0]: https://github.com/jeremylegere-wq/amherst-run/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/jeremylegere-wq/amherst-run/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jeremylegere-wq/amherst-run/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jeremylegere-wq/amherst-run/releases/tag/v0.1.0
