"""Curated offline IFC wall schedule discovery without native imports."""
import json
from importlib.resources import files

OPERATION = 'scheduleWalls'


def catalogue():
    return {'application': {'label': 'IfcOpenShell', 'purpose': 'Schedule the plain IfcWall occurrences of one small ASCII IFC4 file: explicit property-set and quantity columns joined to each wall by GlobalId, with explicit occurrence/type precedence, explicit missing values and project SI units converted to metres, square metres and cubic metres. A fresh native reopen and an independent STEP walk must agree; geometry is never calculated or validated and the schedule is a draft for BIM coordination review.',
                            'keywords': ['IFC', 'IFC4', 'IfcOpenShell', 'BIM', 'wall schedule', 'property set', 'quantity set', 'IfcWall', 'GlobalId', 'building model schedule', 'Pset_WallCommon', 'Qto_WallBaseQuantities']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['Use an absolute local ASCII IFC4 file with FILE_SCHEMA exactly IFC4, at most 2MiB, 4096 entities and 64 plain IfcWall occurrences (at least 2); Unicode escapes, comments, IfcWallStandardCase, IFC2X3 and IFC4X3 are refused before any native process runs.',
                             'Declare 2 to 6 columns explicitly: IfcPropertySingleValue properties (text, number or boolean) or IfcQuantityLength/Area/Volume quantities with the exact set and property or quantity names. No selector expressions, code or geometry options exist.',
                             'Choose missing (refuse or null) and inheritance (occurrence-only or occurrence-overrides-type) explicitly; every cell records whether it came from the occurrence, the type or nothing, and missing is never zero.',
                             'The project must declare plain SI units (metre, square metre, cubic metre with no prefix or MILLI, CENTI, DECI or KILO) for the quantity kinds used; conversion-based, derived, ambiguous or missing units are refused.',
                             'Configure a private IfcOpenShell 0.9.0.post1 Python interpreter (--ifcopenshell or SCHEMAXIS_IFCOPENSHELL). The result is not quantity accuracy, a certified model, compliance, safety, cost or geometry validity.'],
            'references': ['docs/ifcopenshell.md', 'src/schemaxis/adaptors/ifcopenshell/readiness.json'],
            'operations': {OPERATION: {
                'purpose': 'Schedule plain IfcWall occurrences from one ASCII IFC4 file into a GUID-linked typed table of selected property and quantity columns with explicit origin and units, checked by an independent STEP walk.',
                'keywords': ['IFC wall schedule', 'BIM schedule', 'IfcWall', 'property set', 'quantity set', 'GlobalId', 'IFC4', 'IfcOpenShell', 'typed CSV', 'occurrence and type properties', 'Pset_WallCommon', 'Qto_WallBaseQuantities', 'FireRating', 'IFC walls to spreadsheet table', 'building model schedule'],
                'semantics': ['Rows are plain IfcWall occurrences sorted by GlobalId; the Name is nullable literal text and never an identity.',
                              'occurrence-only never reads the wall type; occurrence-overrides-type reads the type property set only where the occurrence has no such property, and each cell records occurrence, type or missing.',
                              'Quantities come from the occurrence IfcElementQuantity only and are converted exactly from the project SI unit to m, m2 or m3; no geometry is calculated and nothing certifies the stored quantity.',
                              'The typed CSV uses the null token \\N and can be read by Calc readTypedCSV; each numeric column needs at least two present values there.'],
                'examples': [{'reference': 'examples/schemaxis/ifcopenshell-baseline.json', 'purpose': 'Schedule three synthetic walls with a type default, an occurrence override, a missing height and mm quantities.'},
                             {'reference': 'examples/schemaxis/ifcopenshell-variant.json', 'purpose': 'Schedule the same walls after one length changed.'},
                             {'reference': 'examples/schemaxis/ifcopenshell-areas.json', 'purpose': 'Convert prefixed project area and volume units to m2 and m3.'}]}}}
