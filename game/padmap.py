"""Which raw button number is A, B, Start... on this gamepad.

pygame reports raw numbers, and they differ between drivers: the usual Xbox layout is A=0 B=1 X=2 Y=3 LB=4 RB=5
Back=6 Start=7, but some Linux drivers (the Xbox pads on Batocera) number them from 1: A=1 B=2 X=3 Y=4 LB=5 RB=6
Back=7 Start=8. Batocera tells SDL the truth through SDL_GAMECONTROLLERCONFIG, so we read the layout from there and
fall back to the usual one.
"""
import os

STANDARD = {"a": 0, "b": 1, "x": 2, "y": 3, "lb": 4, "rb": 5, "back": 6, "start": 7}
KEYS = {"a": "a", "b": "b", "x": "x", "y": "y", "leftshoulder": "lb", "rightshoulder": "rb", "back": "back",
        "start": "start"}
BTN = dict(STANDARD)          # the layout everything uses; set_from() replaces the numbers


def parse(config_text, guid):
    """Layout from SDL_GAMECONTROLLERCONFIG text for the pad with this GUID (None if it is not listed)."""
    for line in (config_text or "").replace("\\n", "\n").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or parts[0].lower() != (guid or "").lower():
            continue
        out = {}
        for p in parts[2:]:
            name, _, val = p.partition(":")
            if name in KEYS and val.startswith("b") and val[1:].isdigit():
                out[KEYS[name]] = int(val[1:])
        if {"a", "start"} <= set(out):
            return {**STANDARD, **out}
    return None


def set_from(pad):
    """Use the layout SDL reports for `pad` (keeps the standard one when nothing is known)."""
    BTN.update(STANDARD)
    try:
        found = parse(os.environ.get("SDL_GAMECONTROLLERCONFIG", ""), pad.get_guid())
    except Exception:
        found = None
    if found:
        BTN.update(found)
    return dict(BTN)
