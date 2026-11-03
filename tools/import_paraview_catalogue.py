# Copyright (C) 2026 David L F Gaden
"""Compile a native capture; execution qualification is separate from generation."""
import argparse
import json
from pathlib import Path
from schemaxis.adaptors.paraview.catalogue_import import compile_catalogue

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--extension-against', type=Path, help='retain only identities absent from this base catalogue')
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text())
    if args.extension_against:
        base = json.loads(args.extension_against.read_text())
        capture['roots'] = [key for key in capture['roots'] if key not in base['inventory']]
    result = compile_catalogue(capture)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'declared': len(result['declarations']), 'inventoried': len(result['inventory'])}))
