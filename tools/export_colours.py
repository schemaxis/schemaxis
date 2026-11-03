# Copyright (C) 2026 David L F Gaden
"""Development-only palette export; native execution never imports Matplotlib.

Run on a host with Matplotlib: python3 tools/export_colours.py
"""
import importlib.metadata
import json
from pathlib import Path
import shutil
from matplotlib.colors import get_named_colors_mapping, to_rgba

root = Path(__file__).resolve().parents[1]
distribution = importlib.metadata.distribution('matplotlib')
palette = {'source': 'Matplotlib get_named_colors_mapping', 'version': distribution.version,
           'colours': {name: list(to_rgba(value)) for name, value in sorted(get_named_colors_mapping().items())}}
(root / 'src/schemaxis/named_colours.json').write_text(json.dumps(palette, indent=2) + '\n')
license_file = next(distribution.locate_file(p) for p in distribution.files if str(p).endswith('.dist-info/LICENSE'))
shutil.copyfile(license_file, root / 'src/schemaxis/Matplotlib-LICENSE.txt')
