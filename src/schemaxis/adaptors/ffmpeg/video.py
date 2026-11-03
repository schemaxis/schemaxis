# Copyright (C) 2026 David L F Gaden
"""Bounded existing-video capture contract; no arbitrary native options."""
import json
import math
from fractions import Fraction
from pathlib import Path

from schemaxis.errors import fail

MAX_RGB = 192 * 1024 * 1024
MAX_PROBE = 4 * 1024 * 1024


def source_paths(node):
    options = node['options']
    if node['filter'] == 'encodeFrames':
        return options['files']
    if node['filter'] == 'encodeVideo':
        return [options['file']]
    return [options['file'], options['metadata']]


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


def inspect(probe):
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
        if not isinstance(frames, list) or not 1 <= len(frames) <= 600:
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
        fail('UNSUPPORTED_VIDEO', str(error), '$.nodes[0].options.file')


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
