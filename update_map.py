#!/usr/bin/env python3
"""Re-download Amherst from OpenStreetMap and rebuild data/amherst_map.json.

Put this file in the amherst-run folder (next to README.md) and run:

    python update_map.py              # default 6 x 6 km area over downtown
    python update_map.py --radius 4000
    python update_map.py --no-nsrn    # keep OpenStreetMap roads instead of the NSRN streets

    python update_map.py --no-elevation   # do not download ground heights

Needs internet access. Extra areas added with tools/extend_map.py (data/map_extensions.json) are added again. Your data/custom_buildings.json is not touched. Ground heights are downloaded the first time
(data/elevation.json); refresh them any time with: python tools/fetch_elevation.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import fetch_osm  # noqa: E402

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-elevation"]
    code = fetch_osm.main(["--convert"] + args)
    if code == 0 and os.path.exists(os.path.join(ROOT, "data", "map_extensions.json")):
        import extend_map                            # the extra areas (tools/extend_map.py), added again
        print("\nAdding the extra map areas in data/map_extensions.json")
        extend_map.main(["--reapply"])
    if code == 0 and "--no-elevation" not in sys.argv and not os.path.exists(os.path.join(ROOT, "data", "elevation.json")):
        import fetch_elevation                       # real hills, once; a failure here is not fatal
        print("\nNo data/elevation.json yet: downloading ground heights (use --no-elevation to skip)")
        fetch_elevation.main([])
    sys.exit(code)
