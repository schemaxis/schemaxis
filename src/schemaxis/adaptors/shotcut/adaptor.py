# Copyright (C) 2026 David L F Gaden
"""Named video assets and frame-exact cuts published through Shotcut's MLT engine."""
import hashlib
import json
import math
import os
from fractions import Fraction
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.shotcut/1'
MAX_BYTES = 192 * 1024 * 1024
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 64, 'required': True}
OPTIONS = {
    'assets': {'type': 'array', 'minItems': 1, 'maxItems': 16, 'required': True,
               'items': {'type': 'object', 'properties': {
                   'name': NAME, 'file': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}}}},
    'clips': {'type': 'array', 'minItems': 1, 'maxItems': 128, 'required': True,
              'items': {'type': 'object', 'properties': {
                  'asset': NAME, 'startFrame': {'type': 'integer', 'minimum': 0, 'maximum': 599, 'default': 0},
                  'frameCount': {'type': 'integer', 'minimum': 1, 'maximum': 600, 'required': True}}}},
    'fps': {'type': 'integer', 'minimum': 1, 'maximum': 120, 'default': 25},
    'width': {'type': 'integer', 'minimum': 2, 'maximum': 4096, 'default': 1280},
    'height': {'type': 'integer', 'minimum': 2, 'maximum': 4096, 'default': 720},
    'threads': {'type': 'integer', 'minimum': 1, 'maximum': 16, 'default': 1},
}
DECLARATIONS = {'editTimeline': {'native': 'Shotcut MLT XML playlist', 'kinds': ['video', 'videoProject', 'videoProjectBundle'],
                                'inputs': {}, 'options': {key: {'value': value} for key, value in OPTIONS.items()}}}
LOSSES = ['Silent one-track cuts only; audio, subtitles, rotation, resizing and frame interpolation are unsupported',
          'Source frame rate and dimensions must match the declared timeline; progressive square pixels only',
          'MLT colour conversion is checked at mean RGB error <=3/255 and maximum channel error <=8/255 per frame',
          'FFV1 publication preserves MLT RGB output; no perceptual or colour-management certification']


def plan(document):
    keys(document, ('version', 'nodes'), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or len(nodes) != 1: fail('INVALID_DOCUMENT', 'declare exactly one timeline', '$.nodes')
    node = nodes[0]
    keys(node, ('id', 'filter', 'options'), '$.nodes[0]')
    from schemaxis.pipeline import name
    identity = name(node.get('id'), '$.nodes[0].id')
    if node.get('filter') != 'editTimeline': fail('UNKNOWN_FILTER', 'select editTimeline', '$.nodes[0].filter')
    options = validate_arguments(OPTIONS, node.get('options', {}), location='$.nodes[0].options')
    names = set()
    for index, asset in enumerate(options['assets']):
        at = '$.nodes[0].options.assets[' + str(index) + ']'
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', asset['name']) or asset['name'] in names:
            fail('INVALID_ASSET', 'asset names must be unique bounded identifiers', at + '.name')
        names.add(asset['name'])
        if '\x00' in asset['file'] or not Path(asset['file']).is_absolute(): fail('INVALID_RESOURCE', 'asset paths must be absolute and contain no NUL', at + '.file')
    total = 0
    segments = []
    used = set()
    for index, clip in enumerate(options['clips']):
        at = '$.nodes[0].options.clips[' + str(index) + ']'
        if clip['asset'] not in names: fail('INVALID_SELECTION', 'clip names an undeclared asset', at + '.asset')
        if clip['startFrame'] + clip['frameCount'] > 600: fail('INVALID_RANGE', 'source range exceeds 600-frame bound', at)
        segments.append({**clip, 'timelineStart': total})
        used.add(clip['asset'])
        total += clip['frameCount']
    if total > 600 or total * options['width'] * options['height'] * 3 > MAX_BYTES:
        fail('RESOURCE_LIMIT', 'timeline exceeds 600 frames or 192 MiB decoded RGB', '$.nodes[0].options.clips')
    if used != names: fail('INVALID_ASSET', 'remove unused assets from the timeline', '$.nodes[0].options.assets')
    return {'version': 'schemaxis.shotcut.plan/1', 'nodes': [{'id': identity, 'filter': 'editTimeline', 'options': options}],
            'segments': segments, 'frames': total, 'duration': total / options['fps'], 'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, NAME as ID, argument_schema, object_schema
    options = {key: argument_schema(spec) for key, spec in OPTIONS.items()}
    descriptions = {
        'assets': 'Named local video files retained beside the editable project; use absolute paths.',
        'clips': 'Timeline order. Each clip selects a contiguous source range at the declared frame rate.',
        'fps': 'Integer frames per second; every source must have this constant rate. Default 25.',
        'width': 'Timeline and source width in pixels; no resizing. Default 1280.',
        'height': 'Timeline and source height in pixels; no resizing. Default 720.',
        'threads': 'Native decoding/rendering thread allocation; 1 to 16, default 1.',
    }
    for key, value in options.items(): value['description'] = descriptions[key]
    for key, explanation in {
        'name': 'Unique asset identifier used by clips; letters, digits, underscores or hyphens.',
        'file': 'Absolute local video file path; execution copies and probes the bytes.',
    }.items(): options['assets']['items']['properties'][key]['description'] = explanation
    for key, explanation in {
        'asset': 'Name of a declared video asset. Repeating an asset repeats selected source frames.',
        'startFrame': 'Zero-based source frame index. Default 0; no seconds-to-frames rounding.',
        'frameCount': 'Number of consecutive source frames. End is startFrame + frameCount, exclusive.',
    }.items(): options['clips']['items']['properties'][key]['description'] = explanation
    return {'$schema': DRAFT, **object_schema({
        'version': {'const': VERSION, 'description': 'Shotcut timeline document contract.'},
        'nodes': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'description': 'One declared timeline publication.',
                  'items': object_schema({'id': {**ID, 'description': 'Publication identity within the workflow.'},
                      'filter': {'const': 'editTimeline', 'description': 'Trim and arrange named video ranges.'},
                      'options': object_schema(options, ['assets', 'clips'])}, ['id', 'filter', 'options'])}}, ['version', 'nodes'])}


def reusableInputs(document):
    options = plan(document)['nodes'][0]['options']
    total = 0
    result = {}
    for asset in options['assets']:
        data = _source_bytes(asset['file'])
        total += len(data)
        if total > MAX_BYTES: fail('RESOURCE_LIMIT', 'encoded source byte budget exceeded')
        result[asset['file']] = hashlib.sha256(data).hexdigest()
    return result


def _source_bytes(filename):
    try:
        if not stat.S_ISREG(Path(filename).stat().st_mode):
            fail('INVALID_RESOURCE', 'video source must be a regular file', filename)
        descriptor = os.open(filename, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                fail('INVALID_RESOURCE', 'video source must be a regular file', filename)
            if os.fstat(stream.fileno()).st_size > MAX_BYTES:
                fail('RESOURCE_LIMIT', 'encoded source byte budget exceeded', filename)
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: fail('RESOURCE_LIMIT', 'encoded source byte budget exceeded', filename)
        return data
    except (OSError, ValueError) as error: fail('RESOURCE_NOT_FOUND', str(error), filename)


def studioCatalogue(schema):
    return [{'id': 'operation:editTimeline', 'operation': 'editTimeline',
             'title': 'Trim and arrange video clips', 'group': 'sources', 'at': '/nodes/-',
             'schema': schema['properties']['nodes']['items'],
             'description': 'Trim, reorder and repeat named source ranges in a verified editable timeline.',
             'ports': {}, 'bindings': DECLARATIONS['editTimeline']['options']}]


def provisionalResources(document, execution, identity):
    try: threads = document['nodes'][0].get('options', {}).get('threads', 1)
    except (KeyError, IndexError, TypeError, AttributeError):
        fail('INVALID_DOCUMENT', 'declare one timeline node', identity)
    if type(threads) is not int or not 1 <= threads <= 16:
        fail('INVALID_EXECUTION', 'timeline threads must be an integer in [1,16]', identity)
    if execution.get('threads', threads) != threads: fail('INVALID_EXECUTION', 'allocation must match timeline threads', identity)
    return {'threads': threads}


def resources(document, execution, identity):
    plan(document)
    return provisionalResources(document, execution, identity)


def _regular(directory, filename, limit=MAX_BYTES):
    path = directory / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        fail('VERIFICATION_FAILED', 'required bounded regular file is absent or invalid', filename)
    return path


def _read(directory, filename):
    return json.loads(_regular(directory, filename, 4 * 1024 * 1024).read_text())


def _probe(probe, options, count=None):
    try:
        streams = probe['streams']
        if len(streams) != 1 or streams[0]['codec_type'] != 'video': raise ValueError('exactly one silent video stream is required')
        stream = streams[0]
        frames = int(stream['nb_read_frames'])
        if not 1 <= frames <= 600 or (count is not None and frames != count): raise ValueError('frame count differs or exceeds bound')
        if stream['width'] != options['width'] or stream['height'] != options['height']: raise ValueError('source/timeline dimensions differ')
        if Fraction(stream['avg_frame_rate']) != options['fps'] or Fraction(stream['r_frame_rate']) != options['fps']:
            raise ValueError('source/timeline frame rate differs')
        if stream.get('field_order', 'progressive') not in ('progressive', 'unknown'): raise ValueError('interlaced sources are unsupported')
        if stream.get('sample_aspect_ratio', '1:1') not in ('1:1', 'N/A', '0:1'): raise ValueError('non-square source pixels are unsupported')
        if any('rotation' in side and float(side['rotation']) != 0 for side in stream.get('side_data_list', [])):
            raise ValueError('rotated video is unsupported')
        if not math.isclose(float(probe['format']['duration']), frames / options['fps'], rel_tol=0, abs_tol=0.002):
            raise ValueError('source/timeline duration differs')
        # ffprobe observed frame timestamps independently reject VFR/gaps even
        # when a container advertises the requested average frame rate.
        observed = [f for f in probe['frames'] if f.get('media_type') == 'video']
        if len(observed) != frames: raise ValueError('missing decoded frame timestamps')
        if any(type(f.get('interlaced_frame')) is not int or f['interlaced_frame'] != 0 for f in observed):
            raise ValueError('every decoded source frame must explicitly be progressive')
        times = [float(f['best_effort_timestamp_time']) for f in observed]
        if not math.isclose(times[0], 0, abs_tol=0.002): raise ValueError('source must start at zero')
        if any(not math.isclose(t, i / options['fps'], rel_tol=0, abs_tol=0.002) for i, t in enumerate(times)):
            raise ValueError('variable frame timing is unsupported')
        if count is not None and stream['codec_name'] != 'ffv1': raise ValueError('publication codec must be FFV1')
        return frames
    except (KeyError, ValueError, TypeError, AttributeError, ZeroDivisionError, OverflowError) as error:
        fail('INVALID_MEDIA' if count is None else 'VERIFICATION_FAILED', str(error))


def _check_range(index, clip, frames):
    # Source frame counts are native observations, so only execution can know
    # whether an otherwise valid range lies inside the retained source.
    end = clip['startFrame'] + clip['frameCount']
    if end > frames:
        fail('INVALID_RANGE', 'clip selects frames beyond the end of its source; shorten the range or choose a longer source',
             '$.nodes[0].options.clips[' + str(index) + ']', asset=clip['asset'], startFrame=clip['startFrame'],
             frameCount=clip['frameCount'], requestedEnd=end, sourceFrames=frames)


def _expected(directory, prepared):
    options = prepared['nodes'][0]['options']
    chunk = options['width'] * options['height'] * 3
    sources = []
    frames = {}
    size = 0
    for index, asset in enumerate(options['assets']):
        retained = f'asset-{index:02d}.media'
        file = _regular(directory, retained)
        probe = _read(directory, f'asset-{index:02d}-probe.stdout')
        count = _probe(probe, options)
        raw = _regular(directory, f'asset-{index:02d}.rgb').read_bytes()
        size += len(raw)
        if len(raw) != count * chunk or size > MAX_BYTES: fail('RESOURCE_LIMIT', 'source decode size differs or exceeds budget')
        frames[asset['name']] = raw
        sources.append({'name': asset['name'], 'file': asset['file'], 'retained': retained,
                        'sha256': file_digest(file), 'decodedSHA256': hashlib.sha256(raw).hexdigest(), 'frames': count})
    expected = bytearray()
    for index, clip in enumerate(options['clips']):
        start, end = clip['startFrame'] * chunk, (clip['startFrame'] + clip['frameCount']) * chunk
        source = frames[clip['asset']]
        _check_range(index, clip, len(source) // chunk)
        expected.extend(source[start:end])
    return sources, bytes(expected)


def project(prepared, directory):
    options = prepared['nodes'][0]['options']
    root = ET.Element('mlt', {'producer': 'tractor', 'LC_NUMERIC': 'C'})
    divisor = math.gcd(options['width'], options['height'])
    ET.SubElement(root, 'profile', {'description': 'Schemaxis Shotcut timeline', 'width': str(options['width']),
        'height': str(options['height']), 'frame_rate_num': str(options['fps']), 'frame_rate_den': '1',
        'progressive': '1', 'sample_aspect_num': '1', 'sample_aspect_den': '1',
        'display_aspect_num': str(options['width'] // divisor), 'display_aspect_den': str(options['height'] // divisor), 'colorspace': '709'})
    def property(element, name, value): ET.SubElement(element, 'property', {'name': name}).text = str(value)
    for index, asset in enumerate(options['assets']):
        producer = ET.SubElement(root, 'producer', {'id': 'asset-' + asset['name']})
        property(producer, 'resource', f'asset-{index:02d}.media')
        property(producer, 'mlt_service', 'avformat')
        property(producer, 'audio_index', -1)
        property(producer, 'video_index', 0)
        property(producer, 'threads', options['threads'])
        property(producer, 'shotcut:caption', asset['name'])
    black = ET.SubElement(root, 'producer', {'id': 'black', 'in': '0', 'out': str(prepared['frames'] - 1)})
    property(black, 'resource', '#000000')
    property(black, 'mlt_service', 'color')
    background = ET.SubElement(root, 'playlist', {'id': 'background'})
    ET.SubElement(background, 'entry', {'producer': 'black', 'in': '0', 'out': str(prepared['frames'] - 1)})
    timeline = ET.SubElement(root, 'playlist', {'id': 'timeline'})
    property(timeline, 'shotcut:name', 'V1')
    property(timeline, 'shotcut:video', 1)
    for clip in options['clips']:
        ET.SubElement(timeline, 'entry', {'producer': 'asset-' + clip['asset'], 'in': str(clip['startFrame']),
                                        'out': str(clip['startFrame'] + clip['frameCount'] - 1)})
    tractor = ET.SubElement(root, 'tractor', {'id': 'tractor', 'in': '0', 'out': str(prepared['frames'] - 1)})
    property(tractor, 'shotcut', 1)
    ET.SubElement(tractor, 'track', {'producer': 'background'})
    ET.SubElement(tractor, 'track', {'producer': 'timeline', 'hide': 'audio'})
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def _reopened(directory, prepared):
    path = _regular(directory, 'reopened.mlt', 4 * 1024 * 1024)
    root = ET.fromstring(path.read_bytes())
    wanted = ET.fromstring(project(prepared, directory))
    if root.find('profile').attrib != wanted.find('profile').attrib: fail('VERIFICATION_FAILED', 'native reloaded timeline profile differs')
    timeline = root.find("playlist[@id='timeline']")
    expected = wanted.find("playlist[@id='timeline']")
    if timeline is None or [e.attrib for e in timeline.findall('entry')] != [e.attrib for e in expected.findall('entry')]:
        fail('VERIFICATION_FAILED', 'native reloaded source ranges/order differ')
    for index, asset in enumerate(prepared['nodes'][0]['options']['assets']):
        producer = root.find("producer[@id='asset-" + asset['name'] + "']")
        if producer is None: fail('VERIFICATION_FAILED', 'native reloaded asset is absent')
        properties = {item.get('name'): item.text for item in producer.findall('property')}
        if properties.get('mlt_service') != 'avformat' or properties.get('resource') != f'asset-{index:02d}.media':
            fail('VERIFICATION_FAILED', 'native reloaded asset source differs')
    return file_digest(path)


def _compare(expected, actual, chunk):
    if len(expected) != len(actual): fail('VERIFICATION_FAILED', 'decoded timeline frame count/dimensions differ')
    errors = []
    for offset in range(0, len(expected), chunk):
        differences = [abs(a - b) for a, b in zip(expected[offset:offset + chunk], actual[offset:offset + chunk])]
        mean, maximum = sum(differences) / chunk, max(differences)
        if mean > 3 or maximum > 8: fail('VERIFICATION_FAILED', 'rendered timeline pixels/order differ', meanError=mean, maximumError=maximum)
        errors.append({'mean': mean, 'maximum': maximum})
    return errors


def _bundle_names(prepared):
    return ['project.mlt'] + [f'asset-{index:02d}.media' for index in range(len(prepared['nodes'][0]['options']['assets']))]


def _write_bundle(directory, prepared):
    # A fixed stored layout keeps the native handoff deterministic and readable
    # without extracting or trusting arbitrary external archive members.
    with zipfile.ZipFile(directory / 'project-bundle.zip', 'w', compression=zipfile.ZIP_STORED) as archive:
        for filename in _bundle_names(prepared):
            info = zipfile.ZipInfo(filename, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, _regular(directory, filename).read_bytes())


def _check_bundle(directory, prepared):
    path = _regular(directory, 'project-bundle.zip', MAX_BYTES + 1024 * 1024)
    with zipfile.ZipFile(path) as archive:
        names = _bundle_names(prepared)
        entries = archive.infolist()
        if [entry.filename for entry in entries] != names:
            fail('VERIFICATION_FAILED', 'project bundle membership/order differs')
        total = 0
        local_offset = central_size = 0
        for entry in entries:
            if (entry.compress_type != zipfile.ZIP_STORED or entry.date_time != (1980, 1, 1, 0, 0, 0)
                    or entry.create_system != 3 or entry.external_attr != 0o100644 << 16
                    or entry.file_size > MAX_BYTES or entry.filename != Path(entry.filename).name
                    or entry.flag_bits != 0 or entry.header_offset != local_offset):
                fail('VERIFICATION_FAILED', 'project bundle member layout differs', entry.filename)
            name_bytes = len(entry.filename.encode('utf-8'))
            local_offset += 30 + name_bytes + entry.file_size
            central_size += 46 + name_bytes
            total += entry.file_size
            if total > MAX_BYTES + 1024 * 1024: fail('VERIFICATION_FAILED', 'project bundle exceeds byte budget')
            with archive.open(entry) as stream: data = stream.read(MAX_BYTES + 1)
            if data != _regular(directory, entry.filename).read_bytes():
                fail('VERIFICATION_FAILED', 'project bundle member differs from captured publication', entry.filename)
        if archive.comment or any(entry.comment or entry.extra for entry in entries):
            fail('VERIFICATION_FAILED', 'project bundle metadata differs')
        if archive.start_dir != local_offset or path.stat().st_size != local_offset + central_size + 22:
            fail('VERIFICATION_FAILED', 'project bundle contains extra or missing bytes')
    return file_digest(path)


def _tools(executable):
    executable = executable or os.environ.get('SHOTCUT_MELT_EXECUTABLE') or shutil.which('melt')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'provide absolute Shotcut-bundled melt executable')
    directory = Path(executable).parent
    ffmpeg, probe = directory / 'ffmpeg', directory / 'ffprobe'
    if not all(os.access(path, os.X_OK) for path in (ffmpeg, probe)):
        fail('INTERPRETER_NOT_FOUND', 'matching FFmpeg/FFprobe must be beside Shotcut melt')
    return str(executable), str(ffmpeg), str(probe)


def _commands(directory, prepared, melt, ffmpeg, probe):
    options = prepared['nodes'][0]['options']
    commands = {}
    for index, asset in enumerate(options['assets']):
        media = directory / f'asset-{index:02d}.media'
        commands[f'asset-{index:02d}-probe'] = [probe, '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-show_frames', '-of', 'json', str(media)]
        commands[f'asset-{index:02d}-decode'] = [ffmpeg, '-nostdin', '-v', 'error', '-y', '-threads', str(options['threads']), '-i', str(media),
            '-map', '0:v:0', '-an', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(directory / f'asset-{index:02d}.rgb')]
    commands['reopen'] = [melt, str(directory / 'project.mlt'), '-consumer', 'xml:' + str(directory / 'reopened.mlt'), 'store=shotcut', 'time_format=frames']
    render = ['vcodec=ffv1', 'pix_fmt=bgr0', 'level=1', 'an=1', 'threads=' + str(options['threads']), 'real_time=-1', 'terminate_on_pause=1']
    commands['render'] = [melt, str(directory / 'project.mlt'), '-consumer', 'avformat:' + str(directory / 'video.mkv')] + render
    commands['rerender'] = [melt, str(directory / 'reopened.mlt'), '-consumer', 'avformat:' + str(directory / 'reopened-video.mkv')] + render
    for basename in ('video', 'reopened-video'):
        commands[basename + '-decode'] = [ffmpeg, '-nostdin', '-v', 'error', '-y', '-threads', str(options['threads']), '-i', str(directory / (basename + '.mkv')),
            '-map', '0:v:0', '-an', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(directory / (basename + '.rgb'))]
        commands[basename + '-probe'] = [probe, '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-show_frames', '-of', 'json', str(directory / (basename + '.mkv'))]
    commands['version'] = [melt, '-version']
    commands['ffmpeg-version'] = [ffmpeg, '-version']
    return commands


def _stage_inputs(directory, prepared, stage):
    media = [directory / f'asset-{i:02d}.media' for i in range(len(prepared['nodes'][0]['options']['assets']))]
    if stage.startswith('asset-'):
        return [directory / (stage[:8] + '.media')]
    if stage in ('reopen', 'render'): return [directory / 'project.mlt'] + media
    if stage == 'rerender': return [directory / 'reopened.mlt'] + media
    if stage.startswith('reopened-video-'): return [directory / 'reopened-video.mkv']
    if stage.startswith('video-'): return [directory / 'video.mkv']
    return []


def _launcher(directory, prepared, stage, command):
    # Bind native readback to the input bytes consumed by that owned process.
    # This is ordinary evidence integrity, not an all-evidence-forgery defence.
    paths = [str(path) for path in _stage_inputs(directory, prepared, stage)]
    return ('import hashlib, json, os, stat\nfrom pathlib import Path\n'
            + f'paths = {paths!r}\ncommand = {command!r}\n'
            + 'digests = {}\nfor filename in paths:\n'
            + '    path = Path(filename)\n'
            + '    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode): raise ValueError("native input is not regular")\n'
            + '    digest = hashlib.sha256()\n'
            + '    with path.open("rb") as stream:\n'
            + '        for block in iter(lambda: stream.read(1048576), b""): digest.update(block)\n'
            + '    digests[filename] = digest.hexdigest()\n'
            + f'Path({str(directory / (stage + "-inputs.json"))!r}).write_text(json.dumps(digests, sort_keys=True))\n'
            + 'os.execvpe(command[0], command, os.environ)\n')


def _result(directory):
    return {'status': 'succeeded', 'verified': True, 'artifacts': 3, 'video': str(directory / 'video.mkv'),
            'project': str(directory / 'project.mlt'), 'projectBundle': str(directory / 'project-bundle.zip')}


def _check_result(directory, result):
    # The result is the handoff other operations read; it must name exactly the
    # three verified publications of this run directory, not merely say "succeeded".
    expected = _result(directory)
    if (not isinstance(result, dict) or any(key not in result or type(result[key]) is not type(value) or result[key] != value
            for key, value in expected.items()) or 'fault' in result or 'verificationFault' in result):
        fail('VERIFICATION_FAILED', 'result publication membership differs from the verified video, project and project bundle',
             str(directory / 'result.json'))


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    options = prepared['nodes'][0]['options']
    melt, ffmpeg, probe = _tools(executable)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'choose a fresh directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    deadline = time.monotonic() + timeout
    commands = _commands(directory, prepared, melt, ffmpeg, probe)
    def stage(name, environment=None):
        launcher = directory / (name + '-launcher.py')
        launcher.write_text(_launcher(directory, prepared, name, commands[name]))
        execute([sys.executable, str(launcher)], directory, name, deadline - time.monotonic(), environment)
    try:
        size = decoded_size = 0
        for index, asset in enumerate(options['assets']):
            data = _source_bytes(asset['file'])
            size += len(data)
            if size > MAX_BYTES: fail('RESOURCE_LIMIT', 'encoded source byte budget exceeded')
            media = directory / f'asset-{index:02d}.media'
            media.write_bytes(data)
            stage(f'asset-{index:02d}-probe')
            count = _probe(_read(directory, f'asset-{index:02d}-probe.stdout'), options)
            for position, clip in enumerate(options['clips']):
                if clip['asset'] == asset['name']: _check_range(position, clip, count)
            decoded_size += count * options['width'] * options['height'] * 3
            if decoded_size > MAX_BYTES: fail('RESOURCE_LIMIT', 'cumulative decoded assets exceed budget')
            stage(f'asset-{index:02d}-decode')
        sources, expected = _expected(directory, prepared)
        (directory / 'expected.rgb').write_bytes(expected)
        (directory / 'project.mlt').write_bytes(project(prepared, directory))
        _write_bundle(directory, prepared)
        stage('reopen', {'MLT_XML_DEEP': '1'})
        _reopened(directory, prepared)
        stage('render')
        stage('rerender')
        for basename in ('video', 'reopened-video'):
            stage(basename + '-decode')
            stage(basename + '-probe')
        stage('version')
        stage('ffmpeg-version')
        atomic_json(directory / 'commands.json', commands)
        receipt = _receipt(directory, prepared)
        atomic_json(directory / 'verification.json', receipt)
        verify(directory, require_result=False)
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'timeline verification exhausted the total timeout')
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'timeline publication cancelled')
        result = _result(directory)
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error), str(directory))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def _receipt(directory, prepared):
    options = prepared['nodes'][0]['options']
    sources, expected = _expected(directory, prepared)
    chunk = options['width'] * options['height'] * 3
    if _regular(directory, 'project.mlt').read_bytes() != project(prepared, directory): fail('VERIFICATION_FAILED', 'editable native project differs')
    if _regular(directory, 'expected.rgb').read_bytes() != expected: fail('VERIFICATION_FAILED', 'expected timeline evidence differs')
    decoded = _regular(directory, 'video.rgb').read_bytes()
    reopened = _regular(directory, 'reopened-video.rgb').read_bytes()
    errors = _compare(expected, decoded, chunk)
    if decoded != reopened: fail('VERIFICATION_FAILED', 'fresh native reload renders different pixels')
    for basename in ('video', 'reopened-video'): _probe(_read(directory, basename + '-probe.stdout'), options, prepared['frames'])
    reopened_digest = _reopened(directory, prepared)
    artifacts = [{'file': str(directory / 'video.mkv'), 'kind': 'video', 'sha256': file_digest(_regular(directory, 'video.mkv')),
                  'frames': prepared['frames'], 'dimensions': [options['width'], options['height']], 'duration': prepared['duration']},
                 {'file': str(directory / 'project.mlt'), 'kind': 'videoProject', 'sha256': file_digest(directory / 'project.mlt'),
                  'format': 'Shotcut MLT XML', 'assets': [source['retained'] for source in sources]},
                 {'file': str(directory / 'project-bundle.zip'), 'kind': 'videoProjectBundle', 'sha256': _check_bundle(directory, prepared),
                  'format': 'ZIP/Shotcut MLT XML', 'members': _bundle_names(prepared), 'selfContained': True}]
    commands = _read(directory, 'commands.json')
    stages = {'reopen', 'render', 'rerender', 'video-decode', 'video-probe', 'reopened-video-decode', 'reopened-video-probe', 'version', 'ffmpeg-version'}
    stages.update(f'asset-{i:02d}-{suffix}' for i in range(len(sources)) for suffix in ('probe', 'decode'))
    if set(commands) != stages: fail('VERIFICATION_FAILED', 'native stage evidence differs')
    melt, ffmpeg = commands['version'][0], commands['ffmpeg-version'][0]
    if not all(isinstance(path, str) and Path(path).is_absolute() for path in (melt, ffmpeg)):
        fail('VERIFICATION_FAILED', 'runtime paths must be absolute')
    probe = str(Path(ffmpeg).with_name('ffprobe'))
    if commands != _commands(directory, prepared, melt, ffmpeg, probe):
        fail('VERIFICATION_FAILED', 'native commands differ from declared timeline')
    evidence = {}
    for name in sorted(stages):
        submission = _read(directory, name + '-submission.json')
        launcher = _regular(directory, name + '-launcher.py', 1024 * 1024)
        if launcher.read_text() != _launcher(directory, prepared, name, commands[name]):
            fail('VERIFICATION_FAILED', 'native stage launcher differs', name)
        wrapper = [submission['interpreter']['executable'], str(launcher)]
        if submission.get('nativeCommand') != wrapper or submission.get('exitCode') != 0:
            fail('VERIFICATION_FAILED', 'native stage command or exit evidence differs', name)
        inputs = {str(path): file_digest(_regular(directory, path.name)) for path in _stage_inputs(directory, prepared, name)}
        if _read(directory, name + '-inputs.json') != inputs:
            fail('VERIFICATION_FAILED', 'native readback consumed different publication bytes', name)
        for suffix in ('.stdout', '.stderr', '-submission.json', '-inputs.json', '-launcher.py'):
            filename = name + suffix
            evidence[filename] = file_digest(_regular(directory, filename, 16 * 1024 * 1024))
    runtime = _regular(directory, 'version.stdout').read_text().splitlines()[0]
    if not runtime.startswith('melt '): fail('VERIFICATION_FAILED', 'native runtime identity is absent')
    return {'artifacts': artifacts, 'sources': sources, 'frames': prepared['frames'], 'fps': options['fps'],
            'width': options['width'], 'height': options['height'], 'duration': prepared['duration'], 'segments': prepared['segments'],
            'meanErrors': errors, 'decodedSHA256': hashlib.sha256(decoded).hexdigest(), 'expectedSHA256': hashlib.sha256(expected).hexdigest(),
            'reopenedSHA256': reopened_digest, 'reopenedVideoSHA256': file_digest(_regular(directory, 'reopened-video.mkv')),
            'commandsSHA256': file_digest(directory / 'commands.json'), 'nativeEvidence': evidence, 'runtime': runtime,
            'ffmpegRuntime': _regular(directory, 'ffmpeg-version.stdout').read_text().splitlines()[0], 'losses': LOSSES}


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        prepared = plan(_read(directory, 'authored.json'))
        result = _read(directory, 'result.json')
        if require_result and (result.get('status') != 'succeeded' or result.get('verified') is not True):
            fail('INCOMPLETE_EXECUTION', 'timeline publication did not complete')
        if require_result: _check_result(directory, result)
        if _read(directory, 'plan.json') != prepared: fail('VERIFICATION_FAILED', 'timeline plan differs')
        expected = _receipt(directory, prepared)
        if _read(directory, 'verification.json') != expected: fail('VERIFICATION_FAILED', 'timeline verification evidence differs')
        return {'verified': True, 'artifacts': 3, 'frames': prepared['frames'], 'duration': prepared['duration'], 'runtime': expected['runtime']}
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, ET.ParseError, zipfile.BadZipFile) as error:
        fail('VERIFICATION_FAILED', 'missing or invalid timeline evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
