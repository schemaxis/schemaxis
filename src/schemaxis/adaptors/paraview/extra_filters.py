# Copyright (C) 2026 David L F Gaden
"""Additional ParaView 5.13.3 operations using the same dictionary contract."""
from schemaxis.adaptors.paraview.filters import NativeFilter, ONE, MANY, option, vector, field, direction, choice


def point_only(option_name, filter_name):
    # ParaView declares InputArrayDomain attribute_type="point" for both warp filters
    # (PV5.13.3:Remoting/Application/Resources/filters_filtersgeneral.xml:2113,2227) and
    # vtkWarpScalar/vtkWarpVector index the selected array by point id, so a cell array
    # would be read at the wrong positions (vtkWarpScalar.cxx:123-145,260; vtkWarpVector.cxx:169-195).
    return {'kind': 'firstItem', 'option': option_name, 'values': ['POINTS'], 'code': 'INVALID_ASSOCIATION',
            'message': filter_name + ' reads the selected array per point; the CELLS association is not supported',
            'recovery': 'name a POINTS array; convert cell data first with cellToPoint'}


WARP_VECTOR = {'id': 'warpVector', 'native': 'WarpByVector', 'inputs': ONE, 'options': {
    'vectors': field('Vectors'), 'scale': option('number', 'ScaleFactor', 1),
}, 'checks': [point_only('vectors', 'warpVector')]}
class WarpVector(NativeFilter):
    declaration = WARP_VECTOR


WARP_SCALAR = {'id': 'warpScalar', 'native': 'WarpByScalar', 'inputs': ONE, 'options': {
    'field': field('Scalars'), 'scale': option('number', 'ScaleFactor', 1),
    'normal': direction('Normal', [0, 0, 1]), 'useNormal': option('boolean', 'UseNormal', True),
}, 'checks': [point_only('field', 'warpScalar')]}
class WarpScalar(NativeFilter):
    declaration = WARP_SCALAR


SHRINK = {'id': 'shrink', 'native': 'Shrink', 'inputs': ONE, 'options': {
    'factor': option('number', 'ShrinkFactor', 0.8, minimum=0, maximum=1),
}}
class Shrink(NativeFilter):
    declaration = SHRINK


CLEAN = {'id': 'clean', 'native': 'Clean', 'inputs': ONE, 'options': {
    'mergePoints': option('boolean', 'PointMerging', True),
    'tolerance': option('number', 'Tolerance', 0, minimum=0),
    'absolute': option('boolean', 'ToleranceIsAbsolute', False),
    'absoluteTolerance': option('number', 'AbsoluteTolerance', 0, minimum=0),
}}
class Clean(NativeFilter):
    declaration = CLEAN


CLEAN_GRID = {'id': 'cleanGrid', 'native': 'CleantoGrid', 'inputs': ONE, 'options': {
    'tolerance': option('number', 'Tolerance', 0, minimum=0),
    'removeUnusedPoints': option('boolean', 'RemovePointsWithoutCells', True),
}}
class CleanGrid(NativeFilter):
    declaration = CLEAN_GRID


DELAUNAY_3D = {'id': 'delaunay3D', 'native': 'Delaunay3D', 'inputs': ONE, 'options': {
    'alpha': option('number', 'Alpha', 0, minimum=0),
    'tolerance': option('number', 'Tolerance', 0.001, minimum=0),
}}
class Delaunay3D(NativeFilter):
    declaration = DELAUNAY_3D


DELAUNAY_2D = {'id': 'delaunay2D', 'native': 'Delaunay2D', 'inputs': ONE, 'options': {
    'alpha': option('number', 'Alpha', 0, minimum=0),
    'tolerance': option('number', 'Tolerance', 0.00001, minimum=0),
}}
class Delaunay2D(NativeFilter):
    declaration = DELAUNAY_2D


ELEVATION = {'id': 'elevation', 'native': 'Elevation', 'inputs': ONE, 'options': {
    'lowPoint': vector('LowPoint', [0, 0, -1]), 'highPoint': vector('HighPoint', [0, 0, 1]),
    'range': option('array', 'ScalarRange', [0, 1], items={'type': 'number'}, minItems=2, maxItems=2),
}}
class Elevation(NativeFilter):
    declaration = ELEVATION


GRADIENT = {'id': 'gradient', 'native': 'Gradient', 'inputs': ONE, 'options': {
    'field': field('ScalarArray'), 'result': option('string', 'ResultArrayName', 'gradient'),
    'gradient': option('boolean', 'ComputeGradient', True),
    'divergence': option('boolean', 'ComputeDivergence', False),
    'vorticity': option('boolean', 'ComputeVorticity', False),
    'qCriterion': option('boolean', 'ComputeQCriterion', False),
}}
class Gradient(NativeFilter):
    declaration = GRADIENT


CELL_SIZE = {'id': 'cellSize', 'native': 'CellSize', 'inputs': ONE, 'options': {
    'area': option('boolean', 'ComputeArea', True), 'volume': option('boolean', 'ComputeVolume', True),
    'length': option('boolean', 'ComputeLength', True), 'sum': option('boolean', 'ComputeSum', False),
}}
class CellSize(NativeFilter):
    declaration = CELL_SIZE


CONNECTIVITY = {'id': 'connectivity', 'native': 'Connectivity', 'inputs': ONE, 'options': {
    'mode': choice('ExtractionMode', ['Extract All Regions', 'Extract Largest Region', 'Extract Closest Point Region'],
                   'Extract All Regions'),
    'colourRegions': option('boolean', 'ColorRegions', True),
    'closestPoint': vector('ClosestPoint', [0, 0, 0]),
}}
class Connectivity(NativeFilter):
    declaration = CONNECTIVITY


DECIMATE = {'id': 'decimate', 'native': 'Decimate', 'inputs': ONE, 'options': {
    'reduction': option('number', 'TargetReduction', 0.5, minimum=0, maximum=1),
    'preserveTopology': option('boolean', 'PreserveTopology', True),
}}
class Decimate(NativeFilter):
    declaration = DECIMATE


SMOOTH = {'id': 'smooth', 'native': 'Smooth', 'inputs': ONE, 'options': {
    'iterations': option('integer', 'NumberofIterations', 20, minimum=0),
    'convergence': option('number', 'Convergence', 0, minimum=0),
}}
class Smooth(NativeFilter):
    declaration = SMOOTH


TRIANGULATE = {'id': 'triangulate', 'native': 'Triangulate', 'inputs': ONE, 'options': {}}
class Triangulate(NativeFilter):
    declaration = TRIANGULATE


APPEND = {'id': 'append', 'native': 'AppendDatasets', 'inputs': MANY, 'options': {}}
class Append(NativeFilter):
    declaration = APPEND


APPEND_GEOMETRY = {'id': 'appendGeometry', 'native': 'AppendGeometry', 'inputs': MANY, 'options': {}}
class AppendGeometry(NativeFilter):
    declaration = APPEND_GEOMETRY


TRANSFORM = {'id': 'transform', 'native': 'Transform', 'inputs': ONE, 'fixed': {'Transform': 'Transform'}, 'options': {
    'translate': vector('Transform.Translate', [0, 0, 0]),
    'rotate': vector('Transform.Rotate', [0, 0, 0]), 'scale': vector('Transform.Scale', [1, 1, 1]),
    'allVectors': option('boolean', 'TransformAllInputVectors', True),
}}
class Transform(NativeFilter):
    declaration = TRANSFORM


RESAMPLE = {'id': 'resample', 'native': 'ResampleWithDataset', 'inputs': {
    'input': {'native': 'SourceDataArrays', 'required': True, 'multiple': False},
    'mesh': {'native': 'DestinationMesh', 'required': True, 'multiple': False}}, 'options': {
    'passPointArrays': option('boolean', 'PassPointArrays', True),
    'passCellArrays': option('boolean', 'PassCellArrays', False),
    'categorical': option('boolean', 'CategoricalData', False),
}}
class Resample(NativeFilter):
    declaration = RESAMPLE


EDGES = {'id': 'edges', 'native': 'ExtractEdges', 'inputs': ONE, 'options': {}}
class Edges(NativeFilter):
    declaration = EDGES


FEATURE_EDGES = {'id': 'featureEdges', 'native': 'FeatureEdges', 'inputs': ONE, 'options': {
    'boundary': option('boolean', 'BoundaryEdges', True),
    'feature': option('boolean', 'FeatureEdges', True),
    'manifold': option('boolean', 'ManifoldEdges', False),
    'nonManifold': option('boolean', 'NonManifoldEdges', True),
    'angle': option('number', 'FeatureAngle', 30, minimum=0, maximum=180),
}}
class FeatureEdges(NativeFilter):
    declaration = FEATURE_EDGES


TEMPORAL = {'id': 'temporalStatistics', 'native': 'TemporalStatistics', 'inputs': ONE, 'options': {
    'average': option('boolean', 'ComputeAverage', True),
    'minimum': option('boolean', 'ComputeMinimum', True),
    'maximum': option('boolean', 'ComputeMaximum', True),
    'standardDeviation': option('boolean', 'ComputeStandardDeviation', True),
}}
class TemporalStatistics(NativeFilter):
    declaration = TEMPORAL


FILTER_CLASSES = (WarpVector, WarpScalar, Shrink, Clean, CleanGrid, Delaunay3D,
                  Delaunay2D, Elevation, Gradient, CellSize, Connectivity,
                  Decimate, Smooth, Triangulate, Append, AppendGeometry,
                  Transform, Resample, Edges, FeatureEdges, TemporalStatistics)
