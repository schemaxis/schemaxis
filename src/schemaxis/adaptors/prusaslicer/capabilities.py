"""Operation selection guidance for bounded FFF slicing."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'PrusaSlicer',
                'purpose': 'Slice one closed STL part into FFF/FDM 3D-printer G-code with an explicit printer, filament and print profile, and publish independently replayed layer, temperature and filament evidence with native print-time estimates. It never controls or sends jobs to a printer.',
                'keywords': ['3D printing', 'additive manufacturing', 'FFF', 'FDM', 'slicer', 'G-code', 'toolpath']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'groups': {'fabrication': {'label': '3D-print preparation', 'purpose': 'Prepare declared geometry for fused-filament printing without machine control.', 'domain': 'fabrication'}},
        'requirements': [
            'PrusaSlicer 2.9.6 console executable configured as an absolute path; Schemaxis renders the complete configuration and never loads user or vendor presets.',
            'Millimetres, seconds, degrees Celsius and grams throughout; model.units states whether STL coordinates are millimetres or inches.',
            'One closed, consistently oriented STL object within 16 MiB and 100000 triangles that fits the declared bed around its placement centre. No mesh repair.',
            'Generic Marlin 2 G-code for an FFF machine described only by the declared limits. The G-code is not sent to hardware and no physical print outcome is certified.'],
        'references': ['docs/prusaslicer.md', 'src/schemaxis/adaptors/prusaslicer/readiness.json'],
        'operations': {'sliceModel': {'groups': ['fabrication'],
            'purpose': 'Slice a closed STL part into layer-by-layer FFF G-code using a declared printer, filament and print profile; publish the G-code, a per-layer table and a summary with native print-time and filament estimates.',
            'keywords': ['slice', 'slicing', 'G-code', 'gcode', 'toolpath', 'layer height', 'infill', 'perimeters',
                         'filament usage', 'print time estimate', 'nozzle temperature', 'bed temperature', 'STL', 'FDM', 'FFF'],
            'semantics': [
                'Lengths and speeds are millimetres and mm/s, temperatures degrees Celsius, density g/cm3 and filament mass grams. The STL is scaled by 25.4 when model.units is inch.',
                'The model is dropped onto the bed and its bounding box centred on placement.centre_mm (default bed centre). No rotation, arrangement, supports, brim, skirt or mesh repair.',
                'An independent replay of the G-code checks layer heights, the extrusion envelope against the model footprint, temperature and fan setpoints per layer, feedrate limits and filament arithmetic; native time estimates must lie within independent kinematic bounds.',
                'A fresh native process reloads the configuration embedded in the published G-code and must regenerate identical G-code.',
                'Estimates are PrusaSlicer model estimates for a generic machine; no printer, firmware or material compatibility, print quality or safety is certified.'],
            'examples': [{'reference': 'examples/schemaxis/prusaslicer-pla.json', 'purpose': 'PLA on a 0.4 mm nozzle with 20% grid infill.'},
                         {'reference': 'examples/schemaxis/prusaslicer-petg.json', 'purpose': 'PETG on a 0.6 mm nozzle, solid infill and a filament-mass limit.'}]}}}
