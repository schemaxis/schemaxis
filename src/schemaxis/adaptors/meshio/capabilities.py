# Copyright (C) 2026 David L F Gaden
"""Curated mesh interchange discovery."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'meshio', 'purpose': 'Convert mesh interchange formats with explicit coordinate units and preserved ordered topology and point/cell arrays.', 'keywords': ['mesh interchange', 'VTU', 'VTK', 'meshio']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['Isolated meshio 5.3.5 Python interpreter on POSIX.', 'Captured ASCII VTU or VTK 4.2 triangle/tetra regular file with explicit units and strict loss policy.'],
        'references': ['docs/meshio.md', 'src/schemaxis/adaptors/meshio/readiness.json'],
        'operations': {'convert': {
            'purpose': 'Convert ASCII VTU and VTK mesh formats with coordinate unit conversion, retaining ordered connectivity and scalar/vector point and cell data.',
            'keywords': ['mesh interchange', 'mesh conversion', 'VTU', 'VTK', 'meshio', 'coordinate units', 'point data', 'cell data', 'triangle', 'tetrahedron', 'millimetres to metres'],
            'semantics': ['Scale XYZ only; preserve flattened cell order and every supported field tuple.', 'Strict refusal of unsupported topology, metadata and compression before native execution; independent source/output parsers check preservation.'],
            'examples': [{'reference': 'examples/schemaxis/meshio-convert.json', 'purpose': 'Convert millimetre VTU to metre VTK with mixed cells and fields.'}, {'reference': 'examples/schemaxis/meshio-convert-variant.json', 'purpose': 'Convert metre VTK back to millimetre VTU.'}]}}
    }
