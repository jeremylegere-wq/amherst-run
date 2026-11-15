# Map editor

Fix the map by hand: move or delete buildings, drag roads, add buildings and streets, and find anything that overlaps.

    python tools/map_editor.py            # needs a window; run it on your laptop, not on Batocera
    python tools/map_editor.py --check    # list overlaps and exit
    python tools/map_editor.py --fix-all  # push every building off the roads it sits on, save, exit

The converted map (`data/amherst_map.json`) is never changed. Your work is saved in two small files that the game reads
every time it starts, so re-downloading the map keeps your fixes:

| File | What is in it |
|---|---|
| `data/map_edits.json` | OpenStreetMap buildings you moved, reshaped, deleted or changed, roads you moved, deleted, renamed or added |
| `data/custom_buildings.json` | buildings you added (the same file as in-game build mode, see BUILDING.md) |

Edits find their building or road by position, not by number. If a later download moves a building more than 3 m, the
edit is reported as skipped when the game loads, instead of landing on the wrong thing.

## Keys (F1 shows them in the editor)

| | |
|---|---|
| Left click | select a building or road (my own buildings are teal, edited ones gold) |
| Drag | move the selected building or road |
| Drag a white corner | reshape. Shift+click an edge to add a corner. Del on a picked corner removes it |
| Right/middle drag, W A S D | pan |
| Wheel | zoom |
| Arrow keys | nudge the selection 0.5 m (Shift: 2 m) |
| `[` `]` | rotate 5 degrees (Shift: 15) |
| PgUp / PgDn | building height |
| M | building material |
| T, `+`, `-`, E | road type, width, name |
| Del | delete the selection |
| B | add a building: `,` `.` choose a preset or style, `[` `]` turn, click to place, Esc to stop |
| R | draw a road: click points (it snaps to road ends), Enter to finish |
| N / Shift+N | jump to the next / previous overlap (red outline) |
| F | push the selected building off its road. With nothing selected it fixes every one it can |
| O | re-check overlaps |
| 1 2 3 4 5 | show or hide roads, buildings, lanes, land, problems |
| Ctrl+Z | undo |
| Ctrl+S | save (closing the window saves too) |

## What counts as an overlap

* A building whose walls poke more than 35 cm into a road's width, or a road running through a building. Bridges and
  ramps are ignored, and so are small service lanes unless you press 3.
* Two buildings sharing real floor area. Walls that only touch (rows of houses) are fine.

The automatic fix slides the building straight away from the road, up to 14 m, and only if that does not push it into
another building. Anything it cannot fix stays red so you can handle it by hand.

## Start point and hand-placed trees (edit the file)

Two sections of `data/map_edits.json` are edited by hand; the editor saves them back unchanged:

```json
"spawn": {"lat": 45.83681, "lon": -64.19768, "bearing": 300},
"props": {"add": [{"kind": "tree", "lat": 45.83676, "lon": -64.19781, "h": 10.5, "r": 4.4, "cr": 0.5, "c": 1}]}
```

`bearing` is the compass direction the car faces (0 = north, 90 = east). Tree `h` is the height and `r` the canopy
radius in metres; `c` picks one of three leaf colours. Both use latitude and longitude, so they stay put when the map is
downloaded again.

## Limits

* Added buildings are rectangles from the presets and styles (they can be turned and resized in the JSON). Reshape an
  existing OpenStreetMap building if you need an odd outline.
* New roads are drawn as "side" streets; press T to change the type. Traffic uses them as soon as they join an existing road.
* Undo goes back through the session, not across saves.
