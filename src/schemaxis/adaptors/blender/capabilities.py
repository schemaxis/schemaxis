"""Adaptor-owned selection guidance; no native imports or probes."""
import json
from importlib.resources import files

def catalogue():
    return json.loads(files(__package__).joinpath("capabilities.json").read_text())
