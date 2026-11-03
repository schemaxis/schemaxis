# Copyright (C) 2026 David L F Gaden
"""Bounded thresholded particle measurement with headless ImageJ 1.x."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from schemaxis.tabular import parse_csv, write_csv
from . import images
from .program import NAME, PROGRAM

VERSION = 'schemaxis.imagej/1'
MAX_EVIDENCE = 16*1024*1024
UNITS = {'nm': 'nm', 'um': 'µm', 'mm': 'mm', 'cm': 'cm', 'm': 'm'}
FORMATS = {'.pgm': 'pgm', '.tif': 'tiff', '.tiff': 'tiff'}
SCALE = {'type': 'number', 'minimum': 1e-6, 'maximum': 1e6, 'required': True}
LEVEL = {'type': 'integer', 'minimum': 0, 'maximum': 65535, 'required': True}
AREA = {'type': 'number', 'minimum': 0, 'maximum': 1e30}
OPTIONS = {
    'image': {'type': 'string', 'minLength': 2, 'maxLength': 4096, 'required': True},
    'calibration': {'type': 'object', 'required': True, 'properties': {
        'pixelWidth': SCALE, 'pixelHeight': SCALE,
        'unit': {'type': 'enum', 'values': list(UNITS), 'required': True}}},
    'threshold': {'type': 'object', 'required': True, 'properties': {'lower': LEVEL, 'upper': LEVEL}},
    'connectivity': {'type': 'enum', 'values': ['eight', 'four'], 'default': 'eight'},
    'includeHoles': {'type': 'boolean', 'default': False},
    'excludeEdges': {'type': 'boolean', 'default': False},
    'minimumArea': {**AREA, 'default': 0},
    'maximumArea': AREA}
DECLARATIONS = {'analyzeParticles': {
    'native': 'ij.plugin.filter.ParticleAnalyzer (ImageJ 1.x Analyze Particles)',
    'kinds': ['table', 'text'], 'inputs': {},
    'options': {key: {'value': value} for key, value in OPTIONS.items()}}}
COLUMNS = ['particle', 'pixelCount', 'area_{u}2', 'centroidX_{u}', 'centroidY_{u}', 'boundsX_{u}', 'boundsY_{u}',
           'boundsWidth_{u}', 'boundsHeight_{u}', 'meanIntensity', 'minimumIntensity', 'maximumIntensity']
NATIVE_COLUMNS = ['Area', 'Mean', 'Min', 'Max', 'X', 'Y', 'BX', 'BY', 'Width', 'Height']
PUBLICATIONS = [('particles.csv', 'table'), ('particle-summary.json', 'text')]
STAGES = ('analyse', 'reopen')
LOSSES = ['One 8/16-bit unsigned grayscale plane per run; no colour, stacks, time series, ROI selections or density calibration',
          'Only an inclusive manual raw-intensity threshold; no automatic threshold methods, background subtraction, filtering or watershed separation',
          'Measurements are pixel-count area, pixel-centre centroid, axis-aligned bounding box and raw intensity mean/min/max; no perimeter, shape descriptors or Feret diameters',
          'Spatial calibration is the declared square or rectangular pixel size with origin at the top-left corner; calibration embedded in the file is recorded and replaced',
          'particles.csv alone omits image provenance, threshold and calibration; retain particle-summary.json with the table']
COORDINATES = ('Origin at the top-left image corner, x to the right and y downward; pixel (i, j) has its centre at '
               '((i+0.5)*pixelWidth, (j+0.5)*pixelHeight). Bounds are the outer pixel edges.')


def columns(unit):
    return [name.replace('{u}', unit) for name in COLUMNS]


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected '+VERSION)
    if document.get('operation') != 'analyzeParticles': fail('UNKNOWN_FILTER', 'select analyzeParticles', '$.operation')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k not in ('version', 'operation')}, location='$')
    path = prepared['image']
    if any(ord(char) < 32 or ord(char) == 127 for char in path) or not Path(path).is_absolute():
        fail('INVALID_RESOURCE', 'image must be an absolute local file path without control characters', '$.image')
    extension = Path(path).suffix.lower()
    if extension not in FORMATS:
        fail('UNSUPPORTED_IMAGE', 'image must be a .pgm, .tif or .tiff grayscale file', '$.image', observed=extension)
    threshold = prepared['threshold']
    if threshold['lower'] > threshold['upper']:
        fail('INVALID_THRESHOLD', 'threshold lower must not exceed upper; both bounds are inclusive raw intensities',
             '$.threshold', lower=threshold['lower'], upper=threshold['upper'])
    if prepared['connectivity'] == 'four' and not prepared['includeHoles']:
        fail('UNSUPPORTED_OPTION', 'ImageJ fills interior holes for 4-connected particles; set includeHoles true '
             'or use eight connectivity', '$.includeHoles')
    calibration = prepared['calibration']
    pixel_area = calibration['pixelWidth']*calibration['pixelHeight']
    # Calibrated area bounds become exact inclusive pixel counts before native assignment.
    minimum = max(0, math.ceil(prepared['minimumArea']/pixel_area - 1e-9))
    maximum = math.floor(prepared['maximumArea']/pixel_area + 1e-9) if 'maximumArea' in prepared else None
    if minimum > images.MAX_PIXELS or (maximum is not None and maximum < max(minimum, 1)):
        fail('INVALID_SIZE_FILTER', 'the size window contains no whole-pixel particle area; widen minimumArea/maximumArea',
             '$.maximumArea' if 'maximumArea' in prepared else '$.minimumArea',
             minimumPixels=minimum, maximumPixels=maximum, pixelArea=pixel_area)
    unit = calibration['unit']
    return {'version': 'schemaxis.imagej.plan/1', 'operation': 'analyzeParticles', **prepared,
            'format': FORMATS[extension], 'extension': extension, 'nativeUnit': UNITS[unit], 'pixelArea': pixel_area,
            'minimumPixels': minimum, 'maximumPixels': maximum, 'columns': columns(unit), 'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    fields = {'version': {'const': VERSION}, 'operation': {'const': 'analyzeParticles'},
              **{key: argument_schema(value) for key, value in OPTIONS.items()}}
    return {'$schema': DRAFT, **object_schema(fields, ['version', 'operation', 'image', 'calibration', 'threshold'])}


def query(document):
    prepared = plan(document)
    return list(dict.fromkeys(visit['plan']['operation'] for visit in prepared['visits'])) if 'visits' in prepared else [prepared['operation']], {}


def reusableInputs(document):
    path = Path(plan(document)['image'])
    try:
        return {str(path): hashlib.sha256(source_bytes(path)).hexdigest()}
    except SchemaxisError:
        return None


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'this bounded particle analysis uses one thread', identity)
    return {'threads': 1}


def source_bytes(path):
    """Read one bounded regular file through a non-following descriptor."""
    try:
        if Path(path).is_symlink(): fail('INVALID_RESOURCE', 'image may not be a symbolic link', '$.image')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    except OSError as error:
        fail('RESOURCE_NOT_FOUND', 'image cannot be opened: '+error.strerror, '$.image')
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode): fail('INVALID_RESOURCE', 'image must be a regular file', '$.image')
        data = stream.read(images.MAX_FILE_BYTES+1)
    if len(data) > images.MAX_FILE_BYTES:
        fail('RESOURCE_LIMIT', 'image file exceeds 16 MiB', '$.image')
    return data


def settings(prepared):
    return {'lower': prepared['threshold']['lower'], 'upper': prepared['threshold']['upper'],
            'connectivity': prepared['connectivity'], 'includeHoles': prepared['includeHoles'],
            'excludeEdges': prepared['excludeEdges'], 'minimumPixels': prepared['minimumPixels'],
            'maximumPixels': prepared['maximumPixels']}


def reference(prepared, data):
    """Decode independently and reject unsupported content before native launch."""
    image = images.decode(data, prepared['extension'])
    top = (1 << image['bitDepth'])-1
    threshold = prepared['threshold']
    if threshold['upper'] > top:
        fail('INVALID_THRESHOLD', f'{image["bitDepth"]}-bit images have raw intensities 0..{top}',
             '$.threshold.upper', bitDepth=image['bitDepth'], upper=threshold['upper'])
    if threshold['lower'] == 0 and threshold['upper'] == top:
        fail('INVALID_THRESHOLD', 'the threshold selects every pixel; ImageJ treats the full range as one image-sized particle',
             '$.threshold', bitDepth=image['bitDepth'])
    analysis = images.analyse(image, settings(prepared))
    if not analysis['particles']:
        fail('NO_PARTICLES', 'no particle passes the declared threshold, edge and size filters; a measurement table needs at least one row',
             '$.threshold', thresholdPixels=analysis['thresholdPixels'], rejected=analysis['rejected'])
    return image, analysis


def commands(java, jar, directory, prepared, count):
    calibration = prepared['calibration']
    base = [str(java), '-Djava.awt.headless=true', '-Dfile.encoding=UTF-8', '-Duser.language=en', '-Duser.country=CA',
            '-Duser.home='+str(directory/'imagej-home'), '-Djava.io.tmpdir='+str(directory/'imagej-home'),
            '-Dplugins.dir='+str(directory/'imagej-home'), '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC',
            '-Xmx512m', '-cp', str(jar), str(directory/NAME)]
    image = str(directory/('input'+prepared['extension']))
    scale = [image, prepared['format'], repr(float(calibration['pixelWidth'])), repr(float(calibration['pixelHeight'])), calibration['unit']]
    maximum = 'Infinity' if prepared['maximumPixels'] is None else str(prepared['maximumPixels'])
    return {'analyse': base+['analyse', *scale, str(prepared['threshold']['lower']), str(prepared['threshold']['upper']),
                             prepared['connectivity'], str(int(prepared['includeHoles'])), str(int(prepared['excludeEdges'])),
                             str(prepared['minimumPixels']), maximum],
            'reopen': base+['reopen', *scale, str(directory/'count-mask.pgm'), str(count)]}


def evidence_names(prepared):
    return ['input'+prepared['extension'], NAME, 'runtime.json', 'java-version.stderr', 'analyse-readback.txt',
            'native-particles.csv', 'count-mask.pgm', 'reopen-readback.txt', 'reopen-particles.csv',
            *[stage+suffix for stage in ('java-version', *STAGES) for suffix in ('-submission.json', '.stdout', '.stderr')
              if stage+suffix != 'java-version.stderr']]


def payload(directory, name, limit=MAX_EVIDENCE):
    path = Path(directory)/name
    try:
        if path.is_symlink(): raise OSError('symbolic link')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise OSError('not a regular file')
            data = stream.read(limit+1)
    except OSError as error:
        fail('VERIFICATION_FAILED', 'required bounded regular evidence is absent: '+str(error), name)
    if len(data) > limit: fail('VERIFICATION_FAILED', 'retained evidence byte budget exceeded', name)
    return data


def digest(directory, name):
    return hashlib.sha256(payload(directory, name)).hexdigest()


def read_json(directory, name):
    value = json.loads(payload(directory, name))
    if not isinstance(value, dict): fail('VERIFICATION_FAILED', 'expected evidence object', name)
    return value


def readback(directory, name, extra):
    lines = payload(directory, name).decode('utf-8').splitlines()
    pairs = [line.partition('=') for line in lines]
    values = {key: value for key, _, value in pairs}
    expected = ['stage', 'imagej', 'java', 'inputSha256', 'width', 'height', 'bitDepth', 'stackSize', 'invertedLut',
                'densityCalibrated', 'pixelWidth', 'pixelHeight', 'unit', 'yUnit', 'origin', *extra]
    if [key for key, _, _ in pairs] != expected or any(not separator for _, separator, _ in pairs):
        fail('VERIFICATION_FAILED', 'native readback fields differ from the fixed program contract', name)
    return values


def runtime_identity(text):
    found = re.fullmatch(r'1\.54[a-z]\d*', text or '')
    if not found: fail('UNSUPPORTED_RUNTIME', 'expected an ImageJ 1.54 release (ij.jar); observed '+repr(text))
    return text


def java_identity(text):
    found = re.search(r'version "(\d+)(?:\.(\d+))?[^"]*"', text)
    major = int(found[1]) if found and found[1] != '1' else int(found[2]) if found and found[2] else 0
    if major < 11:
        fail('UNSUPPORTED_RUNTIME', 'the fixed ImageJ program needs a Java 11 or newer runtime with the jdk.compiler module')
    return major


def check(condition, message, location=None, **details):
    if not condition: fail('VERIFICATION_FAILED', message, location, **details)


def near(actual, expected, scale):
    return math.isfinite(actual) and abs(actual-expected) <= 1e-12*max(abs(expected), scale)


def expected_row(prepared, image, particle):
    calibration = prepared['calibration']
    width, height = calibration['pixelWidth'], calibration['pixelHeight']
    count = particle['pixelCount']
    return [count*width*height, particle['sum']/count, particle['minimum'], particle['maximum'],
            (particle['sumX']/count+0.5)*width, (particle['sumY']/count+0.5)*height,
            particle['left']*width, particle['top']*height, particle['width']*width, particle['height']*height]


def native_rows(directory, name, prepared, image, analysis):
    table = parse_csv(payload(directory, name), location=name)
    check(table['columns'] == NATIVE_COLUMNS, 'native measurement columns differ', name)
    check(len(table['rows']) == len(analysis['particles']), 'native particle count differs from the independent model', name,
          native=len(table['rows']), independent=len(analysis['particles']))
    calibration = prepared['calibration']
    scales = [prepared['pixelArea'], 1, 1, 1, calibration['pixelWidth'], calibration['pixelHeight'],
              calibration['pixelWidth'], calibration['pixelHeight'], calibration['pixelWidth'], calibration['pixelHeight']]
    for index, (row, particle) in enumerate(zip(table['rows'], analysis['particles'])):
        for column, (actual, expected, scale) in enumerate(zip(row, expected_row(prepared, image, particle), scales)):
            check(near(actual, expected, scale), 'native measurement differs from the independent particle model',
                  f'{name}/rows/{index}/{NATIVE_COLUMNS[column]}', native=actual, independent=expected)
    return table['rows']


def publication(prepared, analysis, rows):
    values = []
    for particle, row in zip(analysis['particles'], rows):
        area, mean, minimum, maximum, x, y, left, top, width, height = row
        values.append([particle['label'], particle['pixelCount'], area, x, y, left, top, width, height, mean, minimum, maximum])
    return {'columns': prepared['columns'], 'rows': values}


def summary(prepared, image, analysis, rows, digests, versions):
    calibration = prepared['calibration']
    unit = calibration['unit']
    total = sum(particle['pixelCount'] for particle in analysis['particles'])
    pixels = image['width']*image['height']
    units = dict(zip(prepared['columns'], ['label', 'pixels', unit+'^2', *[unit]*6, 'raw intensity', 'raw intensity', 'raw intensity']))
    return {'version': 'schemaxis.imagej.summary/1', 'operation': 'analyzeParticles',
            'runtime': {'name': 'ImageJ', 'version': versions['imagej'], 'java': versions['java']},
            'image': {'format': image['format'], 'width': image['width'], 'height': image['height'],
                      'bitDepth': image['bitDepth'], 'byteOrder': image['byteOrder'], 'sha256': digests['input'],
                      'name': Path(prepared['image']).name},
            'calibration': {'pixelWidth': calibration['pixelWidth'], 'pixelHeight': calibration['pixelHeight'],
                            'unit': unit, 'nativeUnit': prepared['nativeUnit'], 'pixelArea': prepared['pixelArea'],
                            'areaUnit': unit+'^2', 'coordinates': COORDINATES},
            'threshold': {'lower': prepared['threshold']['lower'], 'upper': prepared['threshold']['upper'],
                          'inclusive': True, 'scale': 'raw stored intensity', 'thresholdPixels': analysis['thresholdPixels']},
            'connectivity': prepared['connectivity'], 'includeHoles': prepared['includeHoles'],
            'excludeEdges': prepared['excludeEdges'],
            'sizeFilter': {'minimumArea': prepared['minimumArea'], 'maximumArea': prepared.get('maximumArea'),
                           'minimumPixels': prepared['minimumPixels'], 'maximumPixels': prepared['maximumPixels']},
            'particleCount': len(analysis['particles']), 'rejected': analysis['rejected'],
            'totalPixels': total, 'totalArea': total*prepared['pixelArea'], 'areaFraction': total/pixels,
            'meanArea': total*prepared['pixelArea']/len(analysis['particles']),
            'columns': prepared['columns'], 'units': units, 'countMaskSha256': digests['mask'],
            'verification': 'Native ParticleAnalyzer rows, count-mask labels and fresh ImageStatistics readback match an independent connected-component model within 1e-12 relative.',
            'losses': LOSSES}


def manifest(directory):
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in PUBLICATIONS]


def run(document, directory, *, executable=None, jar=None, timeout=300):
    prepared = plan(document)
    executable = executable or shutil.which('java')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute Java 11+ executable for ImageJ (schemaxis configure imagej, or --imagej)')
    if not jar or not Path(jar).is_absolute() or Path(jar).suffix != '.jar' or not Path(jar).is_file():
        fail('INTERPRETER_NOT_FOUND', 'configure the absolute ImageJ 1.54 ij.jar location as imagejJar or pass --imagej-jar')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'choose a fresh output directory', str(directory))
    try:
        directory.mkdir(parents=True)
        atomic_json(directory/'authored.json', document); atomic_json(directory/'plan.json', prepared)
        atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    except (OSError, ValueError) as error:
        fail('INVALID_RESOURCE', 'cannot create bounded execution location: '+str(error), str(directory))
    deadline = time.monotonic()+timeout
    try:
        data = source_bytes(prepared['image'])
        image, analysis = reference(prepared, data)
        (directory/('input'+prepared['extension'])).write_bytes(data)
        (directory/NAME).write_text(PROGRAM, encoding='utf-8')
        (directory/'imagej-home').mkdir()
        atomic_json(directory/'runtime.json', {'name': 'ImageJ', 'java': str(executable), 'jar': str(jar),
                                                'jarSha256': hashlib.sha256(Path(jar).read_bytes()).hexdigest()})
        environment = {'LC_ALL': 'C', 'JAVA_TOOL_OPTIONS': '', '_JAVA_OPTIONS': '', 'JDK_JAVA_OPTIONS': ''}
        execute([executable, '-version'], directory, 'java-version', deadline-time.monotonic(), environment)
        java_identity(payload(directory, 'java-version.stderr').decode('utf-8', 'replace'))
        native = commands(executable, jar, directory, prepared, len(analysis['particles']))
        for stage in STAGES:
            if cancellation_requested(): fail('RUNNER_CANCELLED', 'particle analysis cancelled', stage)
            execute(native[stage], directory, stage, deadline-time.monotonic(), environment)
        rows = native_rows(directory, 'native-particles.csv', prepared, image, analysis)
        versions = {'imagej': runtime_identity(readback(directory, 'analyse-readback.txt', ANALYSE_FIELDS)['imagej']),
                    'java': readback(directory, 'analyse-readback.txt', ANALYSE_FIELDS)['java']}
        write_csv(directory/'particles.csv', publication(prepared, analysis, rows))
        atomic_json(directory/'particle-summary.json',
                    summary(prepared, image, analysis, rows, {'input': hashlib.sha256(data).hexdigest(),
                                                              'mask': digest(directory, 'count-mask.pgm')}, versions))
        atomic_json(directory/'verification.json', {'artifacts': manifest(directory), 'runtime': versions,
                                                    'evidence': {name: digest(directory, name) for name in evidence_names(prepared)}})
        result = verify(directory, require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'particle publication cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'particle verification exhausted the total timeout')
        result.update(status='succeeded'); atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error), str(directory))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


ANALYSE_FIELDS = ['lowerThreshold', 'upperThreshold', 'options', 'minimumPixels', 'maximumPixels', 'particles', 'maskBitDepth']
REOPEN_FIELDS = ['maskSha256', 'maskBitDepth', 'particles']


def native_options(prepared):
    options = 16  # ParticleAnalyzer.SHOW_ROI_MASKS (count masks)
    if prepared['connectivity'] == 'four': options |= 8192 | 1024  # FOUR_CONNECTED | INCLUDE_HOLES
    if prepared['includeHoles']: options |= 1024
    if prepared['excludeEdges']: options |= 8  # EXCLUDE_EDGE_PARTICLES
    return options


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        prepared = plan(read_json(directory, 'authored.json'))
        check(read_json(directory, 'plan.json') == prepared, 'effective plan differs from authored particle analysis')
        if require_result:
            result = read_json(directory, 'result.json')
            if result.get('status') != 'succeeded' or result.get('verified') is not True:
                fail('INCOMPLETE_EXECUTION', 'particle analysis did not complete')
        check(payload(directory, NAME).decode('utf-8') == PROGRAM, 'trusted fixed ImageJ program differs')
        data = payload(directory, 'input'+prepared['extension'], images.MAX_FILE_BYTES)
        image, analysis = reference(prepared, data)
        runtime = read_json(directory, 'runtime.json')
        check(set(runtime) == {'name', 'java', 'jar', 'jarSha256'} and Path(runtime['java']).is_absolute()
              and Path(runtime['jar']).is_absolute(), 'native runtime record differs')
        java_identity(payload(directory, 'java-version.stderr').decode('utf-8', 'replace'))
        count = len(analysis['particles'])
        native = commands(runtime['java'], runtime['jar'], directory, prepared, count)
        for stage in ('java-version', *STAGES):
            submission = read_json(directory, stage+'-submission.json')
            expected = [runtime['java'], '-version'] if stage == 'java-version' else native[stage]
            check(submission.get('nativeCommand') == expected and type(submission.get('exitCode')) is int
                  and submission['exitCode'] == 0, 'native command or completion differs', stage)
        source = hashlib.sha256(data).hexdigest()
        calibration = prepared['calibration']
        unit = ','.join(str(ord(char)) for char in prepared['nativeUnit'])
        observed = {}
        for stage, name, extra in (('analyse', 'analyse-readback.txt', ANALYSE_FIELDS), ('reopen', 'reopen-readback.txt', REOPEN_FIELDS)):
            values = observed[stage] = readback(directory, name, extra)
            check(values['stage'] == stage and values['inputSha256'] == source, 'native stage consumed different input bytes', name)
            check([values['width'], values['height'], values['bitDepth'], values['stackSize']]
                  == [str(image['width']), str(image['height']), str(image['bitDepth']), '1'],
                  'ImageJ decoded different image dimensions, depth or plane count', name)
            if values['densityCalibrated'] != 'false' or values['invertedLut'] != 'false':
                fail('UNSUPPORTED_IMAGE', 'ImageJ reports density calibration or an inverted lookup table; supply plain raw intensities', '$.image')
            check(float(values['pixelWidth']) == calibration['pixelWidth'] and float(values['pixelHeight']) == calibration['pixelHeight']
                  and values['unit'] == unit and values['yUnit'] == unit and values['origin'] == '0.0,0.0',
                  'native calibration readback differs from the declared calibration', name)
            check(values['particles'] == str(count) and values['maskBitDepth'] == '16', 'native particle/mask readback differs', name)
        analyse_values = observed['analyse']
        check(float(analyse_values['lowerThreshold']) == prepared['threshold']['lower']
              and float(analyse_values['upperThreshold']) == prepared['threshold']['upper'], 'native threshold readback differs')
        check(analyse_values['options'] == str(native_options(prepared))
              and float(analyse_values['minimumPixels']) == prepared['minimumPixels']
              and float(analyse_values['maximumPixels']) == (math.inf if prepared['maximumPixels'] is None else prepared['maximumPixels']),
              'native particle-analyser options differ')
        versions = {'imagej': runtime_identity(analyse_values['imagej']), 'java': analyse_values['java']}
        check(observed['reopen']['imagej'] == versions['imagej'] and observed['reopen']['java'] == versions['java'],
              'fresh native process used a different runtime')
        labels = images.read_label_pgm(payload(directory, 'count-mask.pgm'), image['width'], image['height'])
        check(labels == analysis['labels'], 'native count-mask labels differ from the independent particle model', 'count-mask.pgm')
        check(observed['reopen']['maskSha256'] == digest(directory, 'count-mask.pgm'), 'fresh process read a different count mask')
        rows = native_rows(directory, 'native-particles.csv', prepared, image, analysis)
        reopened = native_rows(directory, 'reopen-particles.csv', prepared, image, analysis)
        for index, (row, other) in enumerate(zip(rows, reopened)):
            check(all(near(a, b, 1e-300) for a, b in zip(row, other)), 'fresh ImageStatistics readback differs from ParticleAnalyzer', f'reopen-particles.csv/rows/{index}')
        check(parse_csv(payload(directory, 'particles.csv'), location='particles.csv') == publication(prepared, analysis, rows),
              'published particle table differs from verified native measurements')
        details = summary(prepared, image, analysis, rows, {'input': source, 'mask': digest(directory, 'count-mask.pgm')}, versions)
        check(read_json(directory, 'particle-summary.json') == json.loads(json.dumps(details)), 'summary differs from independently checked particles')
        expected = {'artifacts': manifest(directory), 'runtime': versions,
                    'evidence': {name: digest(directory, name) for name in evidence_names(prepared)}}
        check(read_json(directory, 'verification.json') == expected, 'native/publication evidence digest differs')
        return {'verified': True, 'artifacts': len(PUBLICATIONS), 'runtime': versions, 'particles': count,
                'totalArea': details['totalArea'], 'areaUnit': details['calibration']['areaUnit']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError, OverflowError) as error:
        fail('VERIFICATION_FAILED', 'missing or invalid particle evidence: '+str(error))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
