"""Scene and output validation plus native image publication."""
import copy
import hashlib
import math
from pathlib import Path
from schemaxis.core.declarations import validate_arguments, validate_value
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name, markers
from schemaxis.colours import rgba
from schemaxis.camera import VECTOR, CAMERA, staged_values, camera_values

STYLE = {
    'colour': {'type': 'union', 'options': [{'type': 'string'},
               {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 4}],
               'default': [0.7, 0.7, 0.7]},
    'field': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 2, 'maxItems': 2},
    'component': {'type': 'integer', 'default': -1, 'minimum': -1},
    'opacity': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 1},
    'representation': {'type': 'enum', 'values': ['Surface', 'Surface With Edges', 'Wireframe', 'Points', 'Outline'],
                       'default': 'Surface'},
    'range': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 2, 'maxItems': 2},
    'legend': {'type': 'boolean', 'default': False},
    'legendTitle': {'type': 'string'},
    'preset': {'type': 'string'},
    'logScale': {'type': 'boolean', 'default': False},
}




def style(value, location, deferred=False):
    result = staged_values(STYLE, value, location) if deferred else validate_arguments(STYLE, value, location=location)
    if list(markers(result)):
        return result
    colour = rgba(result['colour'], location + '.colour')
    result['colour'] = colour[:3]
    result['opacity'] *= colour[3]
    if 'field' in result and result['field'][0] not in ('POINTS', 'CELLS'):
        fail('INVALID_ASSOCIATION', 'field association must be POINTS or CELLS', location)
    if 'range' in result and result['range'][0] >= result['range'][1]:
        fail('INVALID_RANGE', 'colour range must be increasing', location)
    return result




def scenes(master):
    raw_scenes = master.document.get('scenes')
    if not isinstance(raw_scenes, list) or not raw_scenes:
        fail('EMPTY_PUBLICATION', 'at least one scene is required', '$.scenes')
    result, names, total = [], set(), 0
    for scene_index, raw in enumerate(raw_scenes):
        location = f'$.scenes[{scene_index}]'
        keys(raw, ('id', 'visible', 'geometry', 'measurements', 'images', 'appearances', 'gltf', 'exports'), location)
        scene_id = name(raw.get('id'), location + '.id')
        if scene_id in names:
            fail('DUPLICATE_SCENE', 'scene name must be unique', location + '.id')
        names.add(scene_id)
        visible = raw.get('visible', {})
        if not isinstance(visible, dict):
            fail('INVALID_SCENE', 'visible must map node names to styles', location + '.visible')
        base = {k: style(v, location + '.visible.' + k, deferred=True) for k, v in visible.items()}
        gltf = raw.get('gltf', False)
        if type(gltf) is not bool:
            fail('INVALID_PUBLICATION', 'gltf must be a boolean', location + '.gltf')
        outputs = raw.get('geometry', [])
        if not isinstance(outputs, list) or any(not isinstance(o, str) for o in outputs):
            fail('INVALID_PUBLICATION', 'geometry must list node names', location + '.geometry')
        measurements = raw.get('measurements', [])
        if not isinstance(measurements, list):
            fail('INVALID_PUBLICATION', 'measurements must be a list', location + '.measurements')
        measured = []
        for measurement_index, item in enumerate(measurements):
            measured.append(validate_arguments({
                'node': {'type': 'string', 'required': True},
                'association': {'type': 'enum', 'values': ['POINTS', 'CELLS', 'ROWS'], 'default': 'POINTS'},
            }, item, location=location + f'.measurements[{measurement_index}]'))
        from .writers import validate_exports
        exports = validate_exports(master, raw.get('exports', []), location + '.exports')
        roots = list(dict.fromkeys([*base, *outputs, *(m['node'] for m in measured), *(e['node'] for e in exports)]))
        for node in roots:
            if node in master.nodes and 'data' not in master.declarations[master.nodes[node]['filter']].get('kinds',['data']):
                fail('TYPE_MISMATCH', 'publication requires data; a native resource is not a dataset', location, node=node)
        roots.extend(node for item in exports for node in item.get('resources',{}).values())
        roots=list(dict.fromkeys(roots))
        late = list(markers({k: raw[k] for k in ('visible', 'appearances', 'images', 'exports') if k in raw}))
        master._check_markers(late, location + '.presentation')
        roots.extend(m.get('$observe', m.get('$sample')) for m in late if '$observe' in m or '$sample' in m)
        roots = list(dict.fromkeys(roots))
        selection = master.select(roots)
        for marker in late:
            if '$axis' in marker and marker['$axis'] not in selection.axes:
                fail('PRESENTATION_AXIS_UNAVAILABLE', 'presentation may reference only an active geometry axis; use camera samples for camera-only variation',
                     location, axis=marker['$axis'])
        appearances = raw.get('appearances', [{}])
        if not isinstance(appearances, list) or not appearances:
            fail('EMPTY_APPEARANCES', 'appearances must be a nonempty list', location + '.appearances')
        resolved_styles = []
        for appearance_index, appearance in enumerate(appearances):
            appearance_location = location + f'.appearances[{appearance_index}]'
            keys(appearance, base, appearance_location)
            for node, overrides in appearance.items():
                keys(overrides, STYLE, appearance_location + '.' + node)
            resolved_styles.append({k: style({**v, **appearance.get(k, {})}, appearance_location + '.' + k, deferred=True)
                                    for k, v in base.items()})
        writers, writer_names = [], set()
        images = raw.get('images', [])
        if not isinstance(images, list):
            fail('INVALID_PUBLICATION', 'images must be a list', location + '.images')
        for image_index, raw_writer in enumerate(images):
            image_location = location + f'.images[{image_index}]'
            keys(raw_writer, ('id', 'size', 'cameras'), image_location)
            writer_id = name(raw_writer.get('id'), image_location + '.id')
            if writer_id in writer_names:
                fail('DUPLICATE_WRITER', 'writer names must be unique within a scene', location)
            writer_names.add(writer_id)
            writer = validate_arguments({
                'id': {'type': 'string', 'required': True},
                'size': {'type': 'array', 'items': {'type': 'integer', 'minimum': 32, 'maximum': 8192},
                         'minItems': 2, 'maxItems': 2, 'default': [640, 480]},
            }, {k: v for k, v in raw_writer.items() if k != 'cameras'}, location=image_location)
            cameras = raw_writer.get('cameras')
            if not isinstance(cameras, list) or not cameras:
                fail('INVALID_CAMERA', 'cameras must be a nonempty explicit list', image_location + '.cameras')
            writer['cameras'] = [camera_values(camera, image_location + f'.cameras[{index}]', deferred=True)
                                 for index, camera in enumerate(cameras)]
            writers.append(writer)
        if (writers or gltf) and not base:
            fail('EMPTY_SCENE', 'images require visible objects', location)
        per_state = len(outputs) + len(measured) + len(exports) + len(appearances) * (int(gltf) + sum(len(w['cameras']) for w in writers))
        if not per_state:
            fail('EMPTY_PUBLICATION', 'scene has no requested output', location)
        total += per_state * selection.count
        result.append({'id': scene_id, 'visible': base, 'appearances': resolved_styles,
                       'geometry': outputs, 'measurements': measured, 'images': writers, 'gltf': gltf, 'exports': exports,
                       'selection': selection.to_dict(), 'publications': per_state * selection.count})
    limit = master.document.get('maxPublications', 10000)
    if type(limit) is not int or limit < 1:
        fail('INVALID_LIMIT', 'maxPublications must be a positive integer', '$.maxPublications')
    if total > limit:
        fail('EXPANSION_TOO_LARGE', 'publication count exceeds the limit', expected=total, limit=limit)
    return result


class Renderer:
    def __init__(self, backend):
        self.backend, self.pv = backend, backend.pv
        self.pv._DisableFirstRenderCameraReset()
        self.view = self.pv.CreateView('RenderView')
        self.view.OrientationAxesVisibility = 0
        self.view.UseColorPaletteForBackground = 0
        self.view.Background = [1, 1, 1]
        self.displays = {}
        self.colour_resources = {}
        self.scalar_bars = {}

    def clear(self):
        for display in self.displays.values():
            display.SetScalarBarVisibility(self.view, False)
            self.pv.Delete(display)
        self.displays.clear()
        for bar in self.scalar_bars.values():
            self.pv.Delete(bar)
        self.scalar_bars.clear()
        for resource in reversed(list(self.colour_resources.values())):
            self.pv.Delete(resource)
        self.colour_resources.clear()

    def prepare(self, handles, styles, *, time=0):
        # Rendering updates visible pipelines using the view's time, which is
        # independent of the explicit UpdatePipeline(time) used for geometry.
        self.view.ViewTime = time
        if not math.isfinite(self.view.ViewTime) or abs(self.view.ViewTime-time) > 1e-10*max(1,abs(time)):
            fail('VERIFICATION_FAILED', 'render view time differs from requested time')
        observed = {}
        for node, settings in styles.items():
            proxy = handles[node]
            display = self.displays.get(node)
            if display is None:
                display = self.pv.Show(proxy, self.view)
                self.displays[node] = display
            display.SetScalarBarVisibility(self.view, False)
            display.Representation = settings['representation']
            display.Opacity = settings['opacity']
            field = settings.get('field')
            if field:
                association, field_name = field
                arrays = proxy.PointData if association == 'POINTS' else proxy.CellData
                if field_name not in arrays.keys():
                    fail('MISSING_FIELD', 'visible object lacks requested colour field', node,
                         field=field_name, association=association, available=list(arrays.keys()))
                component = settings['component']
                if component >= arrays[field_name].GetNumberOfComponents():
                    fail('INVALID_COMPONENT', 'field component is out of range', node)
                self.pv.ColorBy(display, (association, field_name), separate=True)
                lut = self.pv.GetColorTransferFunction(field_name, display, separate=True)
                if 'preset' in settings and not lut.ApplyPreset(settings['preset'], True):
                    fail('UNKNOWN_COLOUR_PRESET', 'native colour preset is unavailable', node, preset=settings['preset'])
                lut.VectorMode = 'Magnitude' if component == -1 else 'Component'
                if component >= 0:
                    lut.VectorComponent = component
                bounds = settings.get('range', list(arrays[field_name].GetRange(component)))
                if not all(math.isfinite(v) for v in bounds):
                    fail('INVALID_RANGE', 'colour field range is not finite', node)
                if bounds[0] == bounds[1]:
                    bounds = [bounds[0], bounds[0] + max(1, abs(bounds[0])) * 1e-6]
                if settings['logScale'] and bounds[0] <= 0:
                    fail('INVALID_RANGE', 'logarithmic colour ranges must be positive', node)
                lut.UseLogScale = int(settings['logScale'])
                lut.RescaleTransferFunction(*bounds)
                display.SetScalarBarVisibility(self.view, settings['legend'])
                if settings['legend'] or 'legendTitle' in settings:
                    bar = self.pv.GetScalarBar(lut, self.view)
                    self.scalar_bars[bar.GetGlobalIDAsString()] = bar
                    bar.Title = settings.get('legendTitle', field_name)
                    bar.ComponentTitle = '' if arrays[field_name].GetNumberOfComponents() == 1 else ('Magnitude' if component == -1 else str(component))
                    bar.TitleColor = [0, 0, 0]
                    bar.LabelColor = [0, 0, 0]
                    bar.TitleFontSize = 12
                    bar.LabelFontSize = 11
                colour = list(display.ColorArrayName)
                if colour != list(field):
                    fail('VERIFICATION_FAILED', 'native colour selection differs', node, observed=colour)
            else:
                display.ColorArrayName = ['POINTS', '']
                display.DiffuseColor = settings['colour']
                display.AmbientColor = settings['colour']
                colour = list(display.DiffuseColor)
                if colour != list(settings['colour']):
                    fail('VERIFICATION_FAILED', 'native solid colour differs', node)
            if abs(display.Opacity - settings['opacity']) > 1e-10 or display.Representation != settings['representation']:
                fail('VERIFICATION_FAILED', 'native appearance differs', node)
            observed[node] = {'colour': colour, 'opacity': float(display.Opacity),
                              'representation': str(display.Representation)}
            for resource in (getattr(display, 'LookupTable', None),
                             getattr(display, 'ScalarOpacityFunction', None)):
                if resource is not None:
                    self.colour_resources[resource.GetGlobalIDAsString()] = resource
        return observed

    def frame(self, writer, camera, bounds):
        self.view.ViewSize = writer['size']
        bounds = camera.get('bounds', bounds)
        midpoint = [(bounds[i] + bounds[i + 1]) / 2 for i in (0, 2, 4)]
        diagonal = math.sqrt(sum((bounds[i+1] - bounds[i])**2 for i in (0, 2, 4)))
        if not math.isfinite(diagonal) or diagonal <= 0:
            fail('EMPTY_SCENE', 'cannot frame empty or degenerate bounds')
        focal = camera.get('focalPoint', midpoint)
        direction_scale = max(abs(v) for v in camera['direction'])
        direction = [v / direction_scale for v in camera['direction']]
        length = math.sqrt(sum(v*v for v in direction))
        distance = camera.get('distance', diagonal * 2)
        position = [focal[i] + direction[i] / length * distance for i in range(3)]
        self.view.CameraFocalPoint = focal
        self.view.CameraPosition = position
        self.view.CameraViewUp = camera['up']
        self.view.CameraParallelProjection = int(camera['parallel'])
        self.view.CameraParallelScale = camera.get('scale', diagonal * 0.5 * (1 + camera.get('padding', 0.1)) * max(1, writer['size'][1] / writer['size'][0]))
        self.pv.Render(self.view)
        return focal, position

    def write(self, path, writer, camera, bounds):
        focal, position = self.frame(writer, camera, bounds)
        self.pv.SaveScreenshot(str(path), self.view, ImageResolution=writer['size'])
        from vtkmodules.vtkIOImage import vtkPNGReader
        reader = vtkPNGReader()
        reader.SetFileName(str(path))
        reader.Update()
        output = reader.GetOutput()
        if list(output.GetDimensions())[:2] != writer['size'] or output.GetPointData().GetScalars() is None:
            fail('VERIFICATION_FAILED', 'image cannot be decoded at requested dimensions', str(path))
        pixels = output.GetPointData().GetScalars()
        first = pixels.GetTuple(0)
        if all(pixels.GetTuple(i) == first for i in range(pixels.GetNumberOfTuples())):
            fail('VERIFICATION_FAILED', 'image has uniform pixels', str(path))
        for actual, expected in ((self.view.CameraFocalPoint, focal), (self.view.CameraPosition, position)):
            if any(abs(a-b) > 1e-8 * max(1, abs(b)) for a, b in zip(actual, expected)):
                fail('VERIFICATION_FAILED', 'native camera differs from requested camera', str(path))
        return {'file': str(path), 'verified': True, 'dimensions': list(output.GetDimensions()),
                'viewTime': float(self.view.ViewTime),
                'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'pixelSha256': hashlib.sha256(bytes(int(pixels.GetValue(i)) for i in range(pixels.GetNumberOfValues()))).hexdigest(),
                'camera': {'position': list(self.view.CameraPosition), 'focalPoint': list(self.view.CameraFocalPoint),
                           'up': list(self.view.CameraViewUp), 'parallel': bool(self.view.CameraParallelProjection),
                           'scale': float(self.view.CameraParallelScale),
                           'viewAngle': float(self.view.GetClientSideObject().GetActiveCamera().GetViewAngle())}}

    def gltf(self, path, bounds):
        import base64
        import json
        from vtkmodules.vtkIOExport import vtkGLTFExporter
        from vtkmodules.vtkIOGeometry import vtkGLTFReader
        self.frame({'size': [640, 480]}, {'direction': [1, -1, 1], 'up': [0, 0, 1], 'parallel': True}, bounds)
        exporter = vtkGLTFExporter()
        exporter.SetRenderWindow(self.view.GetClientSideObject().GetRenderWindow())
        exporter.SetFileName(str(path))
        exporter.InlineDataOn()
        exporter.Write()
        document = json.loads(Path(path).read_text())
        if document.get('asset', {}).get('version') != '2.0' or not document.get('meshes'):
            fail('VERIFICATION_FAILED', 'glTF contains no meshes', str(path))
        for buffer in document.get('buffers', []):
            uri = buffer.get('uri', '')
            if not uri.startswith('data:') or len(base64.b64decode(uri.split(',', 1)[1])) != buffer['byteLength']:
                fail('VERIFICATION_FAILED', 'glTF buffer is not complete inline data', str(path))
        reader = vtkGLTFReader()
        reader.SetFileName(str(path))
        reader.Update()
        points = reader.GetOutput().GetNumberOfPoints()
        if points == 0:
            fail('VERIFICATION_FAILED', 'glTF cannot be reopened as nonempty geometry', str(path))
        return {'file': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'verified': True, 'meshes': len(document['meshes']), 'reopenedPoints': points,
                'verificationScope': 'glTF 2.0 structure, complete embedded buffers and nonempty native reopen',
                'losses': ['CFD field arrays and scientific units are not preserved as analysis data',
                           'native rendering effects may differ in other viewers']}

    def close(self):
        self.clear()
        self.pv.Delete(self.view)
