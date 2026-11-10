# Copyright (C) 2026 David L F Gaden
"""Native filter descriptions. No ParaView imports, reflection or code strings.

Each dictionary above its class is the authoritative option and binding contract.
Most filters need no methods: the generic driver validates the options, creates
the proxy, assigns declared property paths and connects declared input ports.
These are new descriptions of native ParaView operations, written from the
native API.
"""
import copy
from schemaxis.core.declarations import validate_arguments, validate_specifications
from schemaxis.core.directions import DIRECTION_ARGUMENT, resolve_direction
from schemaxis.errors import fail


def option(kind, path, default=None, *, required=False, **constraints):
    spec = {'type': kind, **constraints}
    if required:
        spec['required'] = True
    elif default is not None:
        spec['default'] = default
    return {'value': spec, 'path': path.split('.')}


def vector(path, default=None, required=False):
    return option('array', path, default, required=required,
                  items={'type': 'number'}, minItems=3, maxItems=3)


def numbers(path, default=None, required=False):
    return option('array', path, default, required=required,
                  items={'type': 'number'}, minItems=1)


def strings(path, default=None, required=False):
    return option('array', path, default, required=required,
                  items={'type': 'string', 'minLength': 1}, minItems=1)


def choice(path, values, default):
    return option('enum', path, default, values=values)


def field(path):
    return option('array', path, required=True,
                  items={'type': 'string', 'minLength': 1}, minItems=2, maxItems=2)


def direction(path, default):
    return {'value': {**copy.deepcopy(DIRECTION_ARGUMENT), 'default': default},
            'path': path.split('.'), 'convert': 'direction'}


from schemaxis.bindings import convert_option, validate_options


class NativeFilter:
    declaration = {}

    @classmethod
    def describe(cls):
        return copy.deepcopy(cls.declaration)

    @classmethod
    def arguments(cls):
        return {name: item['value'] for name, item in cls.declaration['options'].items()}

    @classmethod
    def validate(cls, values, location):
        return validate_arguments(cls.arguments(), values, location=location)


WAVELET = {'id': 'wavelet', 'native': 'Wavelet', 'inputs': {}, 'options': {
    'extent': option('array', 'WholeExtent', [-10, 10, -10, 10, -10, 10],
                     items={'type': 'integer'}, minItems=6, maxItems=6),
    'centre': vector('Center', [0, 0, 0]),
    'maximum': option('number', 'Maximum', 255),
}, 'checks': [{'kind': 'bounds', 'option': 'extent'}]}
class Wavelet(NativeFilter):
    declaration = WAVELET


SPHERE = {'id': 'sphere', 'native': 'Sphere', 'inputs': {}, 'options': {
    'centre': vector('Center', [0, 0, 0]),
    'radius': option('number', 'Radius', 1, minimum=0, exclusiveMinimum=True),
    'resolution': option('integer', 'ThetaResolution', 24, minimum=3),
}, 'fixed': {'PhiResolution': 24}}
class Sphere(NativeFilter):
    declaration = SPHERE


LINE = {'id': 'line', 'native': 'Line', 'inputs': {}, 'options': {
    'start': vector('Point1', [-1, 0, 0]), 'end': vector('Point2', [1, 0, 0]),
    'resolution': option('integer', 'Resolution', 20, minimum=1),
}}
class Line(NativeFilter):
    declaration = LINE


from .reader_choices import selection as reader_selection

FOAM = {'id': 'foam', 'native': 'OpenFOAMReader', 'inputs': {}, 'options': {
    'file': {**option('string', 'FileName', required=True, minLength=1), 'constructor': True},
    'caseType': {**choice('CaseType', ['Decomposed Case', 'Reconstructed Case'], 'Decomposed Case'), 'constructor': True},
    'regions': reader_selection('MeshRegions', ['internalMesh']),
    'cellArrays': reader_selection('CellArrays'),
    'skipZero': option('boolean', 'SkipZeroTime', False),
}}
class Foam(NativeFilter):
    declaration = FOAM


ONE = {'input': {'native': 'Input', 'required': True, 'multiple': False}}
MANY = {'input': {'native': 'Input', 'required': True, 'multiple': True}}

CALCULATOR = {'id': 'calculator', 'native': 'Calculator', 'inputs': ONE, 'options': {
    'expression': option('string', 'Function', required=True, minLength=1),
    'result': option('string', 'ResultArrayName', required=True, minLength=1),
    'association': choice('AttributeType', ['Point Data', 'Cell Data'], 'Point Data'),
}}
class Calculator(NativeFilter):
    declaration = CALCULATOR


# The curated slice assigns only SliceType (the vtkDataSet cut function). ParaView cuts a
# vtkHyperTreeGrid with the separate HyperTreeGridImplicitFunction property
# (PV5.13.3:VTKExtensions/FiltersGeneral/Resources/general_filters.xml:2797-2825;
# vtkPVMetaSliceDataSet.cxx:76-87), so origin and normal would have no effect on one.
# Declare the narrower contract and refuse hyper-tree grids; pvSlice handles them.
SLICE_INPUT = {'input': {**ONE['input'], 'contract': {
    'nativeTypes': ['vtkDataSet'], 'requirements': {'topology': ['structured', 'unstructured']},
    'recovery': 'use pvSlice, which exposes the native hyper-tree-grid cut function'}}}
# Pin the curated single-plane contract: a fresh ParaView session can otherwise
# expose empty offsets for its first Slice and [0] for later Slice instances.
SLICE = {'id': 'slice', 'native': 'Slice', 'inputs': SLICE_INPUT,
         'fixed': {'SliceType': 'Plane', 'SliceOffsetValues': [0]}, 'options': {
    'origin': vector('SliceType.Origin', [0, 0, 0]),
    'normal': direction('SliceType.Normal', [1, 0, 0]),
    'crinkle': option('boolean', 'Crinkleslice', False),
    'triangulate': option('boolean', 'Triangulatetheslice', True),
}}
class Slice(NativeFilter):
    declaration = SLICE


CONTOUR = {'id': 'contour', 'native': 'Contour', 'inputs': ONE, 'options': {
    'field': field('ContourBy'), 'values': numbers('Isosurfaces', required=True),
    'normals': option('boolean', 'ComputeNormals', True),
    'gradients': option('boolean', 'ComputeGradients', False),
    'scalars': option('boolean', 'ComputeScalars', True),
}}
class Contour(NativeFilter):
    declaration = CONTOUR


CELL_TO_POINT = {'id': 'cellToPoint', 'native': 'CellDatatoPointData', 'inputs': ONE, 'options': {
    'passCellData': option('boolean', 'PassCellData', True),
    'allArrays': option('boolean', 'ProcessAllArrays', True),
    'arrays': strings('CellDataArraytoprocess'),
}, 'requires': [{'when': ['allArrays', False], 'option': 'arrays'}]}
class CellToPoint(NativeFilter):
    declaration = CELL_TO_POINT


POINT_TO_CELL = {'id': 'pointToCell', 'native': 'PointDatatoCellData', 'inputs': ONE, 'options': {
    'passPointData': option('boolean', 'PassPointData', True),
    'allArrays': option('boolean', 'ProcessAllArrays', True),
    'arrays': strings('PointDataArraytoprocess'),
}, 'requires': [{'when': ['allArrays', False], 'option': 'arrays'}]}
class PointToCell(NativeFilter):
    declaration = POINT_TO_CELL


from .block_choices import selection as block_selection

EXTRACT = {'id': 'extractBlock', 'native': 'ExtractBlock', 'inputs': ONE, 'options': {
    'selectors': block_selection('Selectors'),
}}
class ExtractBlock(NativeFilter):
    declaration = EXTRACT


GROUP = {'id': 'group', 'native': 'GroupDatasets', 'inputs': MANY, 'options': {
    'names': strings('BlockNames'),
}}
class Group(NativeFilter):
    declaration = GROUP


MERGE = {'id': 'merge', 'native': 'MergeBlocks', 'inputs': ONE, 'options': {
    'mergePoints': option('boolean', 'MergePoints', True),
}}
class Merge(NativeFilter):
    declaration = MERGE


SURFACE = {'id': 'surface', 'native': 'ExtractSurface', 'inputs': ONE, 'options': {}}
class Surface(NativeFilter):
    declaration = SURFACE


NORMALS = {'id': 'normals', 'native': 'SurfaceNormals', 'inputs': ONE, 'options': {
    'consistency': option('boolean', 'Consistency', True),
    'splitting': option('boolean', 'Splitting', False),
    'featureAngle': option('number', 'FeatureAngle', 30, minimum=0, maximum=180),
}}
class Normals(NativeFilter):
    declaration = NORMALS


REFLECT = {'id': 'reflect', 'native': 'Reflect', 'inputs': ONE, 'options': {
    'plane': choice('Plane', ['X Min', 'Y Min', 'Z Min', 'X Max', 'Y Max', 'Z Max', 'X', 'Y', 'Z'], 'X'),
    'centre': option('number', 'Center', 0),
    'copyInput': option('boolean', 'CopyInput', True),
}}
class Reflect(NativeFilter):
    declaration = REFLECT


STREAM = {'id': 'streamTracer', 'native': 'StreamTracerWithCustomSource',
          'inputs': {**ONE, 'seed': {'native': 'SeedSource', 'required': True, 'multiple': False}}, 'options': {
    'vectors': field('Vectors'),
    'direction': choice('IntegrationDirection', ['FORWARD', 'BACKWARD', 'BOTH'], 'FORWARD'),
    'maximumLength': option('number', 'MaximumStreamlineLength', 20, minimum=0, exclusiveMinimum=True),
    'maximumSteps': option('integer', 'MaximumSteps', 2000, minimum=1),
    'initialStep': option('number', 'InitialStepLength', 0.2, minimum=0, exclusiveMinimum=True),
}}
class StreamTracer(NativeFilter):
    declaration = STREAM


TUBE = {'id': 'tube', 'native': 'Tube', 'inputs': ONE, 'options': {
    'radius': option('number', 'Radius', 0.1, minimum=0, exclusiveMinimum=True),
    'sides': option('integer', 'NumberofSides', 12, minimum=3),
    'capping': option('boolean', 'Capping', True),
}}
class Tube(NativeFilter):
    declaration = TUBE


CLIP = {'id': 'clip', 'native': 'Clip', 'inputs': ONE, 'fixed': {'ClipType': 'Plane'}, 'options': {
    'origin': vector('ClipType.Origin', [0, 0, 0]),
    'normal': direction('ClipType.Normal', [1, 0, 0]),
    'invert': option('boolean', 'Invert', False),
}}
class Clip(NativeFilter):
    declaration = CLIP


THRESHOLD = {'id': 'threshold', 'native': 'Threshold', 'inputs': ONE, 'options': {
    'field': field('Scalars'),
    'lower': option('number', 'LowerThreshold', required=True),
    'upper': option('number', 'UpperThreshold', required=True),
}, 'fixed': {'ThresholdMethod': 'Between'}, 'checks': [{'kind': 'ordered', 'options': ['lower', 'upper']}]}
class Threshold(NativeFilter):
    declaration = THRESHOLD


INTEGRATE = {'id': 'integrate', 'native': 'IntegrateVariables', 'inputs': ONE, 'options': {
    'divideByVolume': option('boolean', 'DivideCellDataByVolume', False),
}}
class Integrate(NativeFilter):
    declaration = INTEGRATE


PROBE = {'id': 'probeLine', 'native': 'PlotOverLine', 'inputs': ONE, 'options': {
    'start': vector('Point1', [-1, 0, 0]), 'end': vector('Point2', [1, 0, 0]),
    'resolution': option('integer', 'Resolution', 100, minimum=1),
}}
class ProbeLine(NativeFilter):
    declaration = PROBE


OUTLINE = {'id': 'outline', 'native': 'Outline', 'inputs': ONE, 'options': {}}
class Outline(NativeFilter):
    declaration = OUTLINE


SURFACE_READER = {'id': 'readSurface', 'native': 'XMLPolyDataReader', 'inputs': {}, 'options': {
    'files': {
        'value': {'type': 'array', 'items': {'type': 'string', 'minLength': 1},
                  'minItems': 1, 'maxItems': 1, 'required': True},
        'path': ['FileName'], 'constructor': True},
}}
class SurfaceReader(NativeFilter):
    declaration = SURFACE_READER


FILTER_CLASSES = (Wavelet, Sphere, Line, Foam, SurfaceReader, Calculator, Slice, Contour,
                  CellToPoint, PointToCell, ExtractBlock, Group, Merge, Surface,
                  Normals, Reflect, StreamTracer, Tube, Clip, Threshold,
                  Integrate, ProbeLine, Outline)


def catalogue():
    from schemaxis.adaptors.paraview.extra_filters import FILTER_CLASSES as extras
    from schemaxis.adaptors.paraview.more_filters import FILTER_CLASSES as more
    result = {}
    for cls in (*FILTER_CLASSES, *extras, *more):
        declaration = cls.describe()
        validate_specifications(cls.arguments(), declaration['id'])
        if declaration['id'] in result:
            fail('DUPLICATE_FILTER', 'duplicate filter identifier', declaration['id'])
        result[declaration['id']] = declaration
    from .catalogue import enrich_curated, generated_declarations
    enrich_curated(result)
    result.update(generated_declarations())
    return result
