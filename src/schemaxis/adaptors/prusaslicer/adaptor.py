"""Slice one declared STL with an explicit FFF printer/material/print profile.

The host renders a complete fixed-policy configuration, runs the PrusaSlicer
console in isolated processes, and independently replays the published G-code.
No authored G-code, scripts, preset names, native options or printer control.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from schemaxis.tabular import parse_csv, write_csv
from . import gcode, profile, stl
from .faults import fault

VERSION = 'schemaxis.prusaslicer/1'
RUNTIME = '2.9.6'
INCH = 25.4
NUMBER = {'type': 'number', 'required': True}
PAIR = {'type': 'array', 'minItems': 2, 'maxItems': 2, 'required': True}
OPTIONS = {
    'model': {'type': 'object', 'required': True, 'properties': {
        'file': {'type': 'string', 'minLength': 2, 'maxLength': 4096, 'required': True},
        'units': {'type': 'enum', 'values': ['millimetre', 'inch'], 'required': True},
        'sha256': {'type': 'string', 'minLength': 64, 'maxLength': 64}}},
    'printer': {'type': 'object', 'required': True, 'properties': {
        'bedSize_mm': {**PAIR, 'items': {'type': 'number', 'minimum': 50, 'maximum': 1000}},
        'maxPrintHeight_mm': {**NUMBER, 'minimum': 10, 'maximum': 1000},
        'nozzleDiameter_mm': {**NUMBER, 'minimum': 0.15, 'maximum': 1.2},
        'gcodeFlavour': {'type': 'enum', 'values': ['marlin2'], 'required': True},
        'maxFeedrate_mm_s': {**NUMBER, 'minimum': 20, 'maximum': 1000},
        'maxAcceleration_mm_s2': {**NUMBER, 'minimum': 100, 'maximum': 30000}}},
    'material': {'type': 'object', 'required': True, 'properties': {
        'type': {'type': 'enum', 'values': ['PLA', 'PETG', 'ABS', 'ASA'], 'required': True},
        'filamentDiameter_mm': {**NUMBER, 'minimum': 1.0, 'maximum': 3.5},
        'density_g_cm3': {**NUMBER, 'minimum': 0.5, 'maximum': 3.0},
        'nozzleTemperature_C': {**NUMBER, 'minimum': 150, 'maximum': 320},
        'firstLayerNozzleTemperature_C': {**NUMBER, 'minimum': 150, 'maximum': 320},
        'bedTemperature_C': {**NUMBER, 'minimum': 0, 'maximum': 130},
        'firstLayerBedTemperature_C': {**NUMBER, 'minimum': 0, 'maximum': 130},
        'fanSpeed_percent': {**NUMBER, 'minimum': 0, 'maximum': 100}}},
    'print': {'type': 'object', 'required': True, 'properties': {
        'layerHeight_mm': {**NUMBER, 'minimum': 0.04, 'maximum': 1.0},
        'firstLayerHeight_mm': {**NUMBER, 'minimum': 0.04, 'maximum': 1.0},
        'extrusionWidth_mm': {**NUMBER, 'minimum': 0.15, 'maximum': 2.4},
        'perimeters': {'type': 'integer', 'minimum': 1, 'maximum': 10, 'required': True},
        'topSolidLayers': {'type': 'integer', 'minimum': 0, 'maximum': 30, 'required': True},
        'bottomSolidLayers': {'type': 'integer', 'minimum': 0, 'maximum': 30, 'required': True},
        'infillDensity_percent': {**NUMBER, 'minimum': 0, 'maximum': 100},
        'infillPattern': {'type': 'enum', 'values': ['rectilinear', 'grid', 'gyroid'], 'required': True},
        'perimeterSpeed_mm_s': {**NUMBER, 'minimum': 5, 'maximum': 500},
        'infillSpeed_mm_s': {**NUMBER, 'minimum': 5, 'maximum': 500},
        'firstLayerSpeed_mm_s': {**NUMBER, 'minimum': 5, 'maximum': 200},
        'travelSpeed_mm_s': {**NUMBER, 'minimum': 10, 'maximum': 1000}}},
    'placement': {'type': 'object', 'default': {}, 'properties': {
        'centre_mm': {'type': 'array', 'minItems': 2, 'maxItems': 2,
                      'items': {'type': 'number', 'minimum': 0, 'maximum': 1000}}}},
    'requirements': {'type': 'array', 'maxItems': 8, 'default': [], 'items': {'type': 'object', 'properties': {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 64, 'required': True},
        'quantity': {'type': 'enum', 'values': ['printTime_s', 'filamentMass_g', 'filamentLength_mm'], 'required': True},
        'maximum': {**NUMBER, 'minimum': 0, 'maximum': 1e9}}}},
}
DECLARATIONS = {'sliceModel': {'native': 'PrusaSlicer console --export-gcode', 'inputs': {}, 'kinds': ['text', 'table'],
    'options': {key: {'value': value} for key, value in OPTIONS.items()}}}
FILES = [('model.gcode', 'text'), ('layers.csv', 'table'), ('slice-summary.json', 'text'), ('config.ini', 'text')]
STAGES = ('version', 'info', 'slice', 'reopen')
MAX_EVIDENCE = 64*1024*1024
HEADER = ['layer', 'z_mm', 'moves', 'path_mm', 'filament_mm', 'xMin_mm', 'xMax_mm', 'yMin_mm', 'yMax_mm',
          'maxFeed_mm_s', 'nozzle_C', 'bed_C', 'fan_percent']
# Tolerances are justified in docs/prusaslicer.md#independent-checks.
COORDINATE = 0.011   # G-code coordinates are printed with three decimals; clipper rounding is far smaller.
FEED = 0.01          # mm/s; feedrates are printed in mm/min.
LOSSES = [
    'Generated G-code targets a generic Marlin 2 FFF machine described only by the declared bed, height, nozzle, feedrate and acceleration; it has not been sent to, executed on or validated for any physical printer, firmware or material.',
    'No physical print quality, adhesion, strength, dimensional accuracy or thermal/fire safety is certified; temperatures, speeds and fan values are authored setpoints whose application is checked, not their suitability.',
    'Print time and filament figures are PrusaSlicer model estimates under the declared machine limits; the adaptor checks kinematic bounds and filament arithmetic only.',
    'One closed, consistently oriented STL object in millimetres or inches; no mesh repair, rotation, arrangement, supports, brim, skirt, raft, multi-material, modifiers, variable layer height, arcs or binary G-code.',
]
DRIVER = ("import hashlib,json,os,stat,sys\nspec=json.loads(sys.argv[1])\n"
          "for name,digest in spec['files']:\n fd=os.open(name,os.O_RDONLY|getattr(os,'O_NONBLOCK',0))\n"
          " with os.fdopen(fd,'rb') as f:\n  info=os.fstat(f.fileno())\n"
          "  if not stat.S_ISREG(info.st_mode) or info.st_size>67108864: raise SystemExit('invalid bounded input '+name)\n"
          "  data=f.read(67108865)\n"
          " if hashlib.sha256(data).hexdigest()!=digest: raise SystemExit('input differs from trusted binding '+name)\n"
          "command=spec['command']\nos.execv(command[0],command)\n")


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') != 'sliceModel':
        fail('UNKNOWN_FILTER', 'select sliceModel')
    options = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k not in ('version', 'operation')})
    model, printer, material, settings = (options[k] for k in ('model', 'printer', 'material', 'print'))
    path = model['file']
    if any(ord(char) < 32 for char in path) or not Path(path).is_absolute() or not path.lower().endswith('.stl'):
        fault('INVALID_RESOURCE', 'model.file must be an absolute path to a .stl file', '$.model.file', file=path)
    if 'sha256' in model and not re.fullmatch('[0-9a-f]{64}', model['sha256']):
        fault('INVALID_RESOURCE', 'model.sha256 must be 64 lowercase hexadecimal digits', '$.model.sha256')
    nozzle = printer['nozzleDiameter_mm']
    for key in ('layerHeight_mm', 'firstLayerHeight_mm'):
        if settings[key] > 0.8*nozzle:
            fault('INVALID_PROFILE', 'layer heights must not exceed 0.8 x nozzle diameter', '$.print.' + key,
                  observed=settings[key], maximum=0.8*nozzle)
    width = settings['extrusionWidth_mm']
    if not nozzle <= width <= 2*nozzle:
        fault('INVALID_PROFILE', 'extrusion width must be between 1 and 2 nozzle diameters', '$.print.extrusionWidth_mm',
              observed=width, minimum=nozzle, maximum=2*nozzle)
    if width <= max(settings['layerHeight_mm'], settings['firstLayerHeight_mm']):
        fault('INVALID_PROFILE', 'extrusion width must exceed every layer height', '$.print.extrusionWidth_mm')
    if settings['infillDensity_percent'] == 100 and settings['infillPattern'] != 'rectilinear':
        fault('INVALID_PROFILE', '100% sparse infill is supported only with the rectilinear pattern', '$.print.infillPattern')
    bed = printer['bedSize_mm']
    centre = options['placement'].get('centre_mm', [bed[0]/2, bed[1]/2])
    if not (0 < centre[0] < bed[0] and 0 < centre[1] < bed[1]):
        fault('MODEL_OUT_OF_BOUNDS', 'placement centre must lie inside the declared bed', '$.placement.centre_mm', centre=centre, bed=bed)
    names = set()
    for index, entry in enumerate(options['requirements']):
        if not re.fullmatch('[a-z][a-z0-9_]{0,63}', entry['name']) or entry['name'] in names:
            fault('INVALID_REQUIREMENT', 'use unique lowercase requirement names', f'$.requirements[{index}].name')
        names.add(entry['name'])
    prepared = {'version': 'schemaxis.prusaslicer.plan/1', 'operation': 'sliceModel', 'model': model,
                'scale': INCH if model['units'] == 'inch' else 1, 'printer': printer, 'material': material,
                'print': settings, 'placement': {'centre_mm': centre}, 'requirements': options['requirements'],
                'limits': {'x': printer['maxFeedrate_mm_s'], 'y': printer['maxFeedrate_mm_s'], 'z': profile.Z_FEEDRATE,
                           'e': profile.E_FEEDRATE, 'acceleration': printer['maxAcceleration_mm_s2']},
                'runtime': 'PrusaSlicer ' + RUNTIME, 'losses': LOSSES}
    prepared['config'] = [list(entry) for entry in profile.entries(prepared)]
    return prepared


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    fields = {'version': {'const': VERSION}, 'operation': {'const': 'sliceModel'},
              **{key: argument_schema(value) for key, value in OPTIONS.items()}}
    fields['model']['properties']['sha256']['pattern'] = '^[0-9a-f]{64}$'
    fields['model']['properties']['file']['pattern'] = '^/[^\\u0000-\\u001f]*\\.[sS][tT][lL]$'
    fields['requirements']['items']['properties']['name']['pattern'] = '^[a-z][a-z0-9_]{0,63}$'
    return {'$schema': DRAFT, **object_schema(fields, ['version', 'operation', 'model', 'printer', 'material', 'print'])}


def query(document):
    prepared = plan(document)
    return list(dict.fromkeys(v['plan']['operation'] for v in prepared['visits'])) if 'visits' in prepared else [prepared['operation']], {}


def source(path, location='$.model.file'):
    try:
        if Path(path).is_symlink():
            fault('INVALID_RESOURCE', 'model.file must be a regular file, not a symbolic link', location, file=path)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    except OSError as error:
        fault('INVALID_RESOURCE', 'cannot open model.file: ' + error.strerror, location, file=path)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > stl.MAX_BYTES:
            fault('INVALID_RESOURCE', 'model.file must be a regular file within 16 MiB', location, file=path)
        data = stream.read(stl.MAX_BYTES + 1)
    if len(data) > stl.MAX_BYTES:
        fault('INVALID_RESOURCE', 'model.file exceeds 16 MiB', location, file=path)
    return data


def reusableInputs(document):
    prepared = plan(document)
    data = source(prepared['model']['file'])
    digest = hashlib.sha256(data).hexdigest()
    declared = prepared['model'].get('sha256')
    if declared and declared != digest:
        fault('INPUT_DIGEST_MISMATCH', 'model bytes differ from the declared sha256', '$.model.sha256', declared=declared, observed=digest)
    return {prepared['model']['file']: digest}


def resources(document, spec, identity):
    if spec.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'bounded slicing uses exactly one native thread', identity)
    return {'threads': 1}


def bounded(path, limit=MAX_EVIDENCE):
    path = Path(path)
    if path.is_symlink():
        fault('VERIFICATION_FAILED', 'evidence must be a bounded regular file', str(path))
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            fault('VERIFICATION_FAILED', 'evidence must be a bounded regular file', str(path))
        data = stream.read(limit + 1)
    if len(data) > limit:
        fault('VERIFICATION_FAILED', 'evidence exceeds byte budget', str(path))
    return data


def read_json(path):
    return json.loads(bounded(path))


def analyse_model(prepared, data):
    def problem(message, **observed):
        fault('INVALID_MODEL', message, '$.model.file', **observed)
    mesh = stl.read(data, problem)
    scale = prepared['scale']
    size = [value*scale for value in mesh['size']]
    result = {**mesh, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'units': prepared['model']['units'],
              'scale': scale, 'size_mm': size, 'volume_mm3': mesh['volume']*scale**3}
    declared = prepared['model'].get('sha256')
    if declared and declared != result['sha256']:
        fault('INPUT_DIGEST_MISMATCH', 'model bytes differ from the declared sha256', '$.model.sha256',
              declared=declared, observed=result['sha256'])
    printer, settings = prepared['printer'], prepared['print']
    centre = prepared['placement']['centre_mm']
    bed = printer['bedSize_mm']
    for axis, name in ((0, 'x'), (1, 'y')):
        low, high = centre[axis] - size[axis]/2, centre[axis] + size[axis]/2
        if low < 0 or high > bed[axis]:
            fault('MODEL_OUT_OF_BOUNDS', 'model footprint does not fit the declared bed around the placement centre',
                  '$.placement.centre_mm', axis=name, extent=[low, high], bed=bed[axis])
        if size[axis] < 2*settings['extrusionWidth_mm']:
            fault('INVALID_MODEL', 'model footprint is narrower than two extrusion widths', '$.model.file', axis=name, size_mm=size[axis])
    if size[2] > printer['maxPrintHeight_mm']:
        fault('MODEL_OUT_OF_BOUNDS', 'model is taller than the declared maximum print height', '$.printer.maxPrintHeight_mm',
              height_mm=size[2])
    if size[2] < settings['firstLayerHeight_mm']:
        fault('INVALID_MODEL', 'model is thinner than the first layer', '$.model.file', height_mm=size[2])
    return result


def native_command(executable, stage, prepared, digests):
    arguments = ['--datadir', '.prusaslicer-data', '--loglevel', '1']
    files = []
    if stage == 'version':
        arguments = ['--help']
    elif stage == 'info':
        arguments += ['--info', 'model.stl']
        files = [['model.stl', digests['model.stl']]]
    else:
        centre = ','.join(profile.number(value) for value in prepared['placement']['centre_mm'])
        load, output, model = (('config.ini', 'model.gcode', 'model.stl') if stage == 'slice'
                               else ('../model.gcode', 'reopened.gcode', '../model.stl'))
        arguments += ['--threads', '1', '--load', load, '--scale', profile.number(prepared['scale']), '--center', centre,
                      '--export-gcode', '--output', output, model]
        files = [[load, digests[Path(load).name]], [model, digests['model.stl']]]
    spec = {'files': files, 'command': [executable, *arguments]}
    return [sys.executable, '-c', DRIVER, json.dumps(spec, sort_keys=True)]


def environment(directory):
    home = Path(directory)/'.native-home'
    return {'HOME': str(home), 'XDG_CONFIG_HOME': str(home/'config'), 'XDG_CACHE_HOME': str(home/'cache'),
            'XDG_DATA_HOME': str(home/'data'), 'LC_ALL': 'C', 'LANG': 'C'}


def runtime_identity(stdout):
    first = stdout.decode('utf-8', 'replace').splitlines()[:1]
    match = re.match(r'PrusaSlicer-(\d+\.\d+\.\d+)(\+\S+)?(\s|$)', first[0] if first else '')
    if not match or match.group(1) != RUNTIME:
        fault('UNSUPPORTED_RUNTIME', 'target stable PrusaSlicer ' + RUNTIME, observed=first[0][:200] if first else '')
    return first[0].split()[0]


def native_info(stdout, mesh):
    values = {}
    for line in stdout.decode('utf-8', 'replace').splitlines():
        key, separator, value = line.partition(' = ')
        if separator:
            values[key.strip()] = value.strip()
    try:
        info = {'size': [float(values['size_' + a]) for a in 'xyz'], 'minimum': [float(values['min_' + a]) for a in 'xyz'],
                'facets': int(values['number_of_facets']), 'manifold': values['manifold'],
                'parts': int(values['number_of_parts']), 'volume': float(values['volume'])}
    except (KeyError, ValueError):
        fault('VERIFICATION_FAILED', 'native model information is incomplete', observed=sorted(values))
    if 'open_edges' in values or any(key in values for key in ('degenerate_facets', 'edges_fixed', 'facets_removed',
                                                               'facets_reversed', 'backwards_edges')):
        fault('VERIFICATION_FAILED', 'native reader reported repair or open edges for a host-accepted mesh', observed=values)
    scale = max(mesh['size'])
    # PrusaSlicer 2.9.6 ModelObject::print_info uses fixed six-decimal output.
    # Add its half-unit rounding error to the native geometry allowance, in raw
    # STL length/cubic units: --info runs before the authored unit conversion.
    rounding = 0.5e-6
    coordinate_tolerance = 1e-5*scale + rounding
    volume_tolerance = 1e-4*mesh['volume'] + rounding
    if (not all(math.isfinite(v) for v in [*info['size'], *info['minimum'], info['volume']])
            or info['facets'] != mesh['triangles'] or info['manifold'] != 'yes' or info['parts'] != 1
            or any(abs(a-b) > coordinate_tolerance for a, b in zip(info['size'], mesh['size']))
            or any(abs(a-b) > coordinate_tolerance for a, b in zip(info['minimum'], mesh['minimum']))
            or abs(info['volume'] - mesh['volume']) > volume_tolerance):
        fault('VERIFICATION_FAILED', 'native model readback differs from independent STL analysis', native=info,
              independent={k: mesh[k] for k in ('size', 'minimum', 'triangles', 'volume')})
    return info


def require(condition, message, **observed):
    if not condition:
        fault('VERIFICATION_FAILED', message, **observed)


def assess(prepared, mesh, info, runtime, data, reopened):
    try:
        replay = gcode.interpret(data, prepared['limits'])
    except gcode.GcodeError as error:
        fault('VERIFICATION_FAILED', 'independent G-code replay failed: ' + str(error), **error.observed)
    header = re.match(r'; generated by PrusaSlicer (\d+\.\d+\.\d+)(\+\S+)? on ', replay['header'])
    require(header is not None and header.group(1) == RUNTIME and runtime.startswith('PrusaSlicer-' + RUNTIME),
            'G-code header differs from the observed native runtime', header=replay['header'][:200], runtime=runtime)
    for key, value in prepared['config']:
        require(key in replay['config'] and profile.same(value, replay['config'][key]),
                'native resolved configuration differs from the declared profile', key=key, expected=value,
                observed=replay['config'].get(key))
    require(replay['commands'].get('G28') == 1, 'the fixed start G-code must home exactly once before motion',
            observed=replay['commands'].get('G28', 0))
    printer, material, settings = prepared['printer'], prepared['material'], prepared['print']
    bed = printer['bedSize_mm']
    low, high = replay['bounds']['min'], replay['bounds']['max']
    require(low[0] >= -COORDINATE and low[1] >= -COORDINATE and high[0] <= bed[0]+COORDINATE and high[1] <= bed[1]+COORDINATE
            and low[2] >= -COORDINATE and high[2] <= printer['maxPrintHeight_mm']+COORDINATE,
            'motion leaves the declared build volume', minimum=low, maximum=high)
    layers = replay['layers']
    height, first, step = mesh['size_mm'][2], settings['firstLayerHeight_mm'], settings['layerHeight_mm']
    zs = [layer['z_mm'] for layer in layers]
    # Every extrusion layer must lie on the first-layer + k x layer-height grid
    # and never above the model. Thin tips or slivers narrower than one line
    # may leave later grid layers empty; those are reported, not hidden.
    slots = []
    for index, z in enumerate(zs):
        slot = 0 if abs(z - first) <= COORDINATE else round((z - first)/step)
        require(z >= first - COORDINATE and abs(first + slot*step - z) <= COORDINATE,
                'extrusion layer is off the declared first-layer/layer-height grid', layer=index+1, z=z)
        slots.append(slot)
    # PrusaSlicer 2.9.6 refuses objects without first-layer extrusion.
    require(slots[0] == 0, 'first extrusion is not on the declared first layer', z=zs[0])
    require(zs[-1] <= height + COORDINATE, 'extrusion above the model height', top=zs[-1], height=height)
    expected = sorted({round(value, 3) for value in replay['annotations']})
    require(expected == [round(z, 3) for z in zs], 'native layer annotations differ from replayed extrusion layers',
            annotations=expected[:5], replay=zs[:5])
    width, centre = settings['extrusionWidth_mm'], prepared['placement']['centre_mm']
    inner = [[centre[a] - mesh['size_mm'][a]/2 + width/2, centre[a] + mesh['size_mm'][a]/2 - width/2] for a in (0, 1)]
    union = [[min(l['min'][a] for l in layers), max(l['max'][a] for l in layers)] for a in (0, 1)]
    for layer in layers:
        for a in (0, 1):
            require(layer['min'][a] >= inner[a][0] - COORDINATE and layer['max'][a] <= inner[a][1] + COORDINATE,
                    'extrusion centreline leaves the model footprint inset by half the extrusion width',
                    layer=layer['layer'], axis='xy'[a], observed=[layer['min'][a], layer['max'][a]], allowed=inner[a])
    deviation = max(abs(union[a][s] - inner[a][s]) for a in (0, 1) for s in (0, 1))
    temperatures = {'firstLayerNozzle_C': material['firstLayerNozzleTemperature_C'], 'nozzle_C': material['nozzleTemperature_C'],
                    'firstLayerBed_C': material['firstLayerBedTemperature_C'], 'bed_C': material['bedTemperature_C']}
    waits = [entry for entry in replay['waits'] if entry['beforeFirstExtrusion']]
    require(any(e['command'] == 'M109' and e['celsius'] == temperatures['firstLayerNozzle_C'] for e in waits),
            'no M109 wait for the first-layer nozzle temperature before extrusion', waits=waits)
    if temperatures['firstLayerBed_C'] > 0:
        require(any(e['command'] == 'M190' and e['celsius'] == temperatures['firstLayerBed_C'] for e in waits),
                'no M190 wait for the first-layer bed temperature before extrusion', waits=waits)
    # First-layer rules apply to the physical first layer (grid slot 0).
    for layer, slot in zip(layers, slots):
        bottom = slot == 0
        nozzle = temperatures['firstLayerNozzle_C' if bottom else 'nozzle_C']
        bed_c = temperatures['firstLayerBed_C' if bottom else 'bed_C']
        observed_bed = [0 if value is None else value for value in layer['bed']]
        require(layer['nozzle'] == [nozzle] and observed_bed == [bed_c],
                'extrusion temperature setpoint differs from the declared material profile', layer=layer['layer'],
                nozzle=layer['nozzle'], bed=layer['bed'])
        fan = 0 if bottom else material['fanSpeed_percent']
        require(len(layer['fan']) == 1 and abs(layer['fan'][0] - fan) <= 100/255/2 + 1e-9,
                'fan setpoint differs from the declared material profile', layer=layer['layer'], fan=layer['fan'])
        limit = settings['firstLayerSpeed_mm_s'] if bottom else max(settings['perimeterSpeed_mm_s'], settings['infillSpeed_mm_s'])
        require(layer['maxFeed_mm_s'] <= limit + FEED, 'extrusion feedrate exceeds the declared speed', layer=layer['layer'],
                observed=layer['maxFeed_mm_s'], maximum=limit)
    allowed = {temperatures['firstLayerNozzle_C'], temperatures['nozzle_C'], 0}
    allowed_bed = {temperatures['firstLayerBed_C'], temperatures['bed_C'], 0}
    for entry in replay['temperatures']:
        require(entry['celsius'] in (allowed if entry['command'] in ('M104', 'M109') else allowed_bed),
                'G-code sets an undeclared temperature', entry=entry)
    totals = replay['totals']
    require(totals['maxTravelFeed_mm_s'] <= settings['travelSpeed_mm_s'] + FEED, 'travel feedrate exceeds the declared speed',
            observed=totals['maxTravelFeed_mm_s'])
    statistics = replay['statistics']
    require(set(statistics) >= {'filamentLength_mm', 'filamentVolume_cm3', 'filamentMass_g', 'printTime_s', 'firstLayerPrintTime_s'},
            'native estimates are missing', observed=sorted(statistics))
    length = totals['extrudedLength_mm']
    area = math.pi*material['filamentDiameter_mm']**2/4
    volume = length*area/1000
    mass = volume*material['density_g_cm3']
    tolerance = 0.006 + 5e-6*totals['extrusionMoves']
    require(abs(statistics['filamentLength_mm'] - length) <= tolerance + 1e-4*length,
            'native filament length differs from the replayed extrusion', native=statistics['filamentLength_mm'], replay=length)
    require(abs(statistics['filamentVolume_cm3'] - volume) <= 0.006 + area*tolerance/1000 + 1e-4*volume,
            'native filament volume differs from replayed extrusion', native=statistics['filamentVolume_cm3'], replay=volume)
    require(abs(statistics['filamentMass_g'] - mass) <= 0.006 + material['density_g_cm3']*(area*tolerance/1000) + 1e-4*mass,
            'native filament mass differs from replayed extrusion and declared density', native=statistics['filamentMass_g'], replay=mass)
    lower, upper = totals['kinematicLowerBound_s'], totals['accelerationUpperBound_s']
    require(lower - 1 <= statistics['printTime_s'] <= upper + 1,
            'native print time estimate lies outside independent kinematic bounds', native=statistics['printTime_s'],
            lower=lower, upper=upper)
    require(0 < statistics['firstLayerPrintTime_s'] <= statistics['printTime_s'], 'native first-layer time estimate is inconsistent')
    ratio = volume*1000/mesh['volume_mm3']
    require(0 < ratio <= 1.2, 'deposited volume is implausible for the model volume', ratio=ratio)
    lines, again = data.split(b'\n'), reopened.split(b'\n')
    require(len(lines) == len(again) and all(a == b for a, b in zip(lines, again) if not a.startswith(b'; generated by ')),
            'fresh native reload of the published G-code configuration produced different G-code')
    rows = [[layer['layer'], layer['z_mm'], layer['moves'], layer['path_mm'], layer['filament_mm'], layer['min'][0],
             layer['max'][0], layer['min'][1], layer['max'][1], layer['maxFeed_mm_s'], layer['nozzle'][0],
             0 if layer['bed'][0] is None else layer['bed'][0], layer['fan'][0]] for layer in layers]
    native = {
        'model': {'triangles': mesh['triangles'], 'size_mm': mesh['size_mm'], 'volume_mm3': mesh['volume_mm3'],
                  'sha256': mesh['sha256'], 'units': mesh['units'], 'nativeInfo': info},
        'layers': {'count': len(zs), 'first_mm': zs[0], 'top_mm': zs[-1], 'modelHeight_mm': height,
                   'topGap_mm': height - zs[-1], 'skippedGridLayers': slots[-1] + 1 - len(zs) - slots[0]},
        'envelope': {'expected_mm': inner, 'observed_mm': union, 'maxDeviation_mm': deviation},
        'temperatures': temperatures, 'fan_percent': material['fanSpeed_percent'],
        'feedrates': {'maxExtrusion_mm_s': max(layer['maxFeed_mm_s'] for layer in layers),
                      'maxTravel_mm_s': totals['maxTravelFeed_mm_s']},
        'filament': {'replayLength_mm': length, 'replayVolume_cm3': volume, 'replayMass_g': mass,
                     'nativeLength_mm': statistics['filamentLength_mm'], 'nativeVolume_cm3': statistics['filamentVolume_cm3'],
                     'nativeMass_g': statistics['filamentMass_g'], 'depositedToModelVolume': ratio},
        'time': {'native_s': statistics['printTime_s'], 'nativeFirstLayer_s': statistics['firstLayerPrintTime_s'],
                 'kinematicLowerBound_s': lower, 'accelerationUpperBound_s': upper},
        'moves': {k: totals[k] for k in ('extrusionMoves', 'travelMoves', 'retractions', 'deretractions')},
        'reopenedIdentical': True,
    }
    return native, rows


def summary(prepared, native, runtime):
    quantities = {'printTime_s': native['time']['native_s'], 'filamentMass_g': native['filament']['nativeMass_g'],
                  'filamentLength_mm': native['filament']['nativeLength_mm']}
    requirements = []
    for entry in prepared['requirements']:
        measured = quantities[entry['quantity']]
        margin = entry['maximum'] - measured
        requirements.append({**entry, 'observed': measured, 'margin': margin, 'accepted': margin >= 0,
            'nextAction': 'Accept this native estimate.' if margin >= 0 else 'Reduce infill/perimeters, raise layer height or speeds, or revise the declared limit; rerun a fresh attempt.'})
    return {'version': 'schemaxis.prusaslicer.summary/1', 'runtime': runtime,
            'accepted': all(entry['accepted'] for entry in requirements),
            'units': {'length': 'mm', 'time': 's', 'temperature': 'degC', 'mass': 'g', 'volume': 'cm3 filament, mm3 model'},
            'estimates': quantities, 'requirements': requirements, 'native': native, 'losses': LOSSES}


def checked(directory, prepared):
    data = bounded(directory/'model.stl', stl.MAX_BYTES)
    mesh = analyse_model(prepared, data)
    if bounded(directory/'config.ini') != profile.ini(prepared['config']):
        fault('VERIFICATION_FAILED', 'retained configuration differs from the declared profile')
    runtime = runtime_identity(bounded(directory/'version.stdout'))
    info = native_info(bounded(directory/'info.stdout'), mesh)
    native, rows = assess(prepared, mesh, info, runtime, bounded(directory/'model.gcode'),
                          bounded(directory/'reopen'/'reopened.gcode'))
    return mesh, native, rows, runtime


def receipt(directory, prepared):
    mesh, native, rows, runtime = checked(directory, prepared)
    assessment = summary(prepared, native, runtime)
    if read_json(directory/'slice-summary.json') != assessment:
        fault('VERIFICATION_FAILED', 'published slice summary differs from checked native values')
    table = parse_csv(bounded(directory/'layers.csv'))
    if table['columns'] != HEADER or table['rows'] != rows:
        fault('VERIFICATION_FAILED', 'published layer table differs from the replayed G-code')
    evidence = ['authored.json', 'plan.json', 'model.stl', 'version.stdout', 'version-submission.json',
                'info.stdout', 'info-submission.json', 'slice.stdout', 'slice.stderr', 'slice-submission.json',
                'reopen/reopened.gcode', 'reopen/reopen-submission.json']
    return {'artifacts': [{'file': str(directory/name), 'kind': kind, 'sha256': hashlib.sha256(bounded(directory/name)).hexdigest()}
                          for name, kind in FILES],
            'evidence': {name: hashlib.sha256(bounded(directory/name)).hexdigest() for name in evidence},
            'model': {'sha256': mesh['sha256'], 'units': mesh['units']},
            'native': native, 'assessment': assessment, 'runtime': runtime, 'losses': LOSSES}


def checked_submission(directory, stage, expected):
    submission = read_json(directory/(stage + '-submission.json'))
    source_text = ('import os\n' + f'os.chdir({str(directory)!r})\n' + f'command = {list(map(str, expected))!r}\n'
                   + 'os.execvpe(command[0], command, os.environ)\n')
    script = directory/'.dispatch'/stage/('replay-' + hashlib.sha256(source_text.encode()).hexdigest()[:16] + '.py')
    if (not isinstance(submission, dict) or submission.get('nativeCommand') != expected
            or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0):
        fault('VERIFICATION_FAILED', 'native submission recipe or exit status differs', stage)
    if (submission.get('interpreter') != {'kind': 'native', 'executable': sys.executable}
            or submission.get('scriptPath') != str(script) or bounded(script) != source_text.encode()):
        fault('VERIFICATION_FAILED', 'trusted replay source or command binding differs', stage)
    # The shared runner records the final 4000 characters of each stream.
    if submission.get('stdout') != bounded(directory/(stage + '.stdout')).decode('utf-8', 'replace')[-4000:] \
            or submission.get('stderr') != bounded(directory/(stage + '.stderr')).decode('utf-8', 'replace')[-4000:]:
        fault('VERIFICATION_FAILED', 'native submission log bindings differ', stage)


def digests_of(directory):
    return {'model.stl': hashlib.sha256(bounded(directory/'model.stl', stl.MAX_BYTES)).hexdigest(),
            'config.ini': hashlib.sha256(bounded(directory/'config.ini')).hexdigest(),
            'model.gcode': hashlib.sha256(bounded(directory/'model.gcode')).hexdigest()}


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    if executable is None:
        executable = os.environ.get('PRUSASLICER_EXECUTABLE') or shutil.which('prusa-slicer')
    try:
        usable = (isinstance(executable, (str, os.PathLike)) and Path(executable).is_absolute()
                  and Path(executable).is_file() and os.access(executable, os.X_OK))
    except (ValueError, OSError):
        usable = False
    if not usable:
        fault('INTERPRETER_NOT_FOUND', 'provide an absolute usable PrusaSlicer ' + RUNTIME + ' console executable')
    executable = os.fspath(executable)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be in (0, 3600]')
    try:
        directory = Path(directory).absolute()
    except (TypeError, ValueError, OSError):
        fail('INVALID_ARGUMENT', 'output directory must be a usable filesystem path')
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a fresh output directory', str(directory))
    deadline = time.monotonic() + timeout
    # Validate the model and placement before creating evidence or launching.
    data = source(prepared['model']['file'])
    analyse_model(prepared, data)
    try:
        directory.mkdir(parents=True)
        atomic_json(directory/'authored.json', document)
        atomic_json(directory/'plan.json', prepared)
        atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
        (directory/'model.stl').write_bytes(data)
        (directory/'config.ini').write_bytes(profile.ini(prepared['config']))
        (directory/'reopen').mkdir()
        for path in (directory/'.native-home', directory/'.prusaslicer-data', directory/'reopen'/'.prusaslicer-data'):
            path.mkdir(parents=True)
    except (OSError, ValueError) as error:
        fault('OUTPUT_WRITE_FAILED', 'cannot create retained attempt: ' + str(error), str(directory))
    try:
        digests = {'model.stl': hashlib.sha256(data).hexdigest(),
                   'config.ini': hashlib.sha256(profile.ini(prepared['config'])).hexdigest()}
        env = environment(directory)
        for stage in STAGES:
            target = directory/'reopen' if stage == 'reopen' else directory
            if stage == 'reopen':
                digests['model.gcode'] = hashlib.sha256(bounded(directory/'model.gcode')).hexdigest()
            execute(native_command(executable, stage, prepared, digests), target, stage, deadline - time.monotonic(),
                    environment=env)
            output = {'slice': target/'model.gcode', 'reopen': target/'reopened.gcode'}.get(stage)
            if output is not None and not output.is_file():
                # PrusaSlicer 2.9.6 can report a configuration refusal on
                # stderr and still exit 0; the missing publication is decisive.
                stderr = (target/(stage + '.stderr')).read_bytes()[-2000:].decode('utf-8', 'replace')
                fault('NATIVE_EXECUTION_FAILED', 'PrusaSlicer produced no G-code', str(target), stage=stage, stderr=stderr)
        mesh, native, rows, runtime = checked(directory, prepared)
        assessment = summary(prepared, native, runtime)
        atomic_json(directory/'slice-summary.json', assessment)
        write_csv(directory/'layers.csv', {'columns': HEADER, 'rows': rows})
        atomic_json(directory/'verification.json', receipt(directory, prepared))
        verify(directory, require_result=False)
        if not assessment['accepted']:
            fault('PERFORMANCE_NOT_MET', 'declared native-estimate limits were not met', '$.requirements',
                  requirements=assessment['requirements'])
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'slicing cancelled')
        if time.monotonic() > deadline:
            fail('RUNNER_TIMED_OUT', 'slicing exhausted total timeout')
        result = {'status': 'succeeded', 'verified': True, 'artifacts': len(FILES)}
        atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fault('NATIVE_EXECUTION_FAILED', str(error), str(directory))
            except SchemaxisError as converted:
                error = converted
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        result = read_json(directory/'result.json')
        if not isinstance(result, dict):
            fault('VERIFICATION_FAILED', 'result must be an object')
        if require_result and (result.get('status') != 'succeeded' or result.get('verified') is not True):
            fail('INCOMPLETE_EXECUTION', 'slice did not complete with accepted requirements')
        prepared = plan(read_json(directory/'authored.json'))
        if read_json(directory/'plan.json') != prepared:
            fault('VERIFICATION_FAILED', 'saved slicing plan differs')
        submission = read_json(directory/'version-submission.json')
        recorded = submission.get('nativeCommand') if isinstance(submission, dict) else None
        try:
            executable = json.loads(recorded[3])['command'][0]
        except (TypeError, ValueError, KeyError, IndexError):
            fault('VERIFICATION_FAILED', 'native executable identity differs')
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            fault('VERIFICATION_FAILED', 'native executable identity differs')
        digests = digests_of(directory)
        for stage in STAGES:
            target = directory/'reopen' if stage == 'reopen' else directory
            checked_submission(target, stage, native_command(executable, stage, prepared, digests))
        expected = receipt(directory, prepared)
        if read_json(directory/'verification.json') != expected:
            fault('VERIFICATION_FAILED', 'saved native/publication evidence differs')
        if not expected['assessment']['accepted']:
            fault('PERFORMANCE_NOT_MET', 'declared native-estimate limits are not accepted', '$.requirements',
                  requirements=expected['assessment']['requirements'])
        return {'verified': True, 'artifacts': len(FILES), 'runtime': expected['runtime'],
                'native': expected['native'], 'assessment': expected['assessment']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        fault('VERIFICATION_FAILED', 'missing or malformed slicing evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
