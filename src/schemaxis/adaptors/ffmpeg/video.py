# Copyright (C) 2026 David L F Gaden
"""Bounded existing-video capture contract; no arbitrary native options."""
import json
import math
import re
from fractions import Fraction
from pathlib import Path

from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail

MAX_RGB = 192 * 1024 * 1024
MAX_PROBE = 4 * 1024 * 1024
MAX_FRAMES = 600
MAX_DIAGNOSTIC = 1024
LOCATION = '$.nodes[0].options.file'
# Top-level boxes an MP4/QuickTime-family file may begin with.
MP4_BOXES = (b'ftyp', b'moov', b'mdat', b'free', b'skip', b'wide', b'uuid', b'styp', b'sidx', b'moof', b'pdin', b'meta')


def source_paths(node):
    options = node['options']
    if node['filter'] == 'encodeFrames':
        return options['files']
    if node['filter'] == 'encodeVideo':
        return [options['file']]
    if node['filter'] == 'muxReview':
        return [options['video'], options['audio'], options['captions']]
    return [options['file'], options['metadata']]


def container_signature(data):
    """Native-free container identification from the leading bytes: matroska, mp4 or None."""
    if data[:4] == b'\x1a\x45\xdf\xa3':
        return 'matroska'
    if len(data) >= 8 and data[4:8] in MP4_BOXES:
        size = int.from_bytes(data[:4], 'big')
        if size in (0, 1) or size >= 8:
            return 'mp4'
    return None


def check_source(data, path, location=LOCATION):
    """Reject a source whose bytes are not its declared container before any native launch."""
    declared = 'mp4' if Path(path).suffix.lower() == '.mp4' else 'matroska'
    detected = container_signature(data)
    if detected == declared:
        return
    observed = {'declared': declared, 'detected': detected, 'bytes': len(data)}
    if detected is None:
        code, message = 'INVALID_RESOURCE', 'source bytes are not a recognisable Matroska or MP4 container'
        recovery = ('Supply an intact Matroska/FFV1 (.mkv) or MP4/H.264 (.mp4) file; an empty, truncated, '
                    'renamed or non-video file cannot be used.')
    else:
        code, message = 'UNSUPPORTED_VIDEO', f'source is a {detected} container but its extension declares {declared}'
        recovery = ('Use the extension that matches the contents (.mkv for Matroska/FFV1, .mp4 for MP4/H.264) '
                    'or supply a source in the declared container.')
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


def check_diagnostics(directory, stage, location=LOCATION):
    """Refuse source errors while keeping launcher/runtime diagnostics distinct."""
    path = directory / (stage + '.stderr')
    if path.is_symlink() or not path.is_file():
        fail('VERIFICATION_FAILED', 'native source diagnostics are absent', stage)
    with path.open('rb') as stream:
        text = stream.read(MAX_DIAGNOSTIC + 1).decode('utf-8', 'replace').strip()
    if not text:
        return
    text = text.replace(str(directory), '<run>')
    # The shared stderr also includes launcher/loader output. Do not blame valid
    # source bytes for an environment warning or an allocation failure.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    native = all(re.match(r'^\[[^]]+ @ 0x[0-9a-f]+\]', line, re.I)
                 or '<run>/input-0000' in line for line in lines)
    resource = any(term in text.lower() for term in ('cannot allocate memory', 'failed to allocate',
                   'out of memory', 'resource temporarily unavailable', 'cannot open shared object', 'symbol lookup error'))
    if not native or resource:
        raise SchemaxisError(Fault('RUNNER_FAILED', 'source inspection produced runtime or unclassified diagnostics',
            location, 'pipeline', observed={'stage': stage, 'diagnostics': text[:MAX_DIAGNOSTIC]},
            recovery='Inspect the retained diagnostics and the configured runtime/environment, then retry in a fresh directory; source validity was not established.'))
    raise SchemaxisError(Fault('INVALID_RESOURCE', 'FFmpeg reported errors reading the source',
        location, 'pipeline', observed={'stage': stage, 'diagnostics': text[:MAX_DIAGNOSTIC]},
        recovery='Re-export or re-download the source so it decodes without errors (a truncated or '
                 'corrupt file can otherwise look like a shorter clip), then run into a fresh directory.'))


def commands(executable, directory, prepared):
    options = prepared['nodes'][0]['options']
    # Force a single-file demuxer and disable rotation. MP4 edit lists use
    # native default presentation semantics identically in probe and decode.
    demuxer = 'mov' if Path(options['file']).suffix.lower() == '.mp4' else 'matroska'
    inputs = ['-protocol_whitelist', 'file', '-f', demuxer]
    source = str(directory / 'input-0000')
    return {
        'source-probe': [str(Path(executable).with_name('ffprobe')), '-v', 'error',
            '-threads', str(options['threads']), *inputs, '-read_intervals', '%+#602', '-show_streams', '-show_frames',
            '-show_entries', 'frame=best_effort_timestamp_time,width,height,pix_fmt:stream:format=format_name,nb_streams',
            '-show_format', '-of', 'json', source],
        'source-decode': [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
            '-filter_threads', '1', '-threads', str(options['threads']), '-noautorotate',
            *inputs, '-i', source, '-map', '0:v:0', '-an', '-sn', '-dn',
            '-frames:v', '601', '-fs', str(MAX_RGB + 1), '-fps_mode', 'passthrough',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(directory / 'source-decoded.rgb')],
    }


def inspect(probe, location=LOCATION):
    """Validate the complete bounded source's decoded timeline before selection."""
    try:
        streams = probe['streams']
        if len(streams) != 1 or streams[0]['codec_type'] != 'video':
            raise ValueError('source must contain exactly one video stream and no audio, subtitles or data')
        stream = streams[0]
        container = probe['format']['format_name']
        allowed = ((stream['codec_name'] == 'ffv1' and stream['pix_fmt'] == 'bgr0' and 'matroska' in container)
                   or (stream['codec_name'] == 'h264' and stream['pix_fmt'] == 'yuv420p' and 'mp4' in container))
        if not allowed:
            raise ValueError('supported sources are Matroska/FFV1 bgr0 and MP4/H.264 yuv420p')
        width, height = stream['width'], stream['height']
        if type(width) is not int or type(height) is not int or not 1 <= width <= 4096 or not 1 <= height <= 4096:
            raise ValueError('source dimensions must be 1..4096 pixels')
        if stream.get('sample_aspect_ratio') not in (None, '0:1', '1:1'):
            raise ValueError('non-square source pixels are unsupported')
        tags = stream.get('tags', {})
        if not isinstance(tags, dict):
            raise ValueError('source stream tags must be an object')
        if stream.get('side_data_list') or tags.get('rotate'):
            raise ValueError('source rotation or stream side data is unsupported')
        if stream.get('field_order') not in (None, 'unknown', 'progressive'):
            raise ValueError('interlaced sources are unsupported')
        rate = Fraction(stream['avg_frame_rate'])
        if rate.denominator != 1 or not 1 <= rate <= 120 or Fraction(stream['r_frame_rate']) != rate:
            raise ValueError('source must have an integer constant frame rate from 1 to 120')
        frames = probe['frames']
        if isinstance(frames, list) and len(frames) > MAX_FRAMES:
            # The bounded probe stops shortly after the limit, so only a lower bound is known.
            raise SchemaxisError(Fault('RESOURCE_LIMIT', f'source exceeds {MAX_FRAMES} decoded frames', location,
                'pipeline', observed={'maximumFrames': MAX_FRAMES},
                recovery=f'Trim the source to at most {MAX_FRAMES} frames before use; startFrame/endFrame '
                         'select within the whole source and cannot make a longer source acceptable.'))
        if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
            raise ValueError('source must contain 1..600 decoded frames')
        if len(frames) * width * height * 3 > MAX_RGB:
            fail('RESOURCE_LIMIT', 'source RGB exceeds 192 MiB')
        for index, frame in enumerate(frames):
            if (frame['width'], frame['height'], frame['pix_fmt']) != (width, height, stream['pix_fmt']):
                raise ValueError('source changes dimensions or pixel format')
            timestamp = float(frame['best_effort_timestamp_time'])
            # Matroska commonly rounds timestamps to milliseconds. No initial
            # offset or variable cadence is silently collapsed into output fps.
            if not math.isfinite(timestamp) or not math.isclose(timestamp, index / rate, rel_tol=0, abs_tol=.0011):
                raise ValueError('source timestamps must start at zero and follow the constant frame rate')
        return width, height, len(frames), int(rate)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        fail('UNSUPPORTED_VIDEO', str(error), location)


def read(directory, prepared):
    probe_path = directory / 'source-probe.stdout'
    raw_path = directory / 'source-decoded.rgb'
    for path, limit in ((probe_path, MAX_PROBE), (raw_path, MAX_RGB)):
        if path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED', 'required regular source readback is absent', path.name)
        if path.stat().st_size > limit:
            fail('RESOURCE_LIMIT', 'source readback exceeds byte budget', path.name)
    width, height, count, rate = inspect(json.loads(probe_path.read_text()))
    raw = raw_path.read_bytes()
    stride = width * height * 3
    if len(raw) != count * stride:
        fail('VERIFICATION_FAILED', 'source decode count/dimensions differ from source probe')
    options = prepared['nodes'][0]['options']
    start, end = options['startFrame'], options['endFrame']
    if end > count:
        fail('INVALID_FRAME_RANGE', 'endFrame exceeds the decoded source frame count', '$.nodes[0].options.endFrame')
    if options['codec'] == 'h264' and (width % 2 or height % 2):
        fail('INVALID_IMAGE', 'H.264 YUV420 requires even frame dimensions')
    return width, height, [raw[index * stride:(index + 1) * stride] for index in range(start, end)]
