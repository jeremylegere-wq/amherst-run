#!/bin/bash
# Amherst Run launcher (Batocera Ports / Linux). Fullscreen is set in game/config.py.
cd "$(dirname "$0")" || exit 1
python3 -m game.main "$@"
