# Building your own Amherst

You can drop your own buildings into the map and make them look like Amherst: red sandstone downtown blocks,
Victorian houses with mansard roofs, clapboard homes, churches, barns. They are saved in one small file,
`data/custom_buildings.json`, that is kept apart from the converted map, so re-downloading the map never loses them.

There are two ways to make them: drive-and-drop inside the game, or edit the file.

## 1. Build mode (inside the game, keyboard)

1. Start the game on a computer: `python -m game.main`.
2. Drive to a street and press **B**. A green ghost building appears beside the car with its front facing the street.
3. Use the keys:

| Key | What it does |
|---|---|
| `[` and `]` | Previous / next building type |
| `,` and `.` | Turn the building 15 degrees |
| `X` | Switch between the right and left side of the street |
| `ENTER` | Place it (refused if it would sit on a road) |
| `BACKSPACE` | Undo the last building you placed this session |
| `B` | Leave build mode |

Each placed building is saved to `data/custom_buildings.json` straight away, as latitude and longitude. Drive on, press
`ENTER` again, and build a whole street. To change a building later, edit the file (below).

## 2. Edit the file

`data/custom_buildings.json` is a list of buildings. The smallest useful entry is a preset and a place:

```json
{"buildings": [
  {"name": "Corner house", "preset": "house", "lat": 45.8301, "lon": -64.2112}
]}
```

Find a latitude and longitude by right-clicking the spot in OpenStreetMap or any map and copying the coordinates.
`data/custom_buildings.example.json` has six ready-made examples placed near the starting square. To try them, copy it
over `custom_buildings.json`.

Check a file without starting the game (it prints what was added, skipped or looks wrong):

```
python -m game.builder data/custom_buildings.json
```

### Presets

| Preset | Size (wide x deep) | Look |
|---|---|---|
| `house` | 9 x 8 m | clapboard, gable roof |
| `cottage` | 7.5 x 7 m | clapboard, hip roof |
| `victorian` | 10 x 9 m | red brick, slate mansard roof (the Second Empire look) |
| `sandstone_block` | 16 x 12 m | red sandstone, flat roof - downtown commercial block |
| `shop` | 8 x 14 m | brick, flat roof |
| `apartments` | 32 x 14 m | brick, flat roof, 13.5 m tall |
| `church` | 11 x 24 m | sandstone, gable roof, with a spire |
| `barn` | 22 x 12 m | red, gable roof |
| `garage` | 6 x 6.5 m | clapboard, small gable roof |

"Wide" is along the street, "deep" is away from it.

### Styles (real Amherst looks)
`data/building_styles.json` holds 28 named looks made from photos of real Amherst buildings: red sandstone and brick
blocks, churches, a station, the ice arena, clapboard houses and cottages in white, blue and yellow, and more. In build
mode they follow the presets when you press `]`. In the file, use `"style"` instead of (or as well as) `"preset"`:

```json
{"name": "Station St corner", "style": "red_sandstone_train_station", "lat": 45.8309, "lon": -64.2124}
```

Anything else in the spec overrides the style (`"height": 9`, `"colour": [200, 190, 180]`). Add your own styles by copying an
entry in the styles file. `suggested_setback` is only a hint for placing by hand. Roof colours can now also be set per
building with `"roof_colour"`.

### Every setting

| Setting | Meaning |
|---|---|
| `preset` | One of the presets above (default `house`) |
| `style` | A named look from `data/building_styles.json` (see above) |
| `lat`, `lon` | Centre of the building. Or use `x`, `y` in map metres instead |
| `facing` | Compass direction the front looks, 0 = north, 90 = east. Leave it out and the front faces the nearest street |
| `setback` | Metres between the kerb and the front. Slides the building along the line to the street |
| `width`, `depth`, `height` | Metres. Override the preset (2 to 80 wide/deep, 0.5 to 60 tall: low ones make decks, hedges, fences) |
| `roof` | `flat`, `gable`, `hip` or `mansard`. `roof_height` is how tall the roof is in metres |
| `roof_colour` | `slate`, `shingle`, `copper`, `tin` or `[r, g, b]` |
| `material` | `sandstone`, `brick`, `clapboard` or `granite` |
| `colour` | `[r, g, b]` wall colour, instead of a material |
| `chimney` | Brick chimney on the ridge of a gable or hip roof: `true`, or where along the ridge from `-0.9` to `0.9` (0 = middle) |
| `label` | Name shown on the whole-town map (keep it generic, like the other landmarks) |
| `replace_radius` | Metres. Removes the OpenStreetMap building(s) whose centre is that close (swap a real house for yours) |

Roofs are drawn on four-cornered buildings (rectangles), which is what every preset makes.

## Making it feel like Amherst

- **Downtown (around the Court House and Victoria Square):** `sandstone_block` or `victorian`, set back 0-2 m from the
  footpath, front on the street, several in a row.
- **Residential streets:** `house` and `cottage` set back 6-8 m, with a `garage` behind. Mix colours with `colour`
  so a street does not look stamped out.
- **Landmarks:** a `church` on a corner. Use `sandstone_block` with `"height": 14` for taller civic buildings.
- **Marsh and edge of town:** `barn` and `garage`, set well back.

## Good to know

- The map keeps the real streets, so build on existing roads. Buildings that overlap a road are reported as a warning
  in the console (and build mode will not place them).
- Original names and shapes only. Do not copy business names or logos onto a building.
- Build mode is keyboard-only (it is a tool for your computer). Buildings you save show up in every version, including
  Batocera and Android, when you copy `data/custom_buildings.json` across with the game.
- Buildings are solid: cars bump into them like any other.


The three mall styles (`brick_supermarket`, `ribbed_shopping_mall`, `grey_box_store`) use the `corrugated` material. Width and depth can go up to 200 m.
