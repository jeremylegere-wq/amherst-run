# Project: Amherst Run (working title)

A retro open-world arcade driving game (cel-shaded street look, with a chunky flat-shaded retro option).
Driving only, no on-foot gameplay. The map is a simplified version of Amherst, Nova Scotia,
built from OpenStreetMap data.

## Hard rules
- Python 3 + pygame only. Must run smoothly on a basic laptop (target 30 fps).
- Render to a 320x224 surface, then scale up (nearest-neighbour) to the window.
- Limited palette feel: flat-shaded or small indexed textures, chunky polygons.
- Keep polygon counts low. Profile before adding anything expensive.
- All art, names, cars, sounds and missions are ORIGINAL. No copyrighted assets, brands or names from other games.
- Map data comes from OpenStreetMap (ODbL). Keep an attribution line in the credits/README: "Map data (c) OpenStreetMap contributors".
- Do NOT use or scrape Google Maps data.
- Arcade driving feel, not simulation. Fun first, realism second.

## Art direction
- Default look is the "street" style (STYLES in game/render3d.py): cel-shaded two-tone lighting, dark ink
  outlines on buildings and cars, saturated colours, deep-blue sky with cartoon clouds, light sidewalks,
  see-through hard shadows, ribbon windows, and a chunky outlined italic HUD (game/main.py).
- Street charm: tree-lined streets (blobby two-tone canopies, outlined trunks, tree shadows), lamp posts on
  main roads, original procedural graffiti tags on ~30% of longer walls, chunky cartoon cars (big wheels,
  tapered cabin, headlights). Props come from OSM trees/lamps plus procedural placement (game/props.py).
- Original look only: never copy characters, logos, fonts, HUD artwork, graffiti pieces or names from other games.
- The chunky flat-shaded "retro" style stays available with --style retro. Add new visual features
  as style data where possible so both styles keep working, and benchmark before/after.

## Amherst world notes
- Real landmarks live in data/landmarks_amherst.json and are applied by tools/landmarks.py during conversion.
  Buildings are matched by OSM name/tags near a point (fallback: nearest building within 45 m); the converter
  prints a report - fix the JSON when it says NOT FOUND or picks the wrong building. Jeremy knows the town:
  ask him before "correcting" a landmark.
- In: red sandstone/brick downtown (380 m around the court house), Court House (45.83315, -64.21318, waymarking.com)
  (54 Victoria St E, 1888; NO tower - the clock tower is on the old post office, 50 Victoria St E), Dominion
  Building/post office, banks, churches with steeples, Victoria Square (lawn, paths, tree ring, World Wars
  Memorial cenotaph), County Museum, Armoury (battlements), Welcome Centre + lighthouse prop,
  wind turbines on the skyline (17 real turbines: 15 on the marsh ~3 km west, 2 east; thewindpower.net).
- Out for now (driving-only game): walk-in interiors, NPC conversations, lockpicking, mining, binoculars.
  The Sackville radio towers were dismantled in 2014, so they are not on today's skyline.
- Mission hooks for M5 (stored as "role" on buildings): Dominion Building = parcel/delivery hub;
  Court House = pay off your wanted level; Museum = return collectibles found around town.
- Town is ~12 km2. Default fetch is a 6x6 km square centred on 45.8260, -64.2180 (downtown, south end, Highway 104).
  The first real download (14 Nov 2026) used an older, wrong default centre 1.8 km south and stopped just short of
  Victoria St, so downtown landmarks reported OUTSIDE; re-run tools/fetch_osm.py --convert to get downtown.
- Real-map facts learned: no trees or lamps are mapped in OSM (all props are procedural); banks/post offices are
  often POI nodes inside buildings (now matched); many buildings carry business names - never show them on screen
  (landmark labels are generic: Bank, Post Office, Church).

## Project layout
```
amherst-run/
  CLAUDE.md
  README.md
  requirements.txt
  data/            # raw OSM export (amherst.osm), generated map files
  tools/           # converters and editors (osm_to_map.py, map_editor.py, fetch_landcover.py, etc.)
  game/            # main.py, menu.py, twoplayer.py, padmap.py, car.py, collision.py, world.py, render3d.py, roadgraph.py,
                   # ai.py, town.py, train.py, props.py, missions.py, zoning.py, landcover.py, mapedits.py, builder.py
  assets/          # original textures, sounds
  tests/
```

## Workflow
- One milestone per session. Finish, run it, test it, commit, then move on.
- Commit to git at every working state with a clear message.
- Keep functions small and commented where the maths is non-obvious.
- After each milestone, update the "Status" section below.
- Ask before adding any dependency beyond pygame and numpy.

## Milestones

### M0 - Setup
- [x] Project folder, requirements.txt (pygame, numpy)
- [x] git repo (initialised 15 Nov 2026 on branch main)
- [ ] venv (do locally when migrating)
- [x] 320x224 scaled window, fixed timestep loop, FPS counter

### M1 - Map pipeline
- [x] tools/fetch_osm.py downloads and converts Amherst in one command (written and tested offline with mocked network; the chat sandbox cannot reach OSM)
- [x] First real download converted (south Amherst + Highway 104: 722 roads, 2,982 buildings, 68 one-ways, 9 bridges)
- [x] Downtown is in the current map (court house, Victoria Square, churches, banks, museum matched). The local
      data/amherst.osm is still the OLD wrong-centre download (git-ignored), so do not re-convert from it: run
      update_map.py (re-downloads) or change the current map through data/map_edits.json.
- [x] tools/osm_to_map.py: parse roads, buildings, rail, water into compact JSON (multipolygon relations not yet stitched)
- [x] Convert lat/lon to local metres, simplify geometry, tag road types (main, side, lane)
- [x] Debug top-down viewer showing the whole town (M key)

### M2 - Drivable top-down prototype
- [x] Arcade car physics (accel, brake, steering, drift/grip, handbrake)
- [x] Camera follows car; roads and buildings drawn from map data
- [x] Simple collisions with buildings and map edge
- [x] Collisions slide along walls (game/collision.py)
- [ ] Tune handling until it feels fun (needs hands on a real keyboard)

### M3 - Retro 3D renderer
- [x] Polygon renderer at 320x224 (decided: true 3D maths + flat polygons in pure pygame, game/render3d.py; spike benchmark below)
- [x] Road surface, flat-shaded buildings, sky bands, parallax hills, banded distance fog, 200 m draw distance
- [x] Chase camera behind car (yaw lag, speed pull-back, pulls in if it would sit inside a building)
- [ ] Confirm 30 fps on the target laptop (sandbox numbers are far under budget; run tools/bench_render.py locally)
- [x] Chunked world: only nearby grid cells are gathered, culled and drawn (roads cut into 20 m pieces)

### M4 - Living town
- [x] Road graph built from map geometry (junctions, T-junction snapping, bridges, one-way, A*) - game/roadgraph.py
- [x] Traffic cars: right-hand lanes, corner and car-ahead braking, spawn/despawn around the player - game/ai.py, game/town.py
- [x] Pedestrian-free for now (keep scope small)
- [x] Police: path chase, direct pursuit when in sight, box-in arrests, heat that drains when you hide
- [x] Wanted level (0-4), damage, BUSTED / WRECKED states, radar, HUD
- [x] Traffic lights / stop signs / junction right-of-way (game/junctions.py)
- [ ] Tune chase difficulty by hand (numbers are in game/town.py and game/ai.py)

### M5 - Missions
- [x] Jobs generated from the road graph at landmark hubs (game/missions.py) - no hand-written scripts needed,
      so they work on the real map: hubs come from building "role"s in the landmark file + Victoria Square
- [x] Parcel Run (post office): 1-3 addresses by street name, stop at each, some fragile (fail on 25 damage)
- [x] Getaway (banks): three stars, lose the police within 2 minutes
- [x] Heritage Tour (square/museum): checkpoint race past the landmarks
- [x] Court House: pay $100 per star to clear your wanted level; busted costs $100; cash + time bonus
- [x] Mission HUD: timer, objective line, direction arrow + distance, cash, hub hints, banners; beacons in 3D,
      on the radar (target sticks to the edge) and on the maps
- [x] tools/autopilot.py drives real physics through jobs to check time limits are fair (careful driver has 15-25% spare)
- [ ] Save cash/progress between sessions (M6 save/load)
- [ ] More job types: timed race between two towns-folk, tailing a car, chase-down (ram a fleeing car)

### M6 - Polish
- [ ] Original sound effects and music (chiptune-style)
- [ ] Menus, pause, save/load
- [x] Amherst landmarks (court house, square + cenotaph, churches, post office, banks, museum, armoury, welcome
  centre lighthouse, wind turbines; sandstone downtown) - public buildings only, no business brands or logos
- [x] Weather/time presets: overcast, coastal fog, golden hour, snow (WEATHER in render3d, --weather, F4)
- [x] Street-style detail: trees and lamp posts (OSM + procedural, solid to drive into), original graffiti tags, cartoon cars
- [ ] More street detail: awnings, shop signs, benches, bins, bus shelters, painted crossings
- [ ] Settings for resolution scale and palette

## Status (updated 15 Nov 2026)
- Everything below is built and tested headless (400 tests, `python -m unittest discover -s tests`). Still needs hands-on
  playtesting: handling, drift/boost feel, 4 player on Batocera, and the map editor with a real mouse.
- Runs on: Windows/macOS/Linux laptop (development), Batocera (Xbox pads, pygame 2.5.2, Python 3.11), Android/Pydroid.
- Frame cost (sandbox): ~2-3 ms render, ~17,500 props (about 15,000 trees). A basic laptop may be 2-4x slower.
  Jeremy's Linux dev machine (Python 3.14, pygame 2.6.1), `tools/bench_town.py data/amherst_map.json --style street`
  (the game's default look) with real hills: AI ~4 ms, render ~19 ms avg / ~24 p95, frame ~23 ms avg / ~29 ms p95;
  flat (--flat) ~21 / ~28. Retro style with hills ~18 / ~23. bench_town defaults to the RETRO style (older numbers
  in this file were retro): pass --style street. A basic laptop 2-4x slower would miss 30 fps in street style -
  rendering is the next performance job (profile: project_poly, _emit, pygame.draw.polygon dominate).
- SDL_AUDIODRIVER=dummy is needed for headless runs here, or pygame.init() stalls ~30 s.
- Game modes: start screen (`game/menu.py`) -> 1 Player (jobs, police, traffic, train) or 2/3/4 Player split screen free
  roam, no police (`game/twoplayer.py`; 3 players = player 1 gets the top half). `--players N`, `--no-menu`, `--no-cops`,
  `--no-train`, `--no-zoning`.
- Vehicles (`MODELS`, `player_car()` in `game/car.py`): P1 boxy retro SUV (yellow/white roof), P2 compact crossover (white),
  P3 mid-size SUV (grey), P4 quad cab pickup (black). Original low-poly designs, no badges. Size/mass/power per model;
  collision circles follow the car's length/width. Drawn by `Renderer3D._draw_cartoon_car` from the model spec.
- Hop + drift boost (LB/RB or Shift): `Car._hop_and_drift`. Hop at speed while steering = power slide (velocity lags the
  nose, DRIFT_* constants), hold to charge blue/orange/purple, release = boost. Sparks/flame in `_draw_effects`.
- Gamepads: raw button numbers differ by driver (Batocera Xbox pads count from 1). `game/padmap.py` reads SDL's
  SDL_GAMECONTROLLERCONFIG, so never hard-code button numbers; use `padmap.BTN["a"|"b"|"x"|"y"|"lb"|"rb"|"back"|"start"]`.
- Crash handling: `main.write_crash_log()` + `show_crash()` write `amherst-run-crash.log` in several places and paint the
  traceback on screen (Batocera hides errors).
- Map: OSM + NSRN roads, zoning raster (`data/zoning.json`) for consistent building looks, NS land-cover woods
  (`data/landcover.json`, nearest woods planted first), train on the real rail line.
- Real elevation (`data/elevation.json`, 708x562 points every 25 m, 0-164 m, Terrain Tiles on AWS) is committed and on
  by default; `--flat` / `World.load(terrain=False)` ignores it. Downtown sits ~27 m up, the marsh at 0 m.
- Real civic addresses (`data/addresses.json`, `tools/fetch_addresses.py`, NS Civic Address File via data.novascotia.ca,
  OGL-NS): 5,610 addresses; `MissionManager.address` uses the nearest real number on the drop point's own street
  within 45 m (~90% of drops), else the made-up number.
- Parcel hub = Dominion Building = OSM "Amherst Town Hall" (98 Victoria St E; Dominion Public Building 1934-36, post
  office until 1976). Set in landmarks_amherst.json AND, for the current map, in map_edits.json (the drugstore post
  office counter keeps its label but not the role; `only_if_no_role` keeps post_office_anywhere from re-taking it).
- Weather: WEATHER presets in render3d are style overrides + a colour grade applied in col(); `set_weather` switches in
  ~2 ms (only clouds and default roof colours are baked at build time - keep it that way or update set_weather).
- Map editor: `python tools/map_editor.py` (docs/EDITOR.md). Edits live in `data/map_edits.json` and
  `data/custom_buildings.json` and are applied by `World.load` via `game/mapedits.py`; re-downloading keeps them.
  `--check` lists buildings on roads, `--fix-all` pushes them clear. Done on the real map (15 Nov 2026): 79 on roads + 1
  inside another; --fix-all moved 70 (median 2.1 m, max 8.2 m). 10 left for hand editing (N jumps to them): 4372 (a lane
  runs 20 m through it - maybe bad road data), 822 Sackville Rd, 128 Victoria/Church corner, 144 Electric St, 4428 King St,
  1387 Douglas Ave, 154 Acadia St, 4344, 4231 (hospital roof part), and 674 inside 675. `--check` only prints the first 40.
  map_edits.json also gets loaded for data/sample_map.json (0 apply, but it logs a long "edit skipped" list).
- Junction rules (`game/junctions.py`, traffic only; police and players ignore them): each road-graph node with 3+
  neighbours gets a control per incoming edge. OSM `signal` marks -> lights (east-west / north-south phases from
  `streetdetail.signal_light`, the same clock the renderer lights the signal heads with: `town.time`); OSM `stop` marks ->
  full stop; otherwise the minor road (lane < side < main, or the stem of a T) gives way, equal 4-ways take turns. Left
  turns give way to oncoming cars; nobody enters a junction whose exit is jammed. Only 4 signals / 16 stops are mapped in
  OSM, so most junctions use the inferred rules with no visible sign. Real map, 2 min, parked player: AI-vs-AI crashes
  36 -> 14. Braking for a stopped car ahead is no longer low-pass filtered (queues rear-ended); waiting at a light pauses
  the jam timer (`car.wait`, despawn after 20 s) instead of draining it.
- START POINT (Jeremy, 15 Nov 2026; do not name the address in public files): a house at the Willow St / Milford St
  corner. The car spawns in the driveway off Milford St, nose towards the house (bearing 300; 120 faces the street) - `spawn` in map_edits.json,
  which overrides the converter's Victoria Square spawn. The house (OSM building at the civic point, 10 x 6.7 m) is
  hand-modelled: 1.5-storey Cape, light blue siding [178,200,230], walls 4.4 m, steep dark shingle gable
  3.6 m with the ridge along Willow St, brick chimney on the west part of the ridge, wooden deck on the south side
  (custom building), red barn-style shed by the NE corner (custom building, gable since there is no gambrel roof),
  paved driveway (road add, service=driveway), two big maples (props.add). Keep it looking like this; ask before
  changing it. bench_town parks at the spawn, so use `--at 394.6,-835.8` to compare with older downtown numbers.
- LiDAR heights (17 Nov 2026): `tools/fetch_heights.py` -> `data/building_heights.json` (4,956 of 5,160 buildings:
  2,493 flat, 1,795 gable, 668 hip; 587 of the 2463 pitched roofs (24%) run across the short side = `ridge_across`). Source NRCan HRDEM
  `hrdem-lidar` project NS-NSDNR_2020 (1 m DSM/DTM COGs on AWS, OGL-Canada); `tools/cog.py` = range-request BigTIFF
  reader + pure-Python LZW + EPSG:3979 projection, no new deps. OSM outlines sit ~3 m north of the LiDAR roofs; the tool
  finds the shift per 500 m cell. Precedence in World.load: lidar.apply (keyed by ORIGINAL footprint centres) ->
  map edits (hand values win; a hand roof drops ridge_across) -> zoning (colours/materials only for "lidar" buildings).
  Small footprints measuring > 10.5 m are skipped (tree canopy). Walls came out ~1.9 m lower than the old estimates.
  Render cost unchanged (roofs replaced the zoning-guessed ones). Tile cache data/.lidar_cache (~250 MB, git-ignored).
  The start house keeps its hand values (LiDAR says walls 4.6 m, ridge 6.7 m vs the hand 4.4 + 3.6).
- House types (17 Nov 2026, `game/archetypes.py`): classify() -> garage / minihome / bungalow / cape / two_storey /
  apartment from LiDAR wall height (bungalow <= 4.0 m, two_storey > 6.0 m, cape between or steep), measured pitch
  (LiDAR under-reads pitch: median 0.35; "steep" >= 0.45), footprint, zone and tags; commercial/landmark/custom -> None.
  Real map: 1,157 cape, 1,045 two-storey, 722 bungalow, 520 mini-home, 310 garage, 42 apartment, 1,366 other.
  Porches are a stable coin flip (55% two-storey, 30% cape, 20% bungalow). `"arch"` in map_edits.json overrides
  (start house = "cape"). Renderer: details only within HOUSE_DETAIL = 45 m, worked out lazily per building
  (`Renderer3D._house`, front wall = first outward probe that hits world.on_road); colours in STYLES[...]["house"].
  Upright gable triangles now use the wall colour on all buildings. No measurable render cost (back-to-back, +-2 ms).
- Heritage buildings (17 Nov 2026, Jeremy chose "public heritage records" as the reference): facts from the Canadian
  Register of Historic Places (via the Wikipedia list of Cumberland County places), matched by street address through
  data/addresses.json; stored in map_edits.json with a `_note` per building (register id in the note). Modelled: 109
  Court House (tower False), 115 old post office "Old Post Office" (tower True: clock tower moved here), 110 Dominion
  (light grey), 160 old Bank of Nova Scotia, 137 butcher shop 1897 (shopfront), 164 Trinity (steeple turret), 113 First
  Baptist (twin, sandstone), 108 Christ Church = OSM "Amherst Anglican Church" (steeple none), 196 station (hip roof),
  16 Armoury (OSM building=military; landmark entry fixed). NOT matched (ask Jeremy): 100 Victoria St E old Bank of
  Montreal (corner LaPlanche), 96 Church St (Moffatt House, mansard), 233 Victoria St E, 30 Hickman St school, 177 Victoria
  St E turret house and 27 / 46 Victoria St W houses (matched but not modelled: need turret/bay/veranda parts).
  Renderer: `steeple` spire/turret/twin/none, `tower` on any building, shop fronts (SHOP_DETAIL 70 m) on street walls of
  downtown sandstone/brick blocks (zone D/U/N or no zone) - `_shop_walls`. No measurable render cost (+-2 ms pairs).
- Benchmarks drift with machine load (17 Nov: street downtown render ~32 ms vs ~17 ms on 15 Nov, same code): compare
  only back-to-back runs.
- Painter's algorithm: scene objects must be sorted far-to-near (regression test exists). Walls are 12 m pieces;
  `_fix_wall_order` nudges cars/props within 10 m of a wall to the correct side of it (fixes the ~4-5% of slanted
  cases centre distance got wrong). Building-vs-building and car-vs-tree are still plain distance.
- tools/autopilot.py on the REAL map fails every job (OUT OF TIME / NO CASH TO FINE) - already true at the first commit,
  so the "15-25% spare" check only holds on the sample map. Needs a look before tuning job timers.

## Realism backlog (suggested order; do one per session, benchmark before and after)
1. DONE (15 Nov 2026): `--check` + `--fix-all` on the real map, `data/map_edits.json` committed (10 left by hand, see Status).
2. DONE (15 Nov 2026): traffic lights / stop signs / right of way (`game/junctions.py`). Follow-ups: visible signs at
   inferred junctions (ask Jeremy where the real ones are), running a red light adds heat.
3. DONE (15 Nov 2026): real house numbers from the NS Civic Address File (see Status).
4. DONE (17 Nov 2026) heights + roof shapes from LiDAR, and house types with close-range details (see Status).
   Next: dormers, gambrel (barn) roofs, bay windows, shop fronts downtown; hand-model the buildings Jeremy knows.
5. Vehicle realism: suspension lean and pitch, tyre marks and smoke on drift, engine and tyre sound, per-vehicle handling.
6. Pedestrians (crossings, footpaths), parked cars along streets, road markings and signs from Mapillary (check licence first).
7. DONE (15 Nov 2026): weather and time of day. Follow-ups: night, rain, fog starting closer (FOG_START is global).
8. Sound and music (original chiptune), pause menu, save/load of cash and progress.
Open questions for Jeremy: which of these matters most; the unmatched heritage buildings listed in Status; where are the real downtown lights/stop signs (OSM has few); Armoury/Dominion Building landmark names; downtown re-download check.

## Notes for Claude
- Prefer simple, readable code over clever code.
- If a task is bigger than one session, split it and say so.
- Before big changes to rendering, run a quick benchmark and report numbers.
- If unsure about a design choice, ask me rather than guess.
