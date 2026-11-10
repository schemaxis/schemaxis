# Copyright (C) 2026 David L F Gaden
"""Adaptor-owned selection guidance; no native imports or probes."""
import json
from importlib.resources import files


def catalogue():
    value = json.loads(files(__package__).joinpath("capabilities.json").read_text())
    value["searchCases"] = json.loads(files(__package__).joinpath("search-cases.json").read_text())
    return value
