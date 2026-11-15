#!/usr/bin/env python3
"""Swap the roads in a converted map for Nova Scotia Road Network (NSRN) roads.

    python tools/nsrn_to_roads.py data/nsrn_amherst_extract.csv data/amherst_map.json
    python tools/nsrn_to_roads.py FULL_NSRN.csv data/amherst_map.json --write-extract data/nsrn_amherst_extract.csv

The full province export is ~460 MB. --write-extract saves the rows around Amherst (same columns) as a small
CSV that lives in the repository; osm_to_map.py applies it automatically when it converts a map.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nsrn  # noqa: E402

EXTRACT_LAT = (45.770, 45.860)        # covers the 6 km Amherst map with room to spare
EXTRACT_LON = (-64.265, -64.175)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    out_extract = argv[argv.index("--write-extract") + 1] if "--write-extract" in argv else None
    if out_extract:
        args = [a for a in args if a != out_extract]
        n = nsrn.write_extract(args[0], out_extract, EXTRACT_LAT, EXTRACT_LON)
        print("wrote %d rows to %s" % (n, out_extract))
        args = [out_extract] + args[1:]
    if len(args) != 2:
        print(__doc__)
        return 1
    with open(args[1]) as f:
        data = json.load(f)
    overrides = os.path.join(os.path.dirname(os.path.abspath(args[1])), "speed_overrides.json")
    print(nsrn.apply(data, args[0], overrides))
    with open(args[1], "w") as f:
        json.dump(data, f, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
