"""Typed sprite operations and independent native readback verification."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.artifacts import atomic_json
from schemaxis.dispatch import SubprocessRunner
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name


def integer(low, high, default=None):
    result = {'type': 'integer', 'minimum': low, 'maximum': high}
    result.update({'required': True} if default is None else {'default': default})
    return result


NAME = {'type': 'string', 'minLength': 1, 'maxLength': 64, 'required': True}
COLOUR = {'type': 'array', 'items': integer(0, 255), 'minItems': 4, 'maxItems': 4, 'required': True}
PALETTE = {'type': 'array', 'items': COLOUR, 'minItems': 1, 'maxItems': 256,
           'default': [[0, 0, 0, 0], [255, 255, 255, 255]]}


def declaration(native, options, root=False):
    return {'native': native, 'kinds': ['sprite'],
            'options': {k: {'value': v} for k, v in options.items()},
            'inputs': {} if root else {'sprite': {'required': True, 'kind': 'sprite'}}}


DRAW = {'layer': NAME, 'frame': integer(1, 32, 1), 'x': integer(0, 255),
        'y': integer(0, 255), 'colour': COLOUR}
DECLARATIONS = {
    'sprite': declaration('Sprite', {'width': integer(1, 256), 'height': integer(1, 256),
        'layer': {**NAME, 'required': False, 'default': 'base'},
        'durationMS': integer(1, 65535, 100), 'colours': PALETTE}, True),
    'layer': declaration('Sprite:newLayer', {'name': NAME}),
    'frame': declaration('Sprite:newEmptyFrame', {'durationMS': integer(1, 65535, 100)}),
    'palette': declaration('Sprite:setPalette', {'colours': {**PALETTE, 'required': True}}),
    'pixel': declaration('Image:drawPixel', DRAW),
    'rect': declaration('Image:drawPixel', {**DRAW, 'width': integer(1, 256), 'height': integer(1, 256)}),
    'circle': declaration('Image:drawPixel', {**DRAW, 'radius': integer(0, 127)}),
    'tag': declaration('Sprite:newTag', {'name': NAME, 'fromFrame': integer(1, 32),
        'toFrame': integer(1, 32), 'direction': {'type': 'enum',
        'values': ['forward', 'reverse', 'pingPong', 'pingPongReverse'], 'default': 'forward'}}),
}
del DECLARATIONS['palette']['options']['colours']['value']['default']
FILES = ('sprite.aseprite', 'preview.png', 'sheet.png', 'sheet.json')


def plan(document):
    keys(document, ('version', 'nodes', 'output'), '$')
    if document.get('version') != 'schemaxis.aseprite/1':
        fail('UNSUPPORTED_VERSION', 'use schemaxis.aseprite/1')
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 256:
        fail('INVALID_DOCUMENT', 'provide 1 to 256 nodes', '$.nodes')
    prepared, seen, layers, tags = [], set(), [], set()
    frames, width, height = 1, 0, 0
    for index, node in enumerate(nodes):
        loc = f'$.nodes[{index}]'
        keys(node, ('id', 'filter', 'options', 'inputs'), loc)
        identity = name(node.get('id'), loc+'.id')
        if identity in seen:
            fail('DUPLICATE_NODE', 'use unique node ids', loc+'.id')
        op = node.get('filter')
        if not isinstance(op, str) or op not in DECLARATIONS:
            fail('UNKNOWN_FILTER', 'use a declared Aseprite operation', loc+'.filter')
        if (index == 0) != (op == 'sprite'):
            fail('INVALID_DEPENDENCY', 'start with exactly one sprite node', loc)
        inputs = node.get('inputs', {})
        keys(inputs, () if index == 0 else ('sprite',), loc+'.inputs')
        if inputs != ({} if index == 0 else {'sprite': prepared[-1]['id']}):
            fail('INVALID_DEPENDENCY', 'sprite input must reference the immediately preceding node', loc+'.inputs')
        options = validate_arguments({k: v['value'] for k, v in DECLARATIONS[op]['options'].items()},
                                     node.get('options', {}), location=loc+'.options')
        for key in ('name', 'layer'):
            if key in options and '\0' in options[key]:
                fail('INVALID_ARGUMENT', 'names cannot contain NUL characters', loc+'.options.'+key)
        for colour in options.get('colours', []) + ([options['colour']] if 'colour' in options else []):
            if colour[3] not in (0, 255) or (colour[3] == 0 and any(colour[:3])):
                fail('UNSUPPORTED_COLOUR', 'use opaque RGBA or transparent [0,0,0,0]', loc+'.options')
        if op == 'sprite':
            width, height = options['width'], options['height']
            layers.append(options['layer'])
        elif op == 'layer':
            if options['name'] in layers or len(layers) == 16:
                fail('INVALID_LAYER', 'use at most 16 uniquely named layers', loc)
            layers.append(options['name'])
        elif op == 'frame':
            frames += 1
        elif op == 'tag':
            if options['name'] in tags or not options['fromFrame'] <= options['toFrame'] <= frames:
                fail('INVALID_TAG', 'use unique tags with an existing ordered frame range', loc)
            tags.add(options['name'])
        elif op in ('pixel', 'rect', 'circle'):
            x, y = options['x'], options['y']
            radius = options.get('radius', 0)
            if (options['layer'] not in layers or options['frame'] > frames or
                x-radius < 0 or y-radius < 0 or
                x+options.get('width', radius+1) > width or y+options.get('height', radius+1) > height):
                fail('INVALID_DRAW', 'select an existing layer/frame and keep the entire shape inside the canvas', loc)
        if frames > 32 or width*height*frames*len(layers) > 262144 or width*frames > 8192:
            fail('RESOURCE_LIMIT', 'limit to 32 frames and 262144 layer/frame pixels', loc)
        prepared.append({'id': identity, 'filter': op, 'options': options, 'inputs': inputs})
        seen.add(identity)
    if document.get('output') != prepared[-1]['id']:
        fail('INVALID_SELECTION', 'output must select the final sprite node', '$.output')
    return {'version': 'schemaxis.aseprite.plan/1', 'nodes': prepared,
            'output': document['output'], 'expectedPublications': 4}


def options_schema(declaration):
    """Declared options refined by the parser's lossless RGBA contract."""
    from schemaxis.schema import option_schema
    result = option_schema(declaration)
    opts = result['properties']
    colour = {'anyOf': [{'const': [0, 0, 0, 0]}, {'type': 'array', 'minItems': 4, 'maxItems': 4,
        'prefixItems': [{'type': 'integer', 'minimum': 0, 'maximum': 255} for _ in range(3)] + [{'const': 255}], 'items': False}]}
    if 'colour' in opts: opts['colour'] = colour
    if 'colours' in opts: opts['colours']['items'] = colour
    return result


def schema():
    from schemaxis.schema import DRAFT, object_schema, argument_schema, NAME
    alternatives = []
    for op, decl in DECLARATIONS.items():
        options = options_schema(decl)
        required = [k for k, v in decl['options'].items() if v['value'].get('required')]
        alternatives.append(object_schema({'id': NAME,
            'filter': {'const': op}, 'options': options,
            'inputs': object_schema({k: {'type': 'string'} for k in decl['inputs']}, list(decl['inputs']))},
            ['id', 'filter'] + (['options'] if required else []) + (['inputs'] if decl['inputs'] else [])))
    return {'$schema': DRAFT, **object_schema({'version': {'const': 'schemaxis.aseprite/1'},
        'nodes': {'type': 'array', 'minItems': 1, 'maxItems': 256, 'items': {'oneOf': alternatives}},
        'output': NAME}, ['version', 'nodes', 'output'])}


def expected(prepared):
    """Independent integer raster oracle; never reads native-generated pixels."""
    first = prepared['nodes'][0]['options']
    w, h = first['width'], first['height']
    layers, durations, tags = [first['layer']], [first['durationMS']], {}
    colours = first['colours']
    cells = {(first['layer'], 1): bytearray(w*h*4)}
    for node in prepared['nodes'][1:]:
        op, o = node['filter'], node['options']
        if op == 'layer':
            layers.append(o['name'])
            for f in range(1, len(durations)+1): cells[o['name'], f] = bytearray(w*h*4)
        elif op == 'frame':
            durations.append(o['durationMS'])
            for layer in layers: cells[layer, len(durations)] = bytearray(w*h*4)
        elif op == 'palette': colours = o['colours']
        elif op == 'tag': tags[o['name']] = {k: o[k] for k in ('fromFrame', 'toFrame', 'direction')}
        else:
            pixels = cells[o['layer'], o['frame']]
            for y in range(h):
                for x in range(w):
                    inside = ((x-o['x'])**2+(y-o['y'])**2 <= o['radius']**2 if op == 'circle' else
                              o['x'] <= x < o['x']+o.get('width', 1) and o['y'] <= y < o['y']+o.get('height', 1))
                    if inside: pixels[(y*w+x)*4:(y*w+x+1)*4] = bytes(o['colour'])
    composites = []
    for f in range(1, len(durations)+1):
        raster = bytearray(w*h*4)
        for layer in layers:
            pixels = cells[layer, f]
            for i in range(0, len(pixels), 4):
                if pixels[i+3]: raster[i:i+4] = pixels[i:i+4]
        composites.append(raster)
    sheet = b''.join(bytes(r[y*w*4:(y+1)*w*4]) for y in range(h) for r in composites)
    tags = [dict(name=k, **v) for k, v in sorted(tags.items())]
    native = {'width': w, 'height': h, 'colourMode': 'RGB', 'layers': layers,
        'durationsMS': durations, 'palette': colours, 'tags': tags,
        'cels': [[cells[layer, f].hex() for f in range(1, len(durations)+1)] for layer in layers]}
    metadata = {'version': 'schemaxis.aseprite.sheet/1', 'width': w*len(durations), 'height': h,
        'frames': [{'x': i*w, 'y': 0, 'width': w, 'height': h, 'durationMS': d}
                   for i, d in enumerate(durations)], 'tags': tags}
    return native, {'width': w, 'height': h, 'pixels': composites[0].hex()}, {
        'width': w*len(durations), 'height': h, 'pixels': sheet.hex()}, metadata


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(document, directory, executable=None, timeout=60):
    prepared = plan(document)
    executable = executable or os.environ.get('ASEPRITE_EXE')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'provide an absolute executable Aseprite path', '$.executable')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        fail('INVALID_ARGUMENT', 'timeout must be greater than zero and at most 600 seconds', '$.timeout')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a fresh output directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    from .native_source import WORKER
    source = WORKER
    (directory/'worker.lua').write_text(source)
    try:
        for stage in ('build', 'reopen'):
            args = [str(executable), '--batch', '--script-param', 'stage='+stage, '--script', str(directory/'worker.lua')]
            # The shared runner owns a Python launcher, then exec replaces that
            # same PID with Aseprite. No shell, nested unmanaged process or
            # authored Lua source crosses this boundary.
            launcher = ('import os\n'
                        f'os.chdir({str(directory)!r})\n'
                        f'os.execv({str(executable)!r}, {args!r})\n')
            runner = SubprocessRunner(Interpreter('python', sys.executable), directory, timeout=timeout)
            stem = 'replay-' + hashlib.sha256(launcher.encode()).hexdigest()[:16]
            try:
                report = runner(launcher)
                atomic_json(directory/(stage+'-submission.json'), report.to_dict())
            finally:
                # Preserve convenient stage transcripts alongside the runner's
                # full stdout/stderr logs and cancellation/resource metrics.
                with (directory/(stage+'.log')).open('wb') as log:
                    for suffix in ('.stdout.log', '.stderr.log'):
                        path = directory/(stem+suffix)
                        if path.is_file():
                            log.write(path.read_bytes())
        if not (directory/'verification.json').is_file():
            fail('VERIFICATION_FAILED', 'native process produced no verification receipt')
        receipt = json.loads((directory/'verification.json').read_text())
        receipt['artifacts'] = artifact_manifest(directory)
        atomic_json(directory/'verification.json', receipt)
        result = verify(directory, require_result=False)
        result.update(status='succeeded', sha256={f: digest(directory/f) for f in (*FILES, 'verification.json', 'worker.lua')})
        atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False,
            'fault': error.fault.to_dict() if isinstance(error, SchemaxisError) else {'message': str(error)}})
        raise


def verify(directory, require_result=True):
    try:
        return _verify(directory, require_result)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        fail('VERIFICATION_FAILED', 'Missing or malformed sprite evidence: ' + str(error), str(directory))


def _verify(directory, require_result=True):
    directory = Path(directory).absolute()
    def read(filename):
        path = directory/filename
        if path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED', 'required regular evidence file is missing', filename)
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                fail('VERIFICATION_FAILED', 'expected an evidence object', filename)
            return value
        except (ValueError, OSError): fail('VERIFICATION_FAILED', 'invalid JSON evidence', filename)
    prepared = plan(read('authored.json'))
    if read('plan.json') != prepared:
        fail('VERIFICATION_FAILED', 'plan differs from authored input')
    result = read('result.json')
    if require_result and (result.get('verified') is not True or result.get('status') != 'succeeded'):
        fail('INCOMPLETE_EXECUTION', 'native execution did not complete')
    receipt = read('verification.json')
    if receipt.get('freshProcess') is not True or not isinstance(receipt.get('runtime'), str):
        fail('VERIFICATION_FAILED', 'missing fresh-process runtime evidence')
    if receipt.get('artifacts') != artifact_manifest(directory):
        fail('VERIFICATION_FAILED', 'publication manifest differs')
    native, preview, sheet, metadata = expected(prepared)
    for key, value in (('native', native), ('preview', preview), ('sheet', sheet)):
        if receipt.get(key) != value:
            fail('VERIFICATION_FAILED', 'native readback differs from independent raster model', key)
    if read('sheet.json') != metadata:
        fail('VERIFICATION_FAILED', 'spritesheet metadata differs')
    for filename in (*FILES, 'verification.json', 'worker.lua'):
        path = directory/filename
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            fail('VERIFICATION_FAILED', 'missing regular artifact', filename)
        if require_result and digest(path) != result.get('sha256', {}).get(filename):
            fail('VERIFICATION_FAILED', 'artifact digest differs', filename)
    return {'verified': True, 'artifacts': 4, 'runtime': receipt['runtime'],
            'frames': len(native['durationsMS']), 'layers': len(native['layers']),
            'width': native['width'], 'height': native['height']}


def artifact_manifest(directory):
    return [{'file': str(directory/filename), 'kind': kind, 'sha256': digest(directory/filename)}
            for filename, kind in [('sprite.aseprite', 'sprite'), ('preview.png', 'image'),
                                   ('sheet.png', 'spriteSheet'), ('sheet.json', 'spriteMetadata')]]


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
