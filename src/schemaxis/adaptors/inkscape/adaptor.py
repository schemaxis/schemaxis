# Copyright (C) 2026 David L F Gaden
"""Bounded technical block diagrams; authored input never contains SVG or commands."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import xml.etree.ElementTree as ET

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from schemaxis.png import decode, MAX_BYTES

VERSION = 'schemaxis.inkscape/1'
PX_MM = 96 / 25.4
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}
MM = {'type': 'number', 'minimum': 0, 'maximum': 1000, 'required': True}
OPTIONS = {
    'width': {**MM, 'minimum': 20, 'maximum': 500},
    'height': {**MM, 'minimum': 20, 'maximum': 500},
    'margin': {**MM, 'minimum': 1, 'maximum': 50, 'required': False, 'default': 5},
    'clearance': {**MM, 'minimum': 1, 'maximum': 50, 'required': False, 'default': 5},
    'padding': {**MM, 'minimum': 1, 'maximum': 20, 'required': False, 'default': 2},
    'fontSize': {**MM, 'minimum': 1, 'maximum': 10, 'required': False, 'default': 3},
    'dpi': {'type': 'integer', 'minimum': 72, 'maximum': 192, 'default': 96},
    'boxes': {'type': 'array', 'minItems': 1, 'maxItems': 32, 'required': True,
              'items': {'type': 'object', 'properties': {
                  'id': NAME, 'label': {'type': 'string', 'minLength': 1, 'maxLength': 80, 'required': True},
                  'x': MM, 'y': MM, 'width': {**MM, 'minimum': 5}, 'height': {**MM, 'minimum': 5},
                  'colour': {'type': 'enum', 'values': ['blue', 'green', 'amber'], 'default': 'blue'}}}},
    'links': {'type': 'array', 'maxItems': 48, 'default': [], 'items': {'type': 'object', 'properties': {
        'id': NAME, 'source': NAME, 'target': NAME}}},
}
FLOW_OPTIONS = {**OPTIONS,
    'boxes': {**OPTIONS['boxes'], 'items': {'type': 'object', 'properties': {
        key: value for key, value in OPTIONS['boxes']['items']['properties'].items() if key in ('id', 'label', 'colour')}}},
    'boxWidth': {**MM, 'minimum': 5, 'maximum': 100, 'required': False, 'default': 26},
    'boxHeight': {**MM, 'minimum': 5, 'maximum': 100, 'required': False, 'default': 14},
    'rankGap': {**MM, 'minimum': 3, 'maximum': 100, 'required': False, 'default': 15},
    'laneGap': {**MM, 'minimum': 1, 'maximum': 100, 'required': False, 'default': 8},
}
DECLARATIONS = {'blockDiagram': {'native': 'Inkscape SVG/query/export', 'kinds': ['image', 'text'],
    'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}},
    'flowDiagram': {'native': 'Inkscape DAG layout/query/export', 'kinds': ['image', 'text'],
                    'inputs': {}, 'options': {k: {'value': v} for k, v in FLOW_OPTIONS.items()}}}
COLOURS = {'blue': '#dbeafe', 'green': '#dcfce7', 'amber': '#fef3c7'}
LOSSES = ['PNG is flattened and loses editable geometry and text; retain diagram.svg.',
          'SVG is adaptor-generated editable geometry, not general imported-SVG compatibility.',
          'Text uses the native sans-serif font; exact typography depends on installed fonts.']


def fault(code, message, location='$', **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed,
        recovery={'INVALID_LAYOUT': 'Move or resize boxes; keep page margins and declared clearance; route links left-to-right without crossing unrelated boxes.',
                  'FLOW_CYCLE': 'Remove or reverse the named cyclic dependencies; flowDiagram requires a DAG.',
                  'FLOW_PAGE_OVERFLOW': 'Increase page width/height or reduce card size/gaps within clearance limits; inspect requiredPage and ranks before retrying.',
                  'FLOW_ROUTING_COLLISION': 'Change the dependency structure or use blockDiagram to place cards explicitly; the bounded deterministic router cannot safely route this graph.',
                  'LABEL_OVERFLOW': 'Widen or heighten the named box, shorten its label, or lower fontSize; rerun to measure the actual native font.',
                  'VERIFICATION_FAILED': 'Preserve the failed evidence and run the original authored document in a fresh directory.'}.get(code, 'Correct the located input or select a usable absolute Inkscape executable; retry in a fresh directory.')))


def _block_plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') != 'blockDiagram': fail('UNKNOWN_FILTER', 'select blockDiagram')
    options = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k not in ('version', 'operation')})
    seen = set(); boxes = {}
    for i, box in enumerate(options['boxes']):
        location = f'$.boxes[{i}]'
        identity = box['id']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', identity) or identity in seen:
            fault('INVALID_LAYOUT', 'box and link IDs must be unique simple names', location + '.id')
        if any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff or ord(c) in (0xfffe, 0xffff) for c in box['label']):
            fault('INVALID_LAYOUT', 'labels must be single-line XML 1.0 text without control or forbidden characters', location + '.label')
        seen.add(identity); boxes[identity] = box
        m = options['margin']; x, y, w, h = (box[k] for k in ('x', 'y', 'width', 'height'))
        if x - .2 + 1e-10 < m or y - .2 + 1e-10 < m or x + w + .2 > options['width'] - m + 1e-10 or y + h + .2 > options['height'] - m + 1e-10:
            fault('INVALID_LAYOUT', 'box stroke violates declared page margin', location)
        if min(w, h) <= 2 * options['padding']:
            fault('INVALID_LAYOUT', 'box needs room for padding on both sides', location)
    # A 1e-10 mm arithmetic epsilon only absorbs binary float roundoff at
    # exact geometric budgets; native readback still has its own 0.015 mm bound.
    all_boxes = list(boxes.values()); minimum = None
    for i, a in enumerate(all_boxes):
        for b in all_boxes[i + 1:]:
            dx = max(a['x'] - b['x'] - b['width'], b['x'] - a['x'] - a['width'], 0)
            dy = max(a['y'] - b['y'] - b['height'], b['y'] - a['y'] - a['height'], 0)
            gap = math.hypot(dx, dy) - .4
            minimum = gap if minimum is None else min(minimum, gap)
            if gap + 1e-10 < options['clearance']:
                fault('INVALID_LAYOUT', 'box strokes violate minimum clearance', '$.boxes', boxes=[a['id'], b['id']], measured=gap)
    routes = []
    for i, link in enumerate(options['links']):
        location = f'$.links[{i}]'; identity = link['id']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', identity) or identity in seen:
            fault('INVALID_LAYOUT', 'box and link IDs must be unique simple names', location + '.id')
        seen.add(identity)
        if link['source'] not in boxes or link['target'] not in boxes or link['source'] == link['target']:
            fault('INVALID_LAYOUT', 'link needs two distinct declared boxes', location)
        a, b = boxes[link['source']], boxes[link['target']]
        x1, y1 = a['x'] + a['width'] + .2, a['y'] + a['height'] / 2
        x2, y2 = b['x'] - .2, b['y'] + b['height'] / 2
        if x2 - x1 + 1e-10 < max(options['clearance'], 3):
            fault('INVALID_LAYOUT', 'links require left-to-right clearance for a 2 mm arrow', location)
        mid = (x1 + x2) / 2
        segments = [[x1, y1, mid, y1], [mid, y1, mid, y2], [mid, y2, x2, y2]]
        for box in all_boxes:
            if box['id'] in (a['id'], b['id']): continue
            for xa, ya, xb, yb in segments:
                if (max(xa, xb) >= box['x'] - .4 and min(xa, xb) <= box['x'] + box['width'] + .4
                    and max(ya, yb) >= box['y'] - .4 and min(ya, yb) <= box['y'] + box['height'] + .4):
                    fault('INVALID_LAYOUT', 'connector crosses an unrelated box', location, box=box['id'])
        # The filled arrow is wider than the connector stroke; its envelope
        # must also avoid unrelated boxes, including at diagonal approaches.
        for box in all_boxes:
            if box['id'] in (a['id'], b['id']): continue
            if (x2 >= box['x'] - .2 and x2 - 2 <= box['x'] + box['width'] + .2
                and y2 + 1 >= box['y'] - .2 and y2 - 1 <= box['y'] + box['height'] + .2):
                fault('INVALID_LAYOUT', 'connector arrow crosses an unrelated box', location, box=box['id'])
        routes.append({'id': identity, 'points': [[x1, y1], [mid, y1], [mid, y2], [x2, y2]]})
    if options['width'] * options['dpi'] / 25.4 > 4096 or options['height'] * options['dpi'] / 25.4 > 4096:
        fault('RESOURCE_LIMIT', 'PNG dimensions exceed 4096 pixels; reduce page size or dpi')
    return {'version': 'schemaxis.inkscape.plan/1', 'operation': 'blockDiagram', **options,
            'routes': routes, 'minimumClearance': minimum, 'losses': LOSSES}


def plan(document):
    if not isinstance(document, dict): keys(document, (), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') == 'blockDiagram': return _block_plan(document)
    if document.get('operation') != 'flowDiagram': fail('UNKNOWN_FILTER', 'select blockDiagram or flowDiagram')
    keys(document, ('version', 'operation', *FLOW_OPTIONS), '$')
    options = validate_arguments(FLOW_OPTIONS, {k: v for k, v in document.items() if k not in ('version', 'operation')})
    from .layout import arrange
    return arrange(options, _block_plan, fault)


def schema():
    from schemaxis.schema import DRAFT, object_schema, argument_schema
    variants = [object_schema({'version': {'const': VERSION}, 'operation': {'const': operation},
        **{k: argument_schema(v) for k, v in options.items()}}, ['version', 'operation', 'width', 'height', 'boxes'])
        for operation, options in (('blockDiagram', OPTIONS), ('flowDiagram', FLOW_OPTIONS))]
    fields = {}
    for variant in variants:
        for key, value in variant['properties'].items():
            if value not in fields.setdefault(key, []): fields[key].append(value)
    properties = {key: values[0] if len(values) == 1 else {'anyOf': values} for key, values in fields.items()}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation', 'width', 'height', 'boxes']), 'oneOf': variants}


def query(document):
    prepared = plan(document)
    plans = [visit['plan'] for visit in prepared['visits']] if prepared.get('version') == 'schemaxis.study.plan/1' else [prepared]
    return sorted({visit['operation'] for visit in plans}), {}


def reusableInputs(document):
    plan(document); return {}


def resources(document, spec, identity):
    if spec.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'diagram export reserves one host thread', identity)
    return {'threads': 1}


def svg(prepared):
    # A small closed SVG vocabulary. XML escaping is provided by ElementTree.
    root = ET.Element('svg', {'xmlns': 'http://www.w3.org/2000/svg', 'width': f"{prepared['width']}mm",
        'height': f"{prepared['height']}mm", 'viewBox': f"0 0 {prepared['width']} {prepared['height']}"})
    for box in prepared['boxes']:
        identity = box['id']
        ET.SubElement(root, 'rect', {'id': 'box_' + identity, **{k: str(box[k]) for k in ('x', 'y', 'width', 'height')},
            'fill': COLOURS[box['colour']], 'stroke': '#334155', 'stroke-width': '0.4'})
        text = ET.SubElement(root, 'text', {'id': 'label_' + identity, 'x': str(box['x'] + prepared['padding']),
            'y': str(box['y'] + box['height'] / 2 + prepared['fontSize'] * .35),
            'font-family': 'sans-serif', 'font-size': str(prepared['fontSize']), 'fill': '#0f172a'})
        text.text = box['label']
    for route in prepared['routes']:
        points = route['points']; x2, y2 = points[-1]
        ET.SubElement(root, 'path', {'id': 'link_' + route['id'], 'd': 'M ' + ' L '.join(f'{x} {y}' for x, y in points),
            'fill': 'none', 'stroke': '#334155', 'stroke-width': '0.4', 'stroke-linejoin': 'round', 'stroke-linecap': 'butt'})
        ET.SubElement(root, 'polygon', {'id': 'arrow_' + route['id'],
            'points': f'{x2},{y2} {x2-2},{y2-1} {x2-2},{y2+1}', 'fill': '#334155'})
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def bounds(prepared, output):
    # query-all reports CSS pixels at 96 dpi, independently of PNG export
    # DPI. The generated viewBox maps one SVG user unit to one mm.
    measurements = {}
    for line in output.splitlines():
        parts = line.split(',')
        if len(parts) != 5: fault('VERIFICATION_FAILED', 'native query contains a malformed row')
        identity = parts[0]
        try: values = [float(v) / PX_MM for v in parts[1:]]
        except ValueError: fault('VERIFICATION_FAILED', 'native bounds are not numbers')
        if identity in measurements or not all(math.isfinite(v) for v in values) or min(values[2:]) < 0:
            fault('VERIFICATION_FAILED', 'native bounds are duplicated or invalid')
        measurements[identity] = values
    labels = {}; padding = prepared['padding']
    def required(identity):
        if identity not in measurements: fault('VERIFICATION_FAILED', 'native object is absent', identity)
        return measurements[identity]
    def compare(identity, expected):
        actual = required(identity)
        if any(abs(a - b) > .015 for a, b in zip(actual, expected)):
            fault('VERIFICATION_FAILED', 'native geometry differs from declared geometry', identity, expected=expected, actual=actual)
    for box in prepared['boxes']:
        identity = box['id']
        compare('box_' + identity, [box['x'] - .2, box['y'] - .2, box['width'] + .4, box['height'] + .4])
        x, y, w, h = required('label_' + identity)
        if w <= 0 or h <= 0 or x < box['x'] + padding - .015 or y < box['y'] + padding - .015 or x + w > box['x'] + box['width'] - padding + .015 or y + h > box['y'] + box['height'] - padding + .015:
            fault('LABEL_OVERFLOW', 'actual native text violates declared label padding', '$.boxes', box=identity, bounds=[x, y, w, h], padding=padding)
        labels[identity] = {'bounds': [x, y, w, h], 'rightSlack': box['x'] + box['width'] - padding - x - w}
    for route in prepared['routes']:
        points = route['points']; xs, ys = zip(*points); x2, y2 = points[-1]
        # Butt caps do not enlarge the x bounds; round joins bound y by half-stroke.
        compare('link_' + route['id'], [min(xs), min(ys) - .2, max(xs) - min(xs), max(ys) - min(ys) + .4])
        compare('arrow_' + route['id'], [x2 - 2, y2 - 1, 2, 2])
    return {**({'layout': prepared['layout']} if prepared['operation'] == 'flowDiagram' else {}),
            'objects': measurements, 'labels': labels, 'boxCount': len(prepared['boxes']),
            'linkCount': len(prepared['routes']), 'minimumClearance': prepared['minimumClearance']}


def raster(prepared, data):
    w, h, pixels = decode(data)
    expected = [round(prepared[k] * prepared['dpi'] / 25.4) for k in ('width', 'height')]
    if [w, h] != expected: fault('VERIFICATION_FAILED', 'PNG page dimensions differ', expected=expected, actual=[w, h])
    checks = [(0, 0, '#ffffff'), (w - 1, h - 1, '#ffffff')]
    scale = prepared['dpi'] / 25.4
    for box in prepared['boxes']:
        checks.append((round((box['x'] + prepared['padding'] / 2) * scale),
                       round((box['y'] + prepared['padding'] / 2) * scale), COLOURS[box['colour']]))
    probes = []
    for x, y, colour in checks:
        observed = list(pixels[(y * w + x) * 4:(y * w + x) * 4 + 4])
        expected_colour = [int(colour[i:i+2], 16) for i in (1, 3, 5)] + [255]
        if observed != expected_colour: fault('VERIFICATION_FAILED', 'rendered page or box colour probe differs', actual=observed, expected=expected_colour, pixel=[x, y])
        probes.append({'pixel': [x, y], 'rgba': observed})
    return {'width': w, 'height': h, 'probes': probes}


def receipt(directory, prepared):
    if (directory / 'diagram.svg').read_bytes() != svg(prepared):
        fault('VERIFICATION_FAILED', 'editable SVG semantics differ from authored diagram')
    native = bounds(prepared, (directory / 'query.stdout').read_text())
    image = directory / 'diagram.png'
    if image.stat().st_size > MAX_BYTES: fault('VERIFICATION_FAILED', 'PNG byte budget exceeded')
    preview = raster(prepared, image.read_bytes())
    runtime = (directory / 'version.stdout').read_text().strip()
    if not re.fullmatch(r'Inkscape 1\.4\.\d+[^\n]*', runtime):
        fault('UNSUPPORTED_RUNTIME', 'this route targets stable Inkscape 1.4.x', observed=runtime)
    return {'artifacts': [{'file': str(directory / name), 'kind': kind, 'sha256': file_digest(directory / name)}
                          for name, kind in [('diagram.svg', 'text'), ('diagram.png', 'image'), ('diagram-measurements.json', 'text')]],
            'native': native, 'preview': preview, 'runtime': runtime, 'losses': LOSSES}


def stage_arguments(prepared, directory, stage):
    if stage == 'version': return ['--version']
    if stage == 'query': return [str(directory/'diagram.svg'), '--query-all']
    if stage == 'export': return [str(directory/'diagram.svg'), '--export-type=png', '--export-area-page',
        '--export-background=#ffffff', '--export-background-opacity=1', '--export-png-color-mode=RGBA_8',
        '--export-dpi=' + str(prepared['dpi']), '--export-filename=' + str(directory/'diagram.png')]
    raise ValueError('unknown trusted native stage')


def instance_tag(directory, stage):
    # Valid D-Bus application-ID component, unique across fresh run directories
    # and stages; deterministic so independent verification can replay it.
    return 'schemaxis_' + hashlib.sha256(str(directory).encode()).hexdigest()[:24] + '_' + stage


def native_visit(executable, prepared, directory, stage, timeout):
    tag = instance_tag(directory, stage)
    profile = directory/'.native-profiles'/stage
    profile.mkdir(parents=True, exist_ok=False)
    command = [executable, '--app-id-tag=' + tag, *stage_arguments(prepared, directory, stage)]
    # Inkscape1.4.4's constructor probes the default D-Bus application before
    # CLI processing. Its public upstream environment tag avoids that probe;
    # the CLI tag then preserves the same identity during option handling.
    execute(command, directory, stage, timeout,
            environment={'INKSCAPE_APP_ID_TAG': tag, 'INKSCAPE_PROFILE_DIR': str(profile)})


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('INKSCAPE_EXECUTABLE') or shutil.which('inkscape')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fault('INTERPRETER_NOT_FOUND', 'provide an absolute usable Inkscape executable')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'choose a fresh directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory / 'authored.json', document); atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    deadline = time.monotonic() + timeout
    try:
        (directory / 'diagram.svg').write_bytes(svg(prepared))
        native_visit(executable, prepared, directory, 'version', deadline - time.monotonic())
        # Open the durable SVG in independent native visits for query and export.
        native_visit(executable, prepared, directory, 'query', deadline - time.monotonic())
        if 'Unrecognized unit' in (directory / 'query.stderr').read_text() or 'Units file' in (directory / 'query.stderr').read_text():
            fault('UNSUPPORTED_RUNTIME', 'native installation cannot resolve mm units; repair its data directory before retrying')
        native = bounds(prepared, (directory / 'query.stdout').read_text())
        native_visit(executable, prepared, directory, 'export', deadline - time.monotonic())
        atomic_json(directory / 'diagram-measurements.json', {'version': 'schemaxis.inkscape.measurements/1', 'units': 'mm', **native})
        atomic_json(directory / 'verification.json', receipt(directory, prepared))
        verify(directory, require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'diagram export cancelled')
        result = {'status': 'succeeded', 'verified': True, 'artifacts': 3}
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            error = SchemaxisError(Fault('NATIVE_EXECUTION_FAILED', str(error), str(directory), 'execution'))
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        names = ['authored.json', 'plan.json', 'verification.json', 'result.json', 'diagram.svg', 'diagram.png',
                 'diagram-measurements.json', 'query.stdout', 'version.stdout',
                 'version-submission.json', 'query-submission.json', 'export-submission.json']
        for name in names:
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                fault('VERIFICATION_FAILED', 'required bounded regular evidence file absent', name)
        def read(name): return json.loads((directory / name).read_text())
        result = read('result.json')
        if require_result and (result.get('status') != 'succeeded' or result.get('verified') is not True):
            fail('INCOMPLETE_EXECUTION', 'diagram did not complete')
        prepared = plan(read('authored.json'))
        if read('plan.json') != prepared: fault('VERIFICATION_FAILED', 'saved plan differs from authored input')
        expected = receipt(directory, prepared)
        version_command = read('version-submission.json').get('nativeCommand')
        if not isinstance(version_command, list) or not version_command or not isinstance(version_command[0], str):
            fault('VERIFICATION_FAILED', 'missing native executable command identity')
        executable = version_command[0]
        if not Path(executable).is_absolute(): fault('VERIFICATION_FAILED', 'native executable identity is not absolute')
        for stage in ('version', 'query', 'export'):
            command = [executable, '--app-id-tag=' + instance_tag(directory, stage), *stage_arguments(prepared, directory, stage)]
            if read(stage + '-submission.json').get('nativeCommand') != command:
                fault('VERIFICATION_FAILED', 'native stage command differs from trusted isolated diagram recipe', stage)
        if read('diagram-measurements.json') != {'version': 'schemaxis.inkscape.measurements/1', 'units': 'mm', **expected['native']}:
            fault('VERIFICATION_FAILED', 'published measurements differ from independently checked native bounds')
        if read('verification.json') != expected: fault('VERIFICATION_FAILED', 'saved native/publication evidence differs')
        return {'verified': True, 'artifacts': 3, 'runtime': expected['runtime'], 'native': expected['native'], 'preview': expected['preview']}
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        fault('VERIFICATION_FAILED', 'missing or invalid diagram evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
