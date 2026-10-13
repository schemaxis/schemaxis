"""Native distributed publication: fetch only compact per-rank fingerprints."""
import hashlib
import json
from pathlib import Path
from schemaxis.errors import fail
from .parallel_files import manifest, file_digest, canonical


def array_fingerprint(array):
    if array is None:
        return None
    result = {'type': array.GetDataTypeAsString(), 'shape': [array.GetNumberOfTuples(), array.GetNumberOfComponents()]}
    if result['type'] == 'char':
        result['type'] = 'signed char' if array.GetDataTypeMin() < 0 else 'unsigned char'
    hasher = hashlib.sha256()
    if array.GetDataType() == 13:
        for index in range(array.GetNumberOfValues()):
            value = array.GetValue(index).encode('utf-8')
            hasher.update(len(value).to_bytes(8, 'big'))
            hasher.update(value)
    else:
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        values = vtk_to_numpy(array)
        # Bounded scratch space; never form a Python list of mesh coordinates or tuples.
        for start in range(0, len(values), 32768):
            block = values[start:start+32768]
            if not np.isfinite(block).all():
                fail('NONFINITE_DATA', 'distributed output contains nonfinite values', array.GetName() or 'array')
            hasher.update(block.astype(block.dtype.newbyteorder('>'), copy=False).tobytes())
    return {**result, 'sha256': hasher.hexdigest()}


def leaf_fingerprint(data):
    if not (data.IsA('vtkPolyData') or data.IsA('vtkUnstructuredGrid')):
        fail('UNSUPPORTED_MPI_OUTPUT', 'parallel verification supports polydata and unstructured grids', data.GetClassName())
    result = {'type': data.GetClassName(), 'points': data.GetNumberOfPoints(), 'cells': data.GetNumberOfCells(),
              'coordinates': array_fingerprint(data.GetPoints().GetData()) if data.GetPoints() else None}
    def topology(cells):
        return {'offsets': array_fingerprint(cells.GetOffsetsArray()),
                'connectivity': array_fingerprint(cells.GetConnectivityArray())}
    if data.IsA('vtkPolyData'):
        for key, cells in [('verts', data.GetVerts()), ('lines', data.GetLines()), ('polys', data.GetPolys()), ('strips', data.GetStrips())]:
            result[key] = topology(cells)
    else:
        result['topology'] = topology(data.GetCells())
        result['cellTypes'] = array_fingerprint(data.GetCellTypesArray())
        # Polyhedral connectivity carries faces in addition to ordinary cell point IDs.
        for key, method in [('faces', 'GetFaces'), ('faceLocations', 'GetFaceLocations')]:
            if hasattr(data, method):
                result[key] = array_fingerprint(getattr(data, method)())
    for key, arrays in [('pointData', data.GetPointData()), ('cellData', data.GetCellData()), ('fieldData', data.GetFieldData())]:
        result[key] = [{'name': arrays.GetArrayName(index), 'data': array_fingerprint(arrays.GetAbstractArray(index))}
                       for index in range(arrays.GetNumberOfArrays())]
        result[key].sort(key=lambda entry: entry['name'] or '')
    return result


def local_record(data):
    """Runs on every rank, including empty ranks. Exceptions become returned evidence."""
    from vtkmodules.vtkParallelCore import vtkMultiProcessController
    controller = vtkMultiProcessController.GetGlobalController()
    rank = controller.GetLocalProcessId() if controller else 0
    size = controller.GetNumberOfProcesses() if controller else 1
    try:
        if data.GetNumberOfCells() == 0 and data.GetNumberOfPoints() == 0:
            return {'rank': rank, 'size': size, 'empty': True}
        return {'rank': rank, 'size': size, 'data': leaf_fingerprint(data)}
    except Exception as error:
        return {'rank': rank, 'size': size, 'error': str(error)}


def summaries(backend, proxy, time, association=None):
    from vtkmodules.vtkParallelCore import vtkMultiProcessController
    controller = vtkMultiProcessController.GetGlobalController()
    ranks = controller.GetNumberOfProcesses() if controller else 1
    # Use the retained runtime archive on each rank; authored input cannot supply this script.
    import schemaxis
    runtime = str(Path(schemaxis.__file__).parent.parent)
    script = (
        f'import sys, json\nsys.path.insert(0, {runtime!r})\n'
        'from schemaxis.adaptors.paraview.parallel_native import local_record, local_measurement\n'
        'from vtkmodules.vtkCommonCore import vtkStringArray, vtkPoints\n'
        'from vtkmodules.vtkCommonDataModel import vtkCellArray\n' +
        (f'result = local_measurement(self.GetInputDataObject(0, 0), {association!r})\n' if association is not None else
         'result = local_record(self.GetInputDataObject(0, 0))\n') +
        'column = vtkStringArray()\ncolumn.SetName("schemaxisSummary")\n'
        'column.InsertNextValue(json.dumps(result, allow_nan=False))\n'
        'output = self.GetOutputDataObject(0)\n'
        'points = vtkPoints()\npoints.InsertNextPoint(result["rank"], 0, 0)\noutput.SetPoints(points)\n'
        'cells = vtkCellArray()\ncells.InsertNextCell(1)\ncells.InsertCellPoint(0)\noutput.SetVerts(cells)\n'
        'output.GetPointData().AddArray(column)\n')
    summary = backend.pv.ProgrammableFilter(Input=proxy, OutputDataSetType='vtkPolyData', Script=script)
    try:
        from .writers import checked_update
        checked_update(backend, summary, time, 'distributed verification')
        # Only O(ranks × array metadata) crosses this boundary, never geometry.
        table = backend.sm.Fetch(summary)
        column = table.GetPointData().GetAbstractArray('schemaxisSummary')
        if column is None or column.GetNumberOfValues() != ranks:
            fail('VERIFICATION_FAILED', 'missing rank summaries', expected=ranks, rows=table.GetNumberOfPoints(), arrays=[table.GetPointData().GetArrayName(i) for i in range(table.GetPointData().GetNumberOfArrays())], values=column.GetNumberOfValues() if column else None)
        result = sorted([json.loads(column.GetValue(i)) for i in range(ranks)], key=lambda value: value['rank'])
        if [record['rank'] for record in result] != list(range(ranks)) or any(record['size'] != ranks or 'error' in record for record in result):
            fail('VERIFICATION_FAILED', 'rank summaries failed or disagree', summaries=result)
        return result
    finally:
        backend.pv.Delete(summary)


def geometry(backend, proxy, path, allow_empty=False):
    info = proxy.GetDataInformation()
    formats = {'vtkPolyData': '.pvtp', 'vtkUnstructuredGrid': '.pvtu'}
    if info.GetDataClassName() not in formats:
        fail('UNSUPPORTED_MPI_OUTPUT', 'merge composite blocks before distributed publication', type=info.GetDataClassName())
    if not allow_empty and info.GetNumberOfPoints() == 0:
        fail('EMPTY_GEOMETRY', 'parallel output contains no points')
    path = Path(str(path)+formats[info.GetDataClassName()])
    time = backend.records.get(id(proxy), {}).get('time', 0)
    before = summaries(backend, proxy, time)
    from .writers import checked_update, preserve_field_data
    writer = backend.pv.CreateWriter(str(path), proxy)
    if writer is None:
        fail('UNAVAILABLE_WRITER', 'native parallel XML writer is unavailable', str(path))
    try:
        preserve_field_data(writer, {})
        checked_update(backend, writer, time, str(path))
    finally:
        backend.pv.Delete(writer)
    reader = backend.pv.OpenDataFile(str(path))
    if reader is None:
        fail('UNAVAILABLE_READER', 'native parallel XML reader is unavailable', str(path))
    try:
        checked_update(backend, reader, time, str(path))
        after = summaries(backend, reader, time)
    finally:
        backend.pv.Delete(reader)
    if canonical(before) != canonical(after):
        fail('VERIFICATION_FAILED', 'parallel piece readback differs in geometry, topology or fields', str(path), before=before, after=after)
    return {'file': str(path), 'sha256': file_digest(path), 'files': manifest(path),
            'verified': True, 'publicationMode': 'native-distributed',
            'verification': {'method': 'exact-per-piece-v1', 'before': before, 'after': after,
                             'gatheredGeometry': False},
            'dataDigest': hashlib.sha256(json.dumps(canonical(before)).encode()).hexdigest()}


def local_measurement(data, association):
    """Copy only the logical tuples from a native reduction, not its allocated capacity."""
    from vtkmodules.vtkParallelCore import vtkMultiProcessController
    controller = vtkMultiProcessController.GetGlobalController()
    record = {'rank': controller.GetLocalProcessId(), 'size': controller.GetNumberOfProcesses()}
    try:
        import math
        arrays = data.GetPointData() if association == 'POINTS' else data.GetCellData()
        count = data.GetNumberOfPoints() if association == 'POINTS' else data.GetNumberOfCells()
        if count == 0:
            return {**record, 'empty': True}
        if count != 1:
            fail('UNBOUNDED_MPI_MEASUREMENT', 'native integration must produce one tuple', tuples=count)
        fields = [arrays.GetArray(i) for i in range(arrays.GetNumberOfArrays()) if arrays.GetArray(i) is not None]
        headers = [f'{a.GetName()}[{c}]' for a in fields for c in range(a.GetNumberOfComponents())]
        values = [a.GetComponent(0, c) for a in fields for c in range(a.GetNumberOfComponents())]
        if not values or not all(math.isfinite(value) for value in values):
            fail('NONFINITE_DATA', 'native reduction is empty or contains nonfinite values')
        return {**record, 'headers': headers, 'values': values}
    except Exception as error:
        return {**record, 'error': str(error)}


def measurement(backend, proxy, path, association):
    import csv
    if association not in ('POINTS', 'CELLS'):
        fail('INVALID_ASSOCIATION', 'distributed reductions support point or cell data')
    if backend.records.get(id(proxy), {}).get('declaration', {}).get('id') != 'integrate':
        fail('UNBOUNDED_MPI_MEASUREMENT', 'integrate the dataset before measuring')
    records = summaries(backend, proxy, backend.records[id(proxy)].get('time', 0), association)
    nonempty = [record for record in records if 'values' in record]
    if len(nonempty) != 1:
        fail('VERIFICATION_FAILED', 'native global integration did not produce exactly one result', records=records)
    headers = ['index', *nonempty[0]['headers']]
    rows = [[0, *nonempty[0]['values']]]
    path = Path(str(path)+'.csv')
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)
    with path.open(newline='') as stream:
        reader = csv.reader(stream)
        if next(reader) != headers or [[float(value) for value in row] for row in reader] != rows:
            fail('VERIFICATION_FAILED', 'reduced measurement readback differs')
    return {'file': str(path), 'sha256': file_digest(path), 'verified': True,
            'association': association, 'rows': 1, 'columns': headers, 'values': rows,
            'units': 'not inferred', 'reductionEvidence': records, 'gatheredGeometry': False}
