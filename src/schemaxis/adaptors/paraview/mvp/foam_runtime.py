# Copyright (C) 2026 David L F Gaden
"""Native real-case runtime, embedded with versioned helper source in each replay."""
import hashlib
import json
import math
from pathlib import Path

from _schemaxis_replay.faults import SchemaxisError, Fault
from _schemaxis_replay.times import resolve_times
from _schemaxis_replay.iteration import Axis, expand


def run_foam(config, normal, directory, options):
    from paraview import servermanager
    from paraview.simple import (OpenFOAMReader, MergeBlocks, Calculator, Slice,
        ExtractSurface, UpdatePipeline, SaveData, XMLPolyDataReader, Delete,
        CreateView, Show, ColorBy, GetColorTransferFunction, SaveScreenshot,
        Render, Outline, _DisableFirstRenderCameraReset)
    from vtkmodules.vtkIOImage import vtkPNGReader

    directory = Path(directory)
    receipt = directory / 'verification.json'
    evidence = {'verified': False, 'status': 'running', 'config': config,
                'normal': normal, 'options': options, 'states': [], 'images': [], 'events': [],
                'executionMode': 'serial pvbatch, native decomposed OpenFOAM reader; no MPI claim'}

    def publish():
        temporary = receipt.with_suffix('.tmp')
        temporary.write_text(json.dumps(evidence, allow_nan=False, indent=2) + '\n')
        temporary.replace(receipt)

    def fail(code, message, **observed):
        raise SchemaxisError(Fault(code, message, 'case', 'verification', observed=observed))

    def fields(proxy):
        return {association: [{'name': item.Name, 'components': item.GetNumberOfComponents(),
                               'range': list(item.GetRange())} for item in arrays.values()]
                for association, arrays in [('POINTS', proxy.PointData), ('CELLS', proxy.CellData)]}

    def inspect(proxy, origin, time):
        UpdatePipeline(time=time, proxy=proxy)
        data = servermanager.Fetch(proxy)
        cells, points = data.GetNumberOfCells(), data.GetNumberOfPoints()
        bounds = list(data.GetBounds())
        if not cells or not points or any(bounds[i] > bounds[i+1] for i in (0, 2, 4)):
            fail('EMPTY_GEOMETRY', 'Requested plane produced no usable geometry', cells=cells, points=points, bounds=bounds)
        coordinates = [data.GetPoint(i) for i in range(points)]
        distance = max(abs(sum((point[i]-origin[i])*normal[i] for i in range(3))) for point in coordinates)
        tolerance = max(1.0, max(abs(x) for x in bounds)) * 2e-6
        if not all(math.isfinite(x) for point in coordinates for x in point) or distance > tolerance:
            fail('VERIFICATION_FAILED', 'Slice coordinates are nonfinite or off plane', distance=distance, tolerance=tolerance)
        arrays = {}
        raw = {}
        for name, components in [('U', 3), ('p', 1), ('Umag', 1)]:
            array = data.GetCellData().GetArray(name)
            if array is None or array.GetNumberOfTuples() != cells or array.GetNumberOfComponents() != components:
                fail('MISSING_FIELD', 'Cell field is missing or incomplete', field=name, cells=cells)
            values = [array.GetTuple(i) for i in range(cells)]
            if not all(math.isfinite(x) for item in values for x in item):
                fail('VERIFICATION_FAILED', 'Field contains nonfinite values', field=name)
            raw[name] = values
            arrays[name] = {'association': 'CELLS', 'components': components, 'tuples': cells,
                            'range': list(array.GetRange(-1 if components == 3 else 0)),
                            'sha256': hashlib.sha256(memoryview(array)).hexdigest()}
        if not all(math.isclose(magnitude[0], math.hypot(*velocity), rel_tol=2e-6, abs_tol=1e-6) for magnitude, velocity in zip(raw['Umag'], raw['U'])):
            fail('VERIFICATION_FAILED', 'Umag differs from the magnitude of U')
        # Hash connectivity too: equal bounds/counts alone do not prove a reopen.
        topology = hashlib.sha256()
        for array in (data.GetPolys().GetOffsetsArray(), data.GetPolys().GetConnectivityArray()):
            topology.update(memoryview(array))
        return {'cells': cells, 'points': points, 'bounds': bounds, 'fields': arrays,
                'coordinatesSha256': hashlib.sha256(memoryview(data.GetPoints().GetData())).hexdigest(),
                'topologySha256': topology.hexdigest(), 'maximumPlaneDistance': distance}

    publish()
    try:
        reader = OpenFOAMReader(FileName=config['file'])
        reader.CaseType = 'Decomposed Case'
        reader.SkipZeroTime = 0
        reader.UpdatePipelineInformation()
        available = list(reader.CellArrays.Available)
        evidence['inspection'] = {'times': list(reader.TimestepValues),
                                  'regions': list(reader.MeshRegions.Available), 'availableCellFields': available}
        publish()
        missing = sorted(set(config['requiredFields'] + ['U', 'p']) - set(available))
        if missing:
            fail('MISSING_FIELD', 'Requested fields are unavailable', missing=missing, available=available)
        reader.MeshRegions = ['internalMesh']
        reader.CellArrays = list(dict.fromkeys(config['requiredFields'] + ['U', 'p']))
        reader.Createcelltopointfiltereddata = 1
        selection = resolve_times(config['times'], list(reader.TimestepValues))
        evidence['timeSelection'] = selection.to_dict()
        # Geometry is the outer nest; cameras never multiply this expansion.
        visits = expand([Axis.of('time', selection.values), Axis.of('position', config['fractions'])],
                        limit=config['maxPublications'])
        total = len(visits) * (1 + len(config['appearances']) * sum(len(w['cameras']) for w in config['writers']))
        if total > config['maxPublications']:
            fail('EXPANSION_TOO_LARGE', 'Publication expansion exceeds the declared limit', requested=total, limit=config['maxPublications'])
        evidence['visits'] = [visit.to_dict() for visit in visits]
        evidence['geometryAxisOrderFastestFirst'] = ['position', 'time']
        # Inspect the reference mesh once. Fixed world-space positions use these
        # bounds at every time, so all carry changes can precede computation.
        UpdatePipeline(time=selection.values[0], proxy=reader)
        reference_bounds = list(reader.GetDataInformation().GetBounds())
        if not reader.GetDataInformation().GetNumberOfCells() or not all(math.isfinite(x) for x in reference_bounds):
            fail('EMPTY_GEOMETRY', 'Reference time has no usable internal mesh')
        evidence['boundsReference'] = {'time': selection.values[0], 'bounds': reference_bounds}
        merged = MergeBlocks(Input=reader)
        calculator = Calculator(Input=merged)
        calculator.AttributeType = 'Cell Data'
        calculator.ResultArrayName = 'Umag'
        calculator.Function = 'mag(U)'
        slicer = Slice(Input=calculator)
        slicer.SliceType = 'Plane'
        slicer.SliceType.Normal = normal
        slicer.Triangulatetheslice = int(options['triangulate'])
        slicer.PointMergeMethod = {'uniformBinning': 'UniformBinning', 'octreeBinning': 'OctreeBinning', 'none': 'NotMergingPoints'}[options['pointMergeMethod']]
        surface = ExtractSurface(Input=slicer)
        proxies = {'reader': reader, 'merge': merged, 'calculator': calculator, 'slice': slicer, 'surface': surface}
        views = []
        if config['writers']:
            _DisableFirstRenderCameraReset()
            context = ExtractSurface(Input=calculator)
            outline = Outline(Input=calculator)
            proxies.update(context=context, outline=outline)
            for writer in config['writers']:
                view = CreateView('RenderView')
                view.ViewSize = writer['size']
                view.UseColorPaletteForBackground = 0
                view.Background = [1, 1, 1]
                view.OrientationAxesVisibility = 0
                view.CameraParallelProjection = 1
                slice_display = Show(surface, view)
                context_display = Show(context, view)
                context_display.Opacity = 0.12
                fixed = Show(outline, view)
                fixed.ColorArrayName = ['POINTS', '']
                fixed.DiffuseColor = [0, 0, 0]
                fixed.AmbientColor = [0, 0, 0]
                views.append((writer, view, slice_display, context_display, fixed))
        evidence['proxyIds'] = {name: proxy.GetGlobalIDAsString() for name, proxy in proxies.items()}
        previous_time = None
        previous_origin = None
        for visit in visits:
            state = visit.ordinal
            time = visit.coordinates['time']
            fraction = visit.coordinates['position']
            evidence['current'] = {'visit': visit.to_dict()}
            publish()
            # Establish the complete state before updating affected dependencies.
            bounds = reference_bounds
            midpoint = [(bounds[2*i] + bounds[2*i+1])/2 for i in range(3)]
            half_projection = sum(abs(normal[i]) * (bounds[2*i+1]-bounds[2*i])/2 for i in range(3))
            origin = [midpoint[i] + (2*fraction-1)*half_projection*normal[i] for i in range(3)]
            if not all(math.isfinite(value) for value in origin):
                fail('INVALID_SLICE_POSITION', 'Bounds-derived origin is not finite', fraction=fraction)
            if origin != previous_origin:
                slicer.SliceType.Origin = origin
            evidence['events'].append({'kind': 'update', 'state': state, 'changed': list(visit.changed)})
            if time != previous_time:
                UpdatePipeline(time=time, proxy=calculator)
                info = reader.GetDataInformation()
                evidence['inspection'].setdefault('selectedStates', []).append({
                    'time': time, 'bounds': list(info.GetBounds()), 'cells': info.GetNumberOfCells(),
                    'points': info.GetNumberOfPoints(), 'fields': fields(reader), 'calculatedFields': fields(calculator)})
            live = inspect(surface, origin, time)
            name = 'geometry-%04d.vtp' % state
            SaveData(str(directory / name), proxy=surface)
            reopened = XMLPolyDataReader(FileName=[str(directory / name)])
            try:
                written = inspect(reopened, origin, time)
            finally:
                Delete(reopened)
            if live != written:
                fail('VERIFICATION_FAILED', 'Reopened geometry differs from the live surface', live=live, reopened=written)
            identity = {name: proxy.GetGlobalIDAsString() for name, proxy in proxies.items()}
            if identity != evidence['proxyIds']:
                fail('VERIFICATION_FAILED', 'Pipeline objects changed within the run')
            evidence['states'].append({'visit': visit.to_dict(), 'origin': origin, 'file': name,
                                       'proxyIds': identity, 'live': live, 'reopened': written})
            evidence['events'].append({'kind': 'geometry', 'state': state})
            publish()
            for appearance in config['appearances'] if views else []:
                colours = {}
                for writer, view, display, context_display, fixed in views:
                    for label, target in [('slice', display), ('context', context_display)]:
                        ColorBy(target, ('CELLS', appearance))
                        colour = list(target.ColorArrayName)
                        if colour != ['CELLS', appearance]:
                            fail('VERIFICATION_FAILED', 'Display field differs from the appearance', colour=colour)
                        colours[label] = appearance
                    if list(fixed.DiffuseColor) != [0, 0, 0] or fixed.ColorArrayName[1]:
                        fail('VERIFICATION_FAILED', 'Fixed outline colour changed')
                    colours['outline'] = list(fixed.DiffuseColor)
                    lut = GetColorTransferFunction(appearance)
                    lut.RescaleTransferFunction(*live['fields'][appearance]['range'])
                evidence['events'].append({'kind': 'appearance', 'state': state, 'field': appearance, 'colours': colours})
                for writer, view, display, context_display, fixed in views:
                    view.ViewTime = time
                    radius = math.sqrt(sum((bounds[2*i+1]-bounds[2*i])**2 for i in range(3))) / 2
                    for camera_index, camera in enumerate(writer['cameras']):
                        direction = camera['direction']
                        length = math.hypot(*direction)
                        position = [midpoint[i] + direction[i]/length*radius*3 for i in range(3)]
                        view.CameraFocalPoint = midpoint
                        view.CameraPosition = position
                        view.CameraViewUp = camera['up']
                        view.CameraParallelScale = radius * 1.1
                        Render(view)
                        actual = {'position': list(view.CameraPosition), 'focalPoint': list(view.CameraFocalPoint),
                                  'up': list(view.CameraViewUp), 'parallelScale': view.CameraParallelScale}
                        if actual['position'] != position or actual['focalPoint'] != midpoint or actual['up'] != camera['up']:
                            fail('VERIFICATION_FAILED', 'Native camera differs from the writer sample', actual=actual)
                        filename = 'image-%04d-%s-%s-%02d.png' % (state, appearance, writer['name'], camera_index)
                        SaveScreenshot(str(directory / filename), view, ImageResolution=writer['size'])
                        png = vtkPNGReader()
                        png.SetFileName(str(directory / filename))
                        png.Update()
                        image = png.GetOutput()
                        dimensions = list(image.GetDimensions())
                        pixels = image.GetPointData().GetScalars()
                        if dimensions != writer['size'] + [1] or pixels is None:
                            fail('VERIFICATION_FAILED', 'PNG is unreadable or has wrong dimensions', file=filename, dimensions=dimensions)
                        if all(pixels.GetRange(i)[0] == pixels.GetRange(i)[1] for i in range(pixels.GetNumberOfComponents())):
                            fail('VERIFICATION_FAILED', 'Rendered image is uniform', file=filename)
                        event = {'kind': 'image', 'state': state, 'field': appearance, 'writer': writer['name'], 'camera': camera_index}
                        evidence['images'].append({'event': event, 'file': filename, 'verified': True,
                                                   'dimensions': dimensions, 'camera': actual,
                                                   'pixelSha256': hashlib.sha256(memoryview(pixels)).hexdigest()})
                        evidence['events'].append(event)
                        publish()
            previous_time, previous_origin = time, origin
        evidence.pop('current', None)
        evidence.update(verified=True, status='succeeded')
        publish()
    except Exception as error:
        fault = error.fault.to_dict() if isinstance(error, SchemaxisError) else {
            'code': 'VERIFICATION_FAILED', 'message': str(error), 'observed': {'exception': type(error).__name__}}
        evidence.update(verified=False, status='failed', fault=fault)
        publish()
        raise
