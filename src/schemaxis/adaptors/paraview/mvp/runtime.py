"""Standalone verification code embedded in the exact submitted replay.

This file runs inside ParaView's interpreter. Keep it independent of Schemaxis imports
so replay does not depend on an Schemaxis installation or a matching Python version.
"""
import json
import math
from pathlib import Path


def check_native_options(proxy, properties, directory):
    for name, value in properties.items():
        available = proxy.ListProperties()
        if name not in available:
            message = 'installed Slice does not expose ' + name
            observed = {'property': name, 'available': available}
        else:
            prop = proxy.GetProperty(name)
            choices = prop.Available if hasattr(prop, 'Available') else None
            if choices is None or value in choices:
                continue
            message = 'installed Slice does not accept this option for ' + name
            observed = {'property': name, 'requested': value, 'available': choices}
        (Path(directory) / 'verification.json').write_text(json.dumps({'fault': {
            'code': 'UNSUPPORTED_NATIVE_OPTION', 'message': message, 'observed': observed,
        }}, indent=2) + '\n', encoding='utf-8')
        raise RuntimeError(message)


def export_verified_slice(proxy, origin, normal, directory, source_proxy, options):
    from paraview import servermanager
    from paraview.simple import (UpdatePipeline, SaveData, XMLPolyDataReader,
                                 XMLUnstructuredGridReader, Delete)

    directory = Path(directory)
    receipt = directory / 'verification.json'

    def fail(code, message, observed):
        receipt.write_text(json.dumps({
            'fault': {'code': code, 'message': message, 'observed': observed}
        }, allow_nan=False, indent=2) + '\n', encoding='utf-8')
        raise RuntimeError(message)

    native_configuration = {'crinkle': bool(proxy.Crinkleslice),
                            'triangulate': bool(proxy.Triangulatetheslice),
                            'pointLocatorProxy': proxy.PointMergeMethod.SMProxy.GetXMLName()}
    if any(native_configuration[name] != options[name] for name in ('crinkle', 'triangulate')):
        fail('VERIFICATION_FAILED', 'native slice configuration differs from the request', native_configuration)
    crinkle = options['crinkle']
    source_cells = set()

    def cell_signature(data, index):
        cell = data.GetCell(index)
        return (cell.GetCellType(), tuple(sorted(
            tuple(data.GetPoint(cell.GetPointId(i))) for i in range(cell.GetNumberOfPoints()))))

    if crinkle:
        UpdatePipeline(proxy=source_proxy)
        input_data = servermanager.Fetch(source_proxy)
        source_cells = {cell_signature(input_data, i) for i in range(input_data.GetNumberOfCells())}

    def inspect(proxy):
        UpdatePipeline(proxy=proxy)
        info = proxy.GetDataInformation()
        bounds = list(info.GetBounds())
        cells = info.GetNumberOfCells()
        points = info.GetNumberOfPoints()
        if not all(math.isfinite(v) for v in bounds):
            fail('DATA_NOT_READY', 'slice bounds are not finite', {'bounds': repr(bounds)})
        if any(bounds[i] > bounds[i + 1] for i in (0, 2, 4)) or cells == 0 or points == 0:
            fail('EMPTY_GEOMETRY', 'the requested plane produced no usable geometry',
                 {'bounds': bounds, 'cells': cells, 'points': points})
        data = servermanager.Fetch(proxy)
        field = data.GetPointData().GetArray('RTData')
        if field is None or field.GetNumberOfTuples() != points:
            fail('VERIFICATION_FAILED', 'RTData point field is missing or incomplete', {})
        field_range = list(field.GetRange())
        if not all(math.isfinite(field.GetTuple1(i)) for i in range(points)):
            fail('VERIFICATION_FAILED', 'RTData contains nonfinite values', {})
        coordinates = [data.GetPoint(i) for i in range(points)]
        if not all(math.isfinite(value) for point in coordinates for value in point):
            fail('VERIFICATION_FAILED', 'geometry contains nonfinite coordinates', {})
        distance = max(abs(sum((point[j] - origin[j]) * normal[j]
                               for j in range(3))) for point in coordinates)
        if not math.isfinite(distance) or (not crinkle and distance > 1e-5):
            fail('VERIFICATION_FAILED', 'geometry does not lie on the requested plane',
                 {'maximumPlaneDistance': repr(distance)})
        cell_types = sorted({data.GetCellType(i) for i in range(cells)})
        if crinkle:
            for i in range(cells):
                signature = cell_signature(data, i)
                distances = [sum((point[j] - origin[j]) * normal[j] for j in range(3))
                             for point in signature[1]]
                if signature not in source_cells or min(distances) > 1e-5 or max(distances) < -1e-5:
                    fail('VERIFICATION_FAILED', 'crinkle output is not an intersected whole input cell',
                         {'cell': i})
        elif options['triangulate'] and cell_types != [5]:  # VTK_TRIANGLE
            fail('VERIFICATION_FAILED', 'triangulation was requested but output contains other cells',
                 {'cellTypes': cell_types})
        return {'cellTypes': cell_types, 'bounds': bounds, 'cells': cells, 'points': points,
                'field': 'RTData', 'association': 'POINTS', 'fieldRange': field_range,
                'maximumPlaneDistance': distance}

    original = inspect(proxy)
    geometry = directory / ('slice.vtu' if crinkle else 'slice.vtp')
    SaveData(str(geometry), proxy=proxy)
    reader = XMLUnstructuredGridReader if crinkle else XMLPolyDataReader
    reopened = reader(FileName=[str(geometry)])
    try:
        written = inspect(reopened)
    finally:
        Delete(reopened)
    if original != written:
        fail('VERIFICATION_FAILED', 'reopened geometry differs from the live slice',
             {'live': original, 'reopened': written})
    evidence = {'verified': True, 'checks': ['nonempty', 'finiteBounds',
                'intersectedWholeInputCells' if crinkle else 'plane',
                'pointField', 'reopenedSummary'], 'live': original, 'reopened': written,
                'origin': origin, 'normal': normal, 'options': options,
                'geometryFile': geometry.name, 'nativeConfiguration': native_configuration,
                'verificationLimits': ['Point locator selection is read back; its effect on duplicate points is input-dependent and not certified by these checks.'],
                'inapplicableOptions': ['triangulate', 'pointMergeMethod'] if crinkle else []}
    receipt.write_text(json.dumps(evidence, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    return evidence


def export_verified_sweep(proxy, origins, normal, directory, source_proxy, options, resolution):
    """Visit positions with one native slicer; retain progress before each update."""
    directory = Path(directory)
    receipt = directory / 'verification.json'
    identity = proxy.GetGlobalIDAsString()
    evidence = {'verified': False, 'status': 'running', 'requested': len(origins),
                'completed': 0, 'slices': [], 'resolution': resolution,
                'sliceProxyId': identity}

    def publish():
        # Replacement avoids a truncated progress receipt if the process stops
        # while serializing a later position.
        temporary = directory / 'verification.tmp'
        temporary.write_text(json.dumps(evidence, allow_nan=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(receipt)

    publish()
    for index, origin in enumerate(origins):
        child = directory / ('slice-%04d' % index)
        evidence['current'] = {'index': index, 'origin': origin, 'directory': child.name}
        publish()
        try:
            child.mkdir(exist_ok=False)
            proxy.SliceType.Origin = origin
            item = export_verified_slice(proxy, origin, normal, str(child), source_proxy, options)
            current_identity = proxy.GetGlobalIDAsString()
            if current_identity != identity:
                raise RuntimeError('slice proxy identity changed within the sweep')
            evidence['slices'].append({'index': index, 'origin': origin,
                                       'directory': child.name, 'sliceProxyId': current_identity,
                                       **item})
            evidence['completed'] += 1
            publish()
        except Exception as error:
            child_receipt = child / 'verification.json'
            detail = json.loads(child_receipt.read_text()) if child_receipt.is_file() else {}
            fault = detail.get('fault', {'code': 'VERIFICATION_FAILED', 'message': str(error), 'observed': {}})
            evidence.update(status='failed', fault={
                'code': fault['code'], 'message': fault['message'],
                'observed': {**fault['observed'], 'index': index, 'origin': origin,
                             'completed': evidence['completed'], 'requested': len(origins),
                             'completedDirectories': [item['directory'] for item in evidence['slices']]}})
            publish()
            raise
    evidence.update(verified=True, status='succeeded')
    evidence.pop('current', None)
    publish()
    return evidence
