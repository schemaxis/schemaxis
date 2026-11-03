# Copyright (C) 2026 David L F Gaden
"""Matplotlib named-colour data, without a Matplotlib/NumPy runtime dependency."""
import json
import math
import re
from functools import lru_cache
from importlib.resources import files
from .errors import fail


@lru_cache(maxsize=1)
def palette():
    return json.loads(files('schemaxis').joinpath('named_colours.json').read_text())


def rgba(value, location='colour'):
    if isinstance(value, str):
        text = value.strip().lower()
        if text == 'none':
            return [0, 0, 0, 0]
        if text in palette()['colours']:
            return list(palette()['colours'][text])
        if re.fullmatch(r'#[0-9a-f]{3,4}|#[0-9a-f]{6}|#[0-9a-f]{8}', text):
            digits = text[1:]
            if len(digits) in (3, 4):
                digits = ''.join(c * 2 for c in digits)
            values = [int(digits[i:i+2], 16) / 255 for i in range(0, len(digits), 2)]
            return values if len(values) == 4 else values + [1]
        try:
            grey = float(text)
            if math.isfinite(grey) and 0 <= grey <= 1:
                return [grey, grey, grey, 1]
        except ValueError:
            pass
        fail('UNKNOWN_COLOUR', 'unknown colour name or notation', location,
             value=value, examples=['goldenrod', 'tab:blue', 'xkcd:sky blue', '#663399', '0.5'])
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        fail('INVALID_COLOUR', 'expected a name, hex colour or RGB/RGBA vector', location)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        fail('INVALID_COLOUR', 'colour components must be finite numbers', location)
    # Whole-number byte notation is unambiguous when any component exceeds one.
    if all(type(v) is int for v in value) and any(v > 1 for v in value):
        if any(v < 0 or v > 255 for v in value):
            fail('INVALID_COLOUR', 'byte components must be in 0..255', location)
        value = [v / 255 for v in value]
    if any(v < 0 or v > 1 for v in value):
        fail('INVALID_COLOUR', 'normalised components must be in 0..1', location)
    return list(value) if len(value) == 4 else list(value) + [1]
