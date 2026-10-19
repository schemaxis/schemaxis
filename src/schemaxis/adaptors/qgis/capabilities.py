"""Adaptor-owned selection guidance; no native imports or probes."""
import json
from importlib.resources import files

def catalogue():
    result = json.loads(files(__package__).joinpath("capabilities.json").read_text())
    result["searchCases"] = json.loads(files(__package__).joinpath("search-cases.json").read_text())
    return result
