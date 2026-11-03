# Copyright (C) 2026 David L F Gaden
"""Native data access and representation-preserving semantic snapshots."""
import hashlib
import math
import struct
from schemaxis.errors import fail


def array_record(array, tuples=None):
    if array is None:
        return None
    if array.GetDataType() == 13:  # VTK_STRING
        return {'dtype':'string', 'shape':[array.GetNumberOfTuples(),array.GetNumberOfComponents()],
                'values': [array.GetValue(i) for i in range(array.GetNumberOfValues())]}
    count = array.GetNumberOfTuples() if tuples is None else tuples
    if count > array.GetNumberOfTuples():
        fail('INVALID_DATA', 'coordinate array is shorter than its grid dimension')
    components = array.GetNumberOfComponents()
    hasher = hashlib.sha256()
    data_type = array.GetDataTypeAsString()
    floating = data_type in ('float', 'double')
    if floating:
        pack = struct.Struct('!' + 'd' * components).pack
        for i in range(count):
            values = array.GetTuple(i)
            if not all(math.isfinite(v) for v in values):
                fail('NONFINITE_DATA', 'an output array contains nonfinite values', array.GetName() or 'array')
            hasher.update(pack(*values))
    else:
        # Preserve integer identities rather than rounding through double.
        for i in range(count * components):
            if hasattr(array, 'GetValue'):
                value = array.GetValue(i)
            else:
                variant = array.GetVariantValue(i)
                value = (variant.ToUnsignedLongLong() if data_type.startswith('unsigned')
                         else variant.ToLongLong())
            if isinstance(value, str):
                value = ord(value)
                if array.GetDataTypeMin() < 0 and value > 127:
                    value -= 256
            hasher.update((str(value) + ',').encode())
    if data_type == 'char':
        data_type = 'signed char' if array.GetDataTypeMin() < 0 else 'unsigned char'
    return {'shape': [count, components],
            'dtype': data_type, 'sha256': hasher.hexdigest()}


def _snapshot(data):
    if data is None:
        return None
    if data.IsA('vtkPartitionedDataSetCollection') or data.IsA('vtkPartitionedDataSet'):
        from vtkmodules.vtkCommonDataModel import vtkCompositeDataSet
        collection = data.IsA('vtkPartitionedDataSetCollection')
        count = data.GetNumberOfPartitionedDataSets() if collection else data.GetNumberOfPartitions()
        child = data.GetPartitionedDataSet if collection else data.GetPartition
        result = {'type': data.GetClassName(),
                  'names': [data.GetMetaData(i).Get(vtkCompositeDataSet.NAME()) if data.HasMetaData(i) else None for i in range(count)],
                  'children': [snapshot(child(i)) for i in range(count)]}
        if collection and data.GetDataAssembly():
            from vtkmodules.vtkCommonCore import vtkIndent
            result['assembly'] = data.GetDataAssembly().SerializeToXML(vtkIndent())
        return result
    if data.IsA('vtkUniformGridAMR'):
        levels = []
        for level in range(data.GetNumberOfLevels()):
            blocks = []
            for index in range(data.GetNumberOfDataSets(level)):
                box = data.GetAMRBox(level, index) if data.IsA('vtkOverlappingAMR') else None
                dimensions = [0] * 6
                if box: box.GetDimensions(dimensions)
                origin = [0.0] * 3
                if data.IsA('vtkOverlappingAMR'): data.GetOrigin(level, index, origin)
                blocks.append({'data': snapshot(data.GetDataSet(level, index)),
                               'box': dimensions if box else None, 'origin': origin})
            levels.append(blocks)
        return {'type': data.GetClassName(), 'levels': levels}
    if data.IsA('vtkHyperTreeGrid'):
        trees = []
        def visit(cursor):
            node = {'masked': bool(cursor.IsMasked()), 'leaf': bool(cursor.IsLeaf())}
            if not cursor.IsLeaf():
                node['children'] = []
                for child in range(data.GetNumberOfChildren()):
                    cursor.ToChild(child)
                    node['children'].append(visit(cursor))
                    cursor.ToParent()
            return node
        for index in range(data.GetMaxNumberOfTrees()):
            if data.GetTree(index):
                trees.append({'index': index, 'tree': visit(data.NewNonOrientedCursor(index, False))})
        arrays = data.GetCellData()
        return {'type': data.GetClassName(), 'dimensions': list(data.GetDimensions()),
                'branchFactor': data.GetBranchFactor(), 'trees': trees,
                'coordinates': [array_record(a) for a in (data.GetXCoordinates(), data.GetYCoordinates(), data.GetZCoordinates())],
                'cellData': {arrays.GetArrayName(i): array_record(arrays.GetAbstractArray(i)) for i in range(arrays.GetNumberOfArrays())}}
    if data.IsA('vtkGraph'):
        result = {'type': data.GetClassName(), 'vertices': data.GetNumberOfVertices(),
                  'edges': [[data.GetSourceVertex(i), data.GetTargetVertex(i)] for i in range(data.GetNumberOfEdges())],
                  'coordinates': array_record(data.GetPoints().GetData()) if data.GetPoints() else None}
        for key, arrays in [('vertexData', data.GetVertexData()), ('edgeData', data.GetEdgeData())]:
            result[key] = {arrays.GetArrayName(i): array_record(arrays.GetAbstractArray(i)) for i in range(arrays.GetNumberOfArrays())}
        return result
    if data.IsA('vtkMultiBlockDataSet'):
        from vtkmodules.vtkCommonDataModel import vtkCompositeDataSet
        return {'type': data.GetClassName(),
                'names': [data.GetMetaData(i).Get(vtkCompositeDataSet.NAME()) if data.HasMetaData(i) else None
                          for i in range(data.GetNumberOfBlocks())],
                'blocks': [snapshot(data.GetBlock(i)) if data.GetBlock(i) else None
                           for i in range(data.GetNumberOfBlocks())]}
    if data.IsA('vtkTable'):
        arrays = data.GetRowData()
        return {'type': data.GetClassName(), 'rows': data.GetNumberOfRows(),
                'rowData': {arrays.GetArrayName(i): array_record(arrays.GetAbstractArray(i))
                            for i in range(arrays.GetNumberOfArrays())}}
    result = {'type': data.GetClassName(), 'points': data.GetNumberOfPoints(),
              'cells': data.GetNumberOfCells()}
    if data.IsA('vtkImageData'):
        result.update(extent=list(data.GetExtent()), origin=list(data.GetOrigin()), spacing=list(data.GetSpacing()))
        if hasattr(data, 'GetDirectionMatrix'):
            direction = data.GetDirectionMatrix()
            result['direction'] = [direction.GetElement(i, j) for i in range(3) for j in range(3)]
    elif data.IsA('vtkStructuredGrid'):
        result['extent'] = list(data.GetExtent())
    elif data.IsA('vtkRectilinearGrid'):
        # ParaView 5.13 Fetch may pad each coordinate array to total point count.
        # Only dimension-sized prefixes define the rectilinear grid; padding is
        # uninitialised and changes between otherwise identical fetches.
        dimensions = data.GetDimensions()
        result.update(extent=list(data.GetExtent()),
                      x=array_record(data.GetXCoordinates(), dimensions[0]),
                      y=array_record(data.GetYCoordinates(), dimensions[1]),
                      z=array_record(data.GetZCoordinates(), dimensions[2]))
    if hasattr(data, 'GetPoints') and data.GetPoints():
        result['coordinates'] = array_record(data.GetPoints().GetData())
    if data.IsA('vtkPolyData'):
        for key, cells in (('verts', data.GetVerts()), ('lines', data.GetLines()),
                           ('polys', data.GetPolys()), ('strips', data.GetStrips())):
            result[key] = array_record(cells.GetData())
    elif data.IsA('vtkUnstructuredGrid'):
        result['connectivity'] = array_record(data.GetCells().GetData())
        result['cellTypes'] = array_record(data.GetCellTypesArray())
    for key, arrays in (('pointData', data.GetPointData()), ('cellData', data.GetCellData())):
        result[key] = {arrays.GetArrayName(i): array_record(arrays.GetAbstractArray(i))
                       for i in range(arrays.GetNumberOfArrays())}
    return result


def snapshot(data):
    """Preserve scientific arrays, geometry, topology, hierarchy and field data."""
    result = _snapshot(data)
    if data is not None and hasattr(data, 'GetFieldData'):
        arrays = data.GetFieldData()
        if arrays and arrays.GetNumberOfArrays():
            result['fieldData'] = {arrays.GetArrayName(i): array_record(arrays.GetAbstractArray(i))
                                   for i in range(arrays.GetNumberOfArrays())}
    return result
