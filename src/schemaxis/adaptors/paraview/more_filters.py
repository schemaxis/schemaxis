"""Additional bounded ParaView source, reader and processing declarations."""
from schemaxis.adaptors.paraview.filters import NativeFilter, ONE, option, vector, direction, choice


class Cone(NativeFilter):
    declaration = {'id': 'cone', 'native': 'Cone', 'inputs': {}, 'options': {
        'centre': vector('Center', [0, 0, 0]), 'direction': direction('Direction', [1, 0, 0]),
        'height': option('number', 'Height', 2, minimum=0, exclusiveMinimum=True),
        'radius': option('number', 'Radius', 1, minimum=0, exclusiveMinimum=True),
        'resolution': option('integer', 'Resolution', 32, minimum=3, maximum=512),
        'capping': option('boolean', 'Capping', True)}}


class Cylinder(NativeFilter):
    declaration = {'id': 'cylinder', 'native': 'Cylinder', 'inputs': {}, 'options': {
        'centre': vector('Center', [0, 0, 0]),
        'height': option('number', 'Height', 2, minimum=0, exclusiveMinimum=True),
        'radius': option('number', 'Radius', 1, minimum=0, exclusiveMinimum=True),
        'resolution': option('integer', 'Resolution', 32, minimum=3, maximum=512),
        'capping': option('boolean', 'Capping', True)}}


class Plane(NativeFilter):
    declaration = {'id': 'plane', 'native': 'Plane', 'inputs': {}, 'options': {
        'origin': vector('Origin', [-1, -1, 0]), 'point1': vector('Point1', [1, -1, 0]),
        'point2': vector('Point2', [-1, 1, 0]),
        'xResolution': option('integer', 'XResolution', 10, minimum=1, maximum=4096),
        'yResolution': option('integer', 'YResolution', 10, minimum=1, maximum=4096)}}


class Disk(NativeFilter):
    declaration = {'id': 'disk', 'native': 'Disk', 'inputs': {}, 'options': {
        'innerRadius': option('number', 'InnerRadius', 0.25, minimum=0),
        'outerRadius': option('number', 'OuterRadius', 1, minimum=0, exclusiveMinimum=True),
        'radialResolution': option('integer', 'RadialResolution', 2, minimum=1, maximum=4096),
        'resolution': option('integer', 'CircumferentialResolution', 32, minimum=3, maximum=4096)},
        'checks': [{'kind': 'ordered', 'options': ['innerRadius', 'outerRadius']}]}


def reader(identifier, native, path='FileName'):
    return {'id': identifier, 'native': native, 'inputs': {}, 'options': {
        'files': {**option('array', path, required=True,
                          items={'type': 'string', 'minLength': 1}, minItems=1, maxItems=1),
                  'constructor': True}}}


class ReadUnstructuredGrid(NativeFilter):
    declaration = reader('readUnstructuredGrid', 'XMLUnstructuredGridReader')


class ReadParallelPolyData(NativeFilter):
    declaration = {**reader('readParallelPolyData', 'XMLPartitionedPolydataReader'), 'nativeIdentity': 'sources/XMLPPolyDataReader'}


class ReadParallelUnstructuredGrid(NativeFilter):
    declaration = {**reader('readParallelUnstructuredGrid', 'XMLPartitionedUnstructuredGridReader'), 'nativeIdentity': 'sources/XMLPUnstructuredGridReader'}


class ReadImageData(NativeFilter):
    declaration = reader('readImageData', 'XMLImageDataReader')


class ReadStructuredGrid(NativeFilter):
    declaration = reader('readStructuredGrid', 'XMLStructuredGridReader')


class ReadRectilinearGrid(NativeFilter):
    declaration = reader('readRectilinearGrid', 'XMLRectilinearGridReader')


class ReadMultiBlock(NativeFilter):
    declaration = reader('readMultiBlock', 'XMLMultiBlockDataReader')


class ReadSTL(NativeFilter):
    declaration = reader('readSTL', 'STLReader', 'FileNames')


class ReadPLY(NativeFilter):
    declaration = reader('readPLY', 'PLYReader', 'FileNames')


class GenerateIds(NativeFilter):
    declaration = {'id': 'generateIds', 'native': 'PointAndCellIds', 'inputs': ONE, 'options': {
        'pointIds': option('boolean', 'GeneratePointIds', True),
        'cellIds': option('boolean', 'GenerateCellIds', True),
        'pointName': option('string', 'PointIdsArrayName', 'pointIds', minLength=1),
        'cellName': option('string', 'CellIdsArrayName', 'cellIds', minLength=1)}}


class PassArrays(NativeFilter):
    declaration = {'id': 'passArrays', 'native': 'PassArrays', 'inputs': ONE, 'options': {
        name: option('array', path, [], items={'type': 'string', 'minLength': 1})
        for name, path in [('pointArrays', 'PointDataArrays'), ('cellArrays', 'CellDataArrays'),
                           ('fieldArrays', 'FieldDataArrays')]}}


class Curvature(NativeFilter):
    declaration = {'id': 'curvature', 'native': 'Curvature', 'inputs': ONE, 'options': {
        'type': choice('CurvatureType', ['Gaussian', 'Mean'], 'Mean'),
        'invertMean': option('boolean', 'InvertMeanCurvature', False)}}


class ExtractSubset(NativeFilter):
    declaration = {'id': 'extractSubset', 'native': 'ExtractSubset', 'inputs': ONE, 'options': {
        'extent': option('array', 'VOI', required=True, items={'type': 'integer'}, minItems=6, maxItems=6),
        'rateI': option('integer', 'SampleRateI', 1, minimum=1),
        'rateJ': option('integer', 'SampleRateJ', 1, minimum=1),
        'rateK': option('integer', 'SampleRateK', 1, minimum=1),
        'includeBoundary': option('boolean', 'IncludeBoundary', True)}}


FILTER_CLASSES = (Cone, Cylinder, Plane, Disk, ReadUnstructuredGrid, ReadParallelPolyData,
                  ReadParallelUnstructuredGrid, ReadImageData,
                  ReadStructuredGrid, ReadRectilinearGrid, ReadMultiBlock, ReadSTL,
                  ReadPLY, GenerateIds, PassArrays, Curvature, ExtractSubset)
