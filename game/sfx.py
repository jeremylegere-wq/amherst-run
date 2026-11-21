"""Small synthesized sound effects (no sound files): item roulette ticks, shot launch, ricochet, balloon pop,
spin-out, boost and a win jingle. Made once with numpy into pygame Sounds.

If the mixer cannot start (no sound card, a dummy audio driver in tests, Batocera without audio) every call is a
quiet no-op, so the game never depends on sound working.
"""
import math

import numpy as np
import pygame

RATE = 22050
_sounds = None


def _tone(freq, secs, kind="square", vol=0.3, sweep=0.0, noise=0.0, decay=6.0):
    n = int(RATE * secs)
    t = np.arange(n) / RATE
    f = freq + sweep * t / max(secs, 1e-6)                     # linear pitch sweep over the sound
    phase = 2 * math.pi * np.cumsum(f) / RATE
    if kind == "square":
        wave = np.sign(np.sin(phase))
    elif kind == "saw":
        wave = 2.0 * ((phase / (2 * math.pi)) % 1.0) - 1.0
    else:
        wave = np.sin(phase)
    if noise:
        rng = np.random.default_rng(7)
        wave = wave * (1.0 - noise) + rng.uniform(-1.0, 1.0, n) * noise
    env = np.exp(-decay * t) * np.minimum(1.0, t * 400.0)       # quick attack, exponential fall
    return wave * env * vol


def _make():
    """name -> pygame Sound, or {} when there is no mixer."""
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(RATE, -16, 1, 512)
        init = pygame.mixer.get_init()
    except Exception:
        return {}
    if not init:
        return {}
    channels = init[2]
    raw = {
        "tick": _tone(1400, 0.03, vol=0.18, decay=40),
        "item": np.concatenate([_tone(880, 0.07, vol=0.2), _tone(1320, 0.12, vol=0.2)]),
        "launch": _tone(300, 0.22, "saw", vol=0.25, sweep=500, noise=0.3, decay=10),
        "ricochet": _tone(2200, 0.09, "sine", vol=0.22, sweep=-900, decay=25),
        "pop": _tone(180, 0.12, "square", vol=0.35, noise=0.7, decay=30),
        "spin": _tone(700, 0.6, "square", vol=0.18, sweep=-500, decay=3),
        "boost": _tone(200, 0.5, "saw", vol=0.22, sweep=600, decay=3),
        "win": np.concatenate([_tone(f, 0.14, vol=0.22, decay=4) for f in (523, 659, 784, 1047)]),
    }
    out = {}
    for name, wave in raw.items():
        pcm = (np.clip(wave, -1.0, 1.0) * 32000).astype(np.int16)
        if channels > 1:
            pcm = np.repeat(pcm[:, None], channels, axis=1)
        try:
            out[name] = pygame.sndarray.make_sound(np.ascontiguousarray(pcm))
        except Exception:
            return {}
    return out


def play(name):
    """Play one effect; silently does nothing without sound."""
    global _sounds
    if _sounds is None:
        _sounds = _make()
    snd = _sounds.get(name)
    if snd is not None:
        try:
            snd.play()
        except Exception:
            pass
