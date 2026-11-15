"""Phone launcher: open this file in Pydroid 3 (or any Android Python with pygame) and press play.

Touch controls are shown automatically. A paired Bluetooth controller also works.
"""
import os
import sys

import pygame  # noqa: F401  (Pydroid 3 looks for this line to start its SDL/pygame display)

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("ANDROID_ROOT", "/system")     # makes game.main turn the touch buttons on

from game.main import main  # noqa: E402

sys.argv = [sys.argv[0], "--touch", "--debug-input"]   # remove --debug-input once it plays right
main()
