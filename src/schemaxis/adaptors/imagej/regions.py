"""Repeated rectangular-region measurements across a small labelled grayscale series.

The host plans and verifies; ImageJ measures. The oracle here enumerates the exact
source pixels of every declared rectangle in every frame (integers and Fractions) and
never calls ImageJ. Nothing is thresholded, moved, interpolated, registered or inferred.
"""
import csv
import hashlib
import io
import json
import math
import os
from fractions import Fraction
from pathlib import Path
import re
import shutil
import stat
import struct
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import images
from .regions_program import NAME, PROGRAM

OPERATION = 'measureRegions'
UNITS = {'nm': 'nm', 'um': 'µm', 'mm': 'mm', 'cm': 'cm', 'm': 'm'}
FORMATS = {'.pgm': 'pgm', '.tif': 'tiff', '.tiff': 'tiff'}
MIN_FRAMES, MAX_FRAMES, MAX_REGIONS = 2, 8, 16
MAX_SERIES_BYTES = 32*1024*1024
MAX_SERIES_PIXELS = 4*1024*1024
MAX_VISITS = 16*1024*1024  # frames x region pixels enumerated by the oracle and measured natively
MAX_EVIDENCE = 16*1024*1024
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}')
SCALE = {'type': 'number', 'minimum': 1e-6, 'maximum': 1e6, 'required': True}
IDENT = {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}
OPTIONS = {
    'frames': {'type': 'array', 'required': True, 'minItems': MIN_FRAMES, 'maxItems': MAX_FRAMES, 'items': {
        'type': 'object', 'properties': {
            'id': IDENT,
            'image': {'type': 'string', 'minLength': 2, 'maxLength': 4096, 'required': True},
            'timeSeconds': {'type': 'number', 'minimum': 0, 'maximum': 1e9, 'required': True}}}},
    'regions': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': MAX_REGIONS, 'items': {
        'type': 'object', 'properties': {
            'id': IDENT,
            'x': {'type': 'integer', 'minimum': 0, 'maximum': images.MAX_SIDE-1, 'required': True},
            'y': {'type': 'integer', 'minimum': 0, 'maximum': images.MAX_SIDE-1, 'required': True},
            'width': {'type': 'integer', 'minimum': 1, 'maximum': images.MAX_SIDE, 'required': True},
            'height': {'type': 'integer', 'minimum': 1, 'maximum': images.MAX_SIDE, 'required': True}}}},
    'calibration': {'type': 'object', 'required': True, 'properties': {
        'pixelWidth': SCALE, 'pixelHeight': SCALE,
        'unit': {'type': 'enum', 'values': list(UNITS), 'required': True}}}}
DECLARATIONS = {OPERATION: {
    'native': 'ij.ImagePlus/ij.ImageStack, ij.gui.Roi, ij.process.ImageStatistics and ij.measure.Calibration (ImageJ 1.x)',
    'kinds': ['file', 'text'], 'inputs': {},
    'options': {key: {'value': value} for key, value in OPTIONS.items()}}}
COLUMNS = ['frame', 'region', 'timeSeconds', 'pixelCount', 'area_{u}2', 'meanIntensity', 'minimumIntensity', 'maximumIntensity']
NATIVE_COLUMNS = 'Frame,Region,X,Y,Width,Height,Count,Area,Mean,Min,Max'
PUBLICATIONS = [('region-measurements.csv', 'file'), ('region-measurements.json', 'text')]
STAGES = ('measure', 'reopen')
LOSSES = [
    '2 to 8 captured 8/16-bit unsigned grayscale PGM/uncompressed TIFF planes with identical width, height and bit depth; no colour, stacks, density or lookup-table scaling, and no resampling or registration',
    'Rectangles are zero-based top-left integer x, y, width and height with right and bottom edges exclusive; every pixel inside is included, none is weighted. The same rectangle list is applied to every frame; nothing moves, tracks or follows features between frames',
    'Rectangles may overlap or nest: each is an independent measurement over its own pixels, not a partition, so the sum over regions can exceed the image area. Thresholds, masks, non-rectangular selections and an editable ROI set are not produced',
    'Time is the declared finite seconds since a user-chosen origin, strictly increasing in frame order; it is never read from file metadata or inferred from file names or modification times',
    'Intensities are raw stored unsigned sample values. Calibration (declared pixelWidth, pixelHeight and nm/um/mm/cm/m, replacing any calibration stored in the files) applies only to calibrated area; no density, display range, LUT or exposure normalisation is applied',
    'Records give pixel count, calibrated area and raw mean/minimum/maximum per frame and region; no sums, centroids, medians or other statistics are published, and no review overlay image is produced or claimed',
    'region-measurements.csv alone omits source hashes, calibration and conventions; retain region-measurements.json and the captured frames with it']
COORDINATES = ('Origin at the top-left image corner, x to the right and y downward. A rectangle (x, y, width, height) covers pixel '
               'columns x..x+width-1 and rows y..y+height-1; its calibrated area is pixelCount*pixelWidth*pixelHeight.')
TIME_CONVENTION = 'timeSeconds is declared seconds since a user-chosen series origin; frames are listed in strictly increasing time order.'
OVERLAP = 'Regions are independent measurements; they may overlap and are not a disjoint partition.'
READBACK_FIXED = ['stage', 'imagej', 'java', 'jarSha256', 'frames', 'regions', 'stackSize', 'pixelWidth', 'pixelHeight', 'unit', 'yUnit', 'origin']
FRAME_FIELDS = ['sha256', 'width', 'height', 'bitDepth', 'stackSize', 'invertedLut', 'densityCalibrated', 'fileCalibration']


def columns(unit):
    return [name.replace('{u}', unit) for name in COLUMNS]


def identifier(value, location):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        fail('INVALID_IDENTIFIER', 'identifiers are 1-32 ASCII characters: a letter then letters, digits, underscore or hyphen',
             location, observed=value if isinstance(value, str) and len(value) <= 64 else None)
    return value


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != 'schemaxis.imagej/1': fail('UNSUPPORTED_VERSION', 'expected schemaxis.imagej/1')
    for name, location in (('frames', '$.frames'), ('regions', '$.regions')):
        if isinstance(document.get(name), list):
            for index, item in enumerate(document[name]): keys(item, OPTIONS[name]['items']['properties'], f'{location}[{index}]')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k not in ('version', 'operation')}, location='$')
    frames, regions = prepared['frames'], prepared['regions']
    seen, previous = {}, None
    for index, frame in enumerate(frames):
        where = f'$.frames[{index}]'
        identifier(frame['id'], where+'.id')
        if frame['id'] in seen: fail('DUPLICATE_FRAME_ID', 'frame identifiers must be unique', where+'.id', first=seen[frame['id']])
        seen[frame['id']] = index
        path = frame['image']
        if any(ord(char) < 32 or ord(char) == 127 for char in path) or not Path(path).is_absolute():
            fail('INVALID_RESOURCE', 'image must be an absolute local file path without control characters', where+'.image')
        extension = Path(path).suffix.lower()
        if extension not in FORMATS:
            fail('UNSUPPORTED_IMAGE', 'image must be a .pgm, .tif or .tiff grayscale file', where+'.image', observed=extension)
        if not math.isfinite(frame['timeSeconds']): fail('INVALID_TIME', 'timeSeconds must be finite', where+'.timeSeconds')
        if previous is not None and frame['timeSeconds'] <= previous:
            fail('NON_INCREASING_TIME', 'frame times must be strictly increasing in frame order', where+'.timeSeconds',
                 previous=previous, observed=frame['timeSeconds'])
        previous = frame['timeSeconds']
    if len({frame['image'] for frame in frames}) != len(frames):
        fail('DUPLICATE_FRAME_SOURCE', 'each frame needs its own captured image file', '$.frames')
    seen = {}
    for index, region in enumerate(regions):
        where = f'$.regions[{index}]'
        identifier(region['id'], where+'.id')
        if region['id'] in seen: fail('DUPLICATE_REGION_ID', 'region identifiers must be unique', where+'.id', first=seen[region['id']])
        seen[region['id']] = index
    calibration = prepared['calibration']
    pixel_area = calibration['pixelWidth']*calibration['pixelHeight']
    unit = calibration['unit']
    return {'version': 'schemaxis.imagej.plan/1', 'operation': OPERATION,
            'frames': [{**frame, 'format': FORMATS[Path(frame['image']).suffix.lower()],
                        'extension': Path(frame['image']).suffix.lower(), 'file': 'frame-%02d%s' % (index+1, Path(frame['image']).suffix.lower())}
                       for index, frame in enumerate(frames)],
            'regions': regions, 'calibration': calibration, 'nativeUnit': UNITS[unit], 'pixelArea': pixel_area,
            'columns': columns(unit), 'records': len(frames)*len(regions),
            'budget': {'frames': [MIN_FRAMES, MAX_FRAMES], 'regions': [1, MAX_REGIONS], 'seriesBytes': MAX_SERIES_BYTES,
                       'seriesPixels': MAX_SERIES_PIXELS, 'regionPixelVisits': MAX_VISITS,
                       'imageBytes': images.MAX_FILE_BYTES, 'imageSide': images.MAX_SIDE, 'imagePixels': images.MAX_PIXELS},
            'losses': LOSSES}


def schema_branch():
    from schemaxis.schema import argument_schema, object_schema
    fields = {'version': {'const': 'schemaxis.imagej/1'}, 'operation': {'const': OPERATION},
              **{key: argument_schema(value) for key, value in OPTIONS.items()}}
    return object_schema(fields, ['version', 'operation', 'frames', 'regions', 'calibration'])


def open_frame(path, location):
    """Open one frame through a non-following descriptor and return its stream with its fstat."""
    try:
        if Path(path).is_symlink(): fail('INVALID_RESOURCE', 'image may not be a symbolic link', location)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    except OSError as error:
        fail('RESOURCE_NOT_FOUND', 'image cannot be opened: '+error.strerror, location)
    stream = os.fdopen(descriptor, 'rb')
    information = os.fstat(stream.fileno())
    if not stat.S_ISREG(information.st_mode):
        stream.close(); fail('INVALID_RESOURCE', 'image must be a regular file', location)
    return stream, information


def read_frame(stream, location):
    data = stream.read(images.MAX_FILE_BYTES+1)
    if len(data) > images.MAX_FILE_BYTES: fail('RESOURCE_LIMIT', 'image file exceeds 16 MiB', location)
    return data


def capture(path, location):
    """Read one bounded regular file through a non-following descriptor."""
    stream, _ = open_frame(path, location)
    with stream: return read_frame(stream, location)


def capture_series(prepared):
    """Open every frame, refuse alias duplicates and an oversize aggregate from fstat, then read.

    Files are identified by (device, inode), so ``a.pgm``, ``./a.pgm`` and a hard link are one source,
    while distinct files with identical pixels are legitimate (an unchanged scene is meaningful).
    Nothing is read until the aggregate size from fstat is within budget.
    """
    streams, identities, total = [], {}, 0
    try:
        for index, frame in enumerate(prepared['frames']):
            location = f'$.frames[{index}].image'
            stream, information = open_frame(frame['image'], location)
            streams.append(stream)
            identity = (information.st_dev, information.st_ino)
            if identity in identities:
                fail('DUPLICATE_FRAME_SOURCE', 'each frame needs its own captured image file; this path names the same file as an earlier frame',
                     location, first=identities[identity])
            identities[identity] = index
            if information.st_size > images.MAX_FILE_BYTES: fail('RESOURCE_LIMIT', 'image file exceeds 16 MiB', location, observedBytes=information.st_size)
            total += information.st_size
        if total > MAX_SERIES_BYTES:
            fail('RESOURCE_LIMIT', 'the series exceeds the %d MiB aggregate file budget' % (MAX_SERIES_BYTES >> 20), '$.frames',
                 observedBytes=total, maximumBytes=MAX_SERIES_BYTES)
        captured = [read_frame(stream, f'$.frames[{index}].image') for index, stream in enumerate(streams)]
    finally:
        for stream in streams: stream.close()
    if sum(len(data) for data in captured) > MAX_SERIES_BYTES:
        fail('RESOURCE_LIMIT', 'the series grew beyond the %d MiB aggregate file budget while being captured' % (MAX_SERIES_BYTES >> 20), '$.frames')
    return captured


def reusable(document):
    prepared = plan(document)
    try:
        return {frame['image']: hashlib.sha256(capture(frame['image'], '$.frames')).hexdigest() for frame in prepared['frames']}
    except SchemaxisError:
        return None


# ------------------------------------------------------------------ independent oracle
def header(data, extension):
    """Bounded header-only probe: (width, height, bitDepth, set of TIFF tags); None when it cannot be read safely."""
    try:
        if extension == '.pgm':
            if data[:2] != b'P5' or len(data) < 3 or data[2] > 32: return None
            position, fields = 2, []
            while len(fields) < 3 and position < min(len(data), 512):
                byte = data[position]
                if byte == 35:
                    end = data.find(b'\n', position)
                    if end < 0: return None
                    position = end+1
                elif byte <= 32: position += 1
                elif 48 <= byte <= 57:
                    start = position
                    while position < len(data) and 48 <= data[position] <= 57 and position-start < 9: position += 1
                    fields.append(int(data[start:position]))
                else: return None
            if len(fields) != 3 or fields[2] not in (255, 65535): return None
            return fields[0], fields[1], 8 if fields[2] == 255 else 16, set()
        order = {b'II*\x00': '<', b'MM\x00*': '>'}.get(data[:4])
        if order is None: return None
        offset, = struct.unpack_from(order+'I', data, 4)
        count, = struct.unpack_from(order+'H', data, offset)
        if not 1 <= count <= 64: return None
        found = {}
        for index in range(count):
            tag, kind, number, value = struct.unpack_from(order+'HHII', data, offset+2+12*index)
            found[tag] = (kind, number, struct.unpack_from(order+('H' if kind == 3 else 'I'), data, offset+2+12*index+8)[0] if kind in (3, 4) else None)
        values = [found[tag][2] if tag in found and found[tag][1] == 1 and found[tag][0] in (3, 4) else None for tag in (256, 257, 258)]
        if None in values or values[2] not in (8, 16): return None
        return values[0], values[1], values[2], set(found)
    except (struct.error, IndexError):
        return None


def decode(prepared, captured):
    """Enforce series agreement and every aggregate budget from bounded headers, then decode without ImageJ."""
    if sum(len(data) for data in captured) > MAX_SERIES_BYTES:
        fail('RESOURCE_LIMIT', 'the series exceeds the %d MiB aggregate file budget' % (MAX_SERIES_BYTES >> 20), '$.frames',
             observedBytes=sum(len(data) for data in captured), maximumBytes=MAX_SERIES_BYTES)
    probes = []
    for index, (frame, data) in enumerate(zip(prepared['frames'], captured)):
        probe = header(data, frame['extension'])
        if probe is None:
            # The header is outside the cheap probe: this one image alone (already bounded to 16 MiB/1 MP) yields its precise fault.
            try: images.decode(data, frame['extension'])
            except SchemaxisError as error:
                fault = error.fault.to_dict()
                fail(fault['code'], fault['message'], f'$.frames[{index}].image', **(fault.get('observed') or {}))
            fail('INVALID_IMAGE', 'image header cannot be read', f'$.frames[{index}].image')
        if not (0 < probe[0] <= images.MAX_SIDE and 0 < probe[1] <= images.MAX_SIDE and probe[0]*probe[1] <= images.MAX_PIXELS):
            fail('RESOURCE_LIMIT', f'images are limited to {images.MAX_SIDE} pixels per side and {images.MAX_PIXELS} pixels',
                 f'$.frames[{index}].image', width=probe[0], height=probe[1])
        probes.append(probe)
    first = probes[0]
    for index, probe in enumerate(probes):
        if probe[:3] != first[:3]:
            fail('SERIES_MISMATCH', 'every frame needs the same width, height and bit depth', f'$.frames[{index}].image',
                 expected=list(first[:3]), observed=list(probe[:3]))
    pixels = first[0]*first[1]*len(probes)
    if pixels > MAX_SERIES_PIXELS:
        fail('RESOURCE_LIMIT', 'the series exceeds the %d pixel aggregate budget' % MAX_SERIES_PIXELS, '$.frames',
             observedPixels=pixels, maximumPixels=MAX_SERIES_PIXELS)
    visits = 0
    for index, region in enumerate(prepared['regions']):
        where = f'$.regions[{index}]'
        if region['x']+region['width'] > first[0] or region['y']+region['height'] > first[1]:
            fail('REGION_OUT_OF_BOUNDS', 'a rectangle must lie fully inside every frame (right and bottom edges are exclusive)', where,
                 region=[region['x'], region['y'], region['width'], region['height']], image=[first[0], first[1]])
        visits += region['width']*region['height']*len(probes)
    if visits > MAX_VISITS:
        fail('RESOURCE_LIMIT', 'rectangle pixel visits across the series exceed the %d budget' % MAX_VISITS, '$.regions',
             observedVisits=visits, maximumVisits=MAX_VISITS)
    decoded = []
    for index, (frame, data) in enumerate(zip(prepared['frames'], captured)):
        try:
            image = images.decode(data, frame['extension'])
        except SchemaxisError as error:
            fault = error.fault.to_dict()
            fail(fault['code'], fault['message'], f'$.frames[{index}].image', **(fault.get('observed') or {}))
        if (image['width'], image['height'], image['bitDepth']) != probes[index][:3]:
            fail('INVALID_IMAGE', 'decoded image differs from its header', f'$.frames[{index}].image')
        image['tags'] = probes[index][3]
        decoded.append(image)
    return decoded


def enumerate_region(image, region):
    """Exact integer count, sum, minimum and maximum over every pixel of the rectangle."""
    width, values = image['width'], image['values']
    total, low, high = 0, None, None
    for row in range(region['y'], region['y']+region['height']):
        chunk = values[row*width+region['x']: row*width+region['x']+region['width']]
        total += sum(chunk)
        low = min(chunk) if low is None else min(low, min(chunk))
        high = max(chunk) if high is None else max(high, max(chunk))
    return {'pixelCount': region['width']*region['height'], 'sum': total, 'minimum': low, 'maximum': high}


def oracle(prepared, decoded):
    return [[enumerate_region(image, region) for region in prepared['regions']] for image in decoded]


def specification(prepared):
    lines = ['frame %s %s %s %s' % (frame['id'], repr(float(frame['timeSeconds'])), frame['file'], frame['format'])
             for frame in prepared['frames']]
    lines += ['region %s %d %d %d %d' % (r['id'], r['x'], r['y'], r['width'], r['height']) for r in prepared['regions']]
    return '\n'.join(lines)+'\n'


def commands(java, jar, directory, prepared):
    calibration = prepared['calibration']
    base = [str(java), '-Djava.awt.headless=true', '-Dfile.encoding=UTF-8', '-Duser.language=en', '-Duser.country=CA',
            '-Duser.home='+str(directory/'imagej-home'), '-Djava.io.tmpdir='+str(directory/'imagej-home'),
            '-Dplugins.dir='+str(directory/'imagej-home'), '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC',
            '-Xmx768m', '-cp', str(jar), str(directory/NAME)]
    # Frame files are named relative to the working directory the fixed spec is read from.
    scale = [str(directory/'series.spec'), repr(float(calibration['pixelWidth'])), repr(float(calibration['pixelHeight'])), calibration['unit']]
    return {stage: base+[stage, *scale] for stage in STAGES}


# ------------------------------------------------------------------ retained evidence
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


def check(condition, message, location, **details):
    """A verification fault always names the retained file, field or row that failed."""
    if not condition: fail('VERIFICATION_FAILED', message, location, **details)


def near(actual, expected, scale=0.0):
    return math.isfinite(actual) and abs(actual-expected) <= 1e-12*max(abs(expected), scale)


def evidence_names(prepared):
    return [frame['file'] for frame in prepared['frames']]+[
        NAME, 'series.spec', 'runtime.json', 'java-version.stderr', 'measure-readback.txt', 'reopen-readback.txt',
        'native-measurements.csv', 'reopen-measurements.csv',
        *[stage+suffix for stage in ('java-version', *STAGES) for suffix in ('-submission.json', '.stdout', '.stderr')
          if stage+suffix != 'java-version.stderr']]


def readback(directory, name, prepared):
    lines = payload(directory, name).decode('utf-8').splitlines()
    pairs = [line.partition('=') for line in lines]
    count, regions = len(prepared['frames']), len(prepared['regions'])
    expected = [*READBACK_FIXED, *[f'frame.{i}.{field}' for i in range(count) for field in FRAME_FIELDS],
                *[f'label.{i}' for i in range(count)], *[f'region.{j}' for j in range(regions)]]
    if [key for key, _, _ in pairs] != expected or any(not separator for _, separator, _ in pairs):
        fail('VERIFICATION_FAILED', 'native readback fields differ from the fixed program contract', name)
    return {key: value for key, _, value in pairs}


def native_rows(directory, name, prepared, measured):
    """Parse native rows and check every one against the exact enumeration."""
    lines = payload(directory, name).decode('utf-8').splitlines()
    check(lines[:1] == [NATIVE_COLUMNS], 'native measurement columns differ', name)
    frames, regions = prepared['frames'], prepared['regions']
    check(len(lines)-1 == len(frames)*len(regions), 'native record count differs from frames x regions', name,
          native=len(lines)-1, expected=len(frames)*len(regions))
    width, height = prepared['calibration']['pixelWidth'], prepared['calibration']['pixelHeight']
    rows = []
    for position, text in enumerate(lines[1:]):
        frame, region = divmod(position, len(regions))
        fields = text.split(',')
        check(len(fields) == 11, 'native record has the wrong number of fields', f'{name}/rows/{position}')
        try:
            ids = [int(fields[0]), int(fields[1]), int(fields[6])]
            numbers = [float(value) for value in fields[2:6]+fields[7:]]
        except ValueError:
            fail('VERIFICATION_FAILED', 'native record holds a non-numeric field', f'{name}/rows/{position}')
        check(ids[:2] == [frame, region], 'native row identity or order differs from frame-major declaration order',
              f'{name}/rows/{position}', native=ids[:2], expected=[frame, region])
        x, y, w, h = (prepared['regions'][region][key] for key in ('x', 'y', 'width', 'height'))
        facts = measured[frame][region]
        count = facts['pixelCount']
        pair = {'X': (numbers[0], x*width), 'Y': (numbers[1], y*height), 'Width': (numbers[2], w*width), 'Height': (numbers[3], h*height),
                'Area': (numbers[4], float(Fraction(count)*Fraction(width)*Fraction(height))),
                'Mean': (numbers[5], float(Fraction(facts['sum'], count)))}
        check(ids[2] == count, 'native pixel count differs from the exact rectangle enumeration', f'{name}/rows/{position}/Count',
              native=ids[2], independent=count)
        for column, (actual, expected) in pair.items():
            check(near(actual, expected), 'native measurement differs from the independent enumeration',
                  f'{name}/rows/{position}/{column}', native=actual, independent=expected)
        check(numbers[6] == facts['minimum'] and numbers[7] == facts['maximum'], 'native minimum/maximum differ from the exact enumeration',
              f'{name}/rows/{position}', native=[numbers[6], numbers[7]], independent=[facts['minimum'], facts['maximum']])
        rows.append({'frame': frame, 'region': region, 'pixelCount': ids[2], 'area': numbers[4], 'mean': numbers[5],
                     'minimum': int(numbers[6]), 'maximum': int(numbers[7])})
    return rows


def csv_bytes(prepared, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(prepared['columns'])
    for row in rows:
        frame, region = prepared['frames'][row['frame']], prepared['regions'][row['region']]
        writer.writerow([frame['id'], region['id'], repr(float(frame['timeSeconds'])), row['pixelCount'], format(row['area'], '.17g'),
                         format(row['mean'], '.17g'), row['minimum'], row['maximum']])
    return out.getvalue().encode('utf-8')


def summary(prepared, decoded, rows, digests, versions):
    calibration = prepared['calibration']
    unit = calibration['unit']
    first = decoded[0]
    units = dict(zip(prepared['columns'], ['id', 'id', 's', 'pixels', unit+'^2', 'raw intensity', 'raw intensity', 'raw intensity']))
    return {'version': 'schemaxis.imagej.regions/1', 'operation': OPERATION,
            'runtime': {'name': 'ImageJ', 'version': versions['imagej'], 'java': versions['java']},
            'series': {'width': first['width'], 'height': first['height'], 'bitDepth': first['bitDepth'], 'frames': len(decoded)},
            'frames': [{'id': frame['id'], 'timeSeconds': frame['timeSeconds'], 'name': Path(frame['image']).name, 'file': frame['file'],
                        'format': image['format'], 'byteOrder': image['byteOrder'], 'sha256': digests[frame['file']]}
                       for frame, image in zip(prepared['frames'], decoded)],
            'regions': [{**region, 'pixels': region['width']*region['height'],
                         'area': region['width']*region['height']*prepared['pixelArea']} for region in prepared['regions']],
            'calibration': {'pixelWidth': calibration['pixelWidth'], 'pixelHeight': calibration['pixelHeight'], 'unit': unit,
                            'nativeUnit': prepared['nativeUnit'], 'pixelArea': prepared['pixelArea'], 'areaUnit': unit+'^2',
                            'coordinates': COORDINATES},
            'timeConvention': TIME_CONVENTION, 'overlap': OVERLAP,
            'records': [{'frame': prepared['frames'][row['frame']]['id'], 'region': prepared['regions'][row['region']]['id'],
                         'timeSeconds': prepared['frames'][row['frame']]['timeSeconds'], 'pixelCount': row['pixelCount'],
                         'area': row['area'], 'meanIntensity': row['mean'], 'minimumIntensity': row['minimum'],
                         'maximumIntensity': row['maximum']} for row in rows],
            'columns': prepared['columns'], 'units': units, 'csvSha256': digests['csv'],
            'overlay': 'omitted: no review image is produced and no editable ROI set is claimed',
            'verification': 'Native ImageStatistics rows for every rectangle and frame, and a fresh-process ImagePlus/Roi readback, match an '
                            'independent exact enumeration of the source pixels (integer count, minimum, maximum and Fraction mean; area, geometry within 1e-12 relative).',
            'losses': LOSSES}


def manifest(directory):
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in PUBLICATIONS]


def java_identity(text):
    found = re.search(r'version "(\d+)(?:\.(\d+))?[^"]*"', text)
    major = int(found[1]) if found and found[1] != '1' else int(found[2]) if found and found[2] else 0
    if major < 11:
        fail('UNSUPPORTED_RUNTIME', 'the fixed ImageJ program needs a Java 11 or newer runtime with the jdk.compiler module', 'java-version.stderr')
    return major


def runtime_identity(text):
    if not re.fullmatch(r'1\.54[a-z]\d*', text or ''): fail('UNSUPPORTED_RUNTIME', 'expected an ImageJ 1.54 release (ij.jar); observed '+repr(text))
    return text


# ------------------------------------------------------------------ run and verify
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
        captured = capture_series(prepared)
        decoded = decode(prepared, captured)   # every refusal precedes native assignment
        measured = oracle(prepared, decoded)
        for frame, data in zip(prepared['frames'], captured): (directory/frame['file']).write_bytes(data)
        (directory/NAME).write_text(PROGRAM, encoding='utf-8')
        (directory/'series.spec').write_text(specification(prepared), encoding='utf-8')
        (directory/'imagej-home').mkdir()
        atomic_json(directory/'runtime.json', {'name': 'ImageJ', 'java': str(executable), 'jar': str(jar),
                                                'jarSha256': hashlib.sha256(Path(jar).read_bytes()).hexdigest()})
        environment = {'LC_ALL': 'C', 'JAVA_TOOL_OPTIONS': '', '_JAVA_OPTIONS': '', 'JDK_JAVA_OPTIONS': ''}
        execute([executable, '-version'], directory, 'java-version', deadline-time.monotonic(), environment)
        java_identity(payload(directory, 'java-version.stderr').decode('utf-8', 'replace'))
        native = commands(executable, jar, directory, prepared)
        for stage in STAGES:
            if cancellation_requested(): fail('RUNNER_CANCELLED', 'region measurement cancelled before the '+stage+' stage', stage)
            execute(native[stage], directory, stage, deadline-time.monotonic(), environment)
        rows = native_rows(directory, 'native-measurements.csv', prepared, measured)
        values = readback(directory, 'measure-readback.txt', prepared)
        versions = {'imagej': runtime_identity(values['imagej']), 'java': values['java']}
        (directory/PUBLICATIONS[0][0]).write_bytes(csv_bytes(prepared, rows))
        digests = {frame['file']: hashlib.sha256(data).hexdigest() for frame, data in zip(prepared['frames'], captured)}
        digests['csv'] = digest(directory, PUBLICATIONS[0][0])
        atomic_json(directory/PUBLICATIONS[1][0], summary(prepared, decoded, rows, digests, versions))
        atomic_json(directory/'verification.json', {'artifacts': manifest(directory), 'runtime': versions,
                                                    'evidence': {name: digest(directory, name) for name in evidence_names(prepared)}})
        result = verify(directory, require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'region publication cancelled', 'verification.json')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'region verification exhausted the total timeout', 'verification.json')
        result.update(status='succeeded'); atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error), str(directory))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        prepared = plan(read_json(directory, 'authored.json'))
        check(read_json(directory, 'plan.json') == json.loads(json.dumps(prepared)), 'effective plan differs from authored region measurement', 'plan.json')
        if require_result:
            result = read_json(directory, 'result.json')
            if result.get('status') != 'succeeded' or result.get('verified') is not True:
                fail('INCOMPLETE_EXECUTION', 'region measurement did not complete', 'result.json')
        check(payload(directory, NAME).decode('utf-8') == PROGRAM, 'trusted fixed ImageJ program differs', NAME)
        check(payload(directory, 'series.spec').decode('utf-8') == specification(prepared), 'series specification differs from the authored frames and regions', 'series.spec')
        captured = [payload(directory, frame['file'], images.MAX_FILE_BYTES) for frame in prepared['frames']]
        decoded = decode(prepared, captured)
        measured = oracle(prepared, decoded)
        runtime = read_json(directory, 'runtime.json')
        check(set(runtime) == {'name', 'java', 'jar', 'jarSha256'} and Path(runtime['java']).is_absolute()
              and Path(runtime['jar']).is_absolute(), 'native runtime record differs', 'runtime.json')
        java_identity(payload(directory, 'java-version.stderr').decode('utf-8', 'replace'))
        native = commands(runtime['java'], runtime['jar'], directory, prepared)
        for stage in ('java-version', *STAGES):
            submission = read_json(directory, stage+'-submission.json')
            expected = [runtime['java'], '-version'] if stage == 'java-version' else native[stage]
            check(submission.get('nativeCommand') == expected and type(submission.get('exitCode')) is int
                  and submission['exitCode'] == 0, 'native command or completion differs', stage+'-submission.json')
        calibration = prepared['calibration']
        unit = ','.join(str(ord(char)) for char in prepared['nativeUnit'])
        observed = {}
        for stage in STAGES:
            values = observed[stage] = readback(directory, stage+'-readback.txt', prepared)
            where = stage+'-readback.txt'
            check(values['stage'] == stage and values['frames'] == str(len(decoded)) and values['regions'] == str(len(prepared['regions']))
                  and values['stackSize'] == str(len(decoded)), 'native stage saw a different series shape', where)
            check(values['jarSha256'] == runtime['jarSha256'],
                  'the ImageJ jar the native process loaded differs from the jarSha256 recorded in runtime.json', where+'/jarSha256')
            check(float(values['pixelWidth']) == calibration['pixelWidth'] and float(values['pixelHeight']) == calibration['pixelHeight']
                  and values['unit'] == unit and values['yUnit'] == unit and values['origin'] == '0.0,0.0',
                  'native calibration readback differs from the declared calibration', where)
            for index, (frame, image, data) in enumerate(zip(prepared['frames'], decoded, captured)):
                prefix = f'frame.{index}.'
                check(values[prefix+'sha256'] == hashlib.sha256(data).hexdigest(), 'native stage consumed different frame bytes', f'{where}/{prefix}sha256')
                check([values[prefix+key] for key in ('width', 'height', 'bitDepth', 'stackSize')]
                      == [str(image['width']), str(image['height']), str(image['bitDepth']), '1'],
                      'ImageJ decoded different frame dimensions, depth or plane count', f'{where}/{prefix[:-1]}')
                if not image['tags'] & {270, 282, 283, 296}:
                    # No resolution or description metadata exists in the file, so ImageJ must report its uncalibrated default.
                    check(values[prefix+'fileCalibration'] == '1.0,1.0,112,105,120,101,108',
                          'ImageJ reports a calibration stored in a file that carries none', f'{where}/{prefix}fileCalibration')
                if values[prefix+'densityCalibrated'] != 'false' or values[prefix+'invertedLut'] != 'false':
                    fail('UNSUPPORTED_IMAGE', 'ImageJ reports density calibration or an inverted lookup table; supply plain raw intensities',
                         f'$.frames[{index}].image')
                check(values[f'label.{index}'] == frame['id'], 'native frame label differs from the declared frame identifier in the '+stage+' stage',
                      f'{where}/label.{index}', native=values[f'label.{index}'], declared=frame['id'])
            for index, region in enumerate(prepared['regions']):
                expected = f"{region['id']},{region['x']},{region['y']},{region['width']},{region['height']},Rectangle"
                check(values[f'region.{index}'] == expected, 'native rectangle readback differs from the declared region in the '+stage+' stage',
                      f'{where}/region.{index}', native=values[f'region.{index}'], declared=expected)
        versions = {'imagej': runtime_identity(observed['measure']['imagej']), 'java': observed['measure']['java']}
        check(observed['reopen']['imagej'] == versions['imagej'] and observed['reopen']['java'] == versions['java'],
              'fresh native process used a different runtime', 'reopen-readback.txt')
        for index in range(len(decoded)):
            key = f'frame.{index}.fileCalibration'
            check(observed['measure'][key] == observed['reopen'][key],
                  'the stored-file calibration ImageJ recorded differs between the measure and reopen stages', f'reopen-readback.txt/{key}')
        rows = native_rows(directory, 'native-measurements.csv', prepared, measured)
        reopened = native_rows(directory, 'reopen-measurements.csv', prepared, measured)
        for index, (row, other) in enumerate(zip(rows, reopened)):
            check(all(near(row[key], other[key]) for key in ('area', 'mean')) and all(row[key] == other[key] for key in ('pixelCount', 'minimum', 'maximum')),
                  'fresh ImagePlus/Roi readback differs from the first native measurement', f'reopen-measurements.csv/rows/{index}')
        check(payload(directory, PUBLICATIONS[0][0]) == csv_bytes(prepared, rows), 'published region table differs from verified native measurements', PUBLICATIONS[0][0])
        digests = {frame['file']: hashlib.sha256(data).hexdigest() for frame, data in zip(prepared['frames'], captured)}
        digests['csv'] = digest(directory, PUBLICATIONS[0][0])
        details = summary(prepared, decoded, rows, digests, versions)
        check(read_json(directory, PUBLICATIONS[1][0]) == json.loads(json.dumps(details)), 'summary differs from independently checked measurements', PUBLICATIONS[1][0])
        receipt = read_json(directory, 'verification.json')
        check(set(receipt) == {'artifacts', 'runtime', 'evidence'}, 'verification receipt has unexpected fields', 'verification.json')
        check(receipt['artifacts'] == manifest(directory), 'verification receipt publication membership or digests differ from the retained publications',
              'verification.json/artifacts')
        check(receipt['runtime'] == versions, 'verification receipt runtime differs from the native readback', 'verification.json/runtime')
        recorded = receipt['evidence']
        check(isinstance(recorded, dict) and sorted(recorded) == sorted(evidence_names(prepared)), 'verification receipt evidence membership differs', 'verification.json/evidence')
        for name in evidence_names(prepared):
            check(recorded[name] == digest(directory, name), 'retained evidence digest differs from the verification receipt', f'verification.json/evidence/{name}')
        return {'verified': True, 'artifacts': len(PUBLICATIONS), 'runtime': versions, 'operation': OPERATION,
                'frames': len(decoded), 'regions': len(prepared['regions']), 'records': len(rows)}
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError, OverflowError) as error:
        fail('VERIFICATION_FAILED', 'missing or invalid region evidence: '+str(error), str(directory))
