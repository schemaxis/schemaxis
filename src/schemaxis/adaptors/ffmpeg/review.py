"""Verified review movie: captured FFV1 video, PCM16 audio and SubRip captions in one Matroska file."""
import hashlib
import json
import math
import os
from fractions import Fraction
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import tempfile
import time
import unicodedata

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested, execution_deadline, remaining_timeout
from schemaxis.errors import fail
from schemaxis.native_command import execute
from . import video

OPTIONS = ('video', 'audio', 'captions')
OUTPUT = 'review.mkv'
MAX_BYTES = 32 * 1024 * 1024
# The native readback of a source at the budget is 24 bytes longer above 48 kHz (fmt 40 against fmt 16); source and PCM budgets stay MAX_BYTES.
NATIVE_WAV_OVERHEAD = 24
MAX_READBACK_WAV = MAX_BYTES + NATIVE_WAV_OVERHEAD
MAX_OUTPUT = 128 * 1024 * 1024
MAX_RGB = video.MAX_RGB
MAX_PROBE = 1024 * 1024
MAX_CAPTION_BYTES = 256 * 1024
MAX_CUES = 1000
MAX_CUE_LINES = 4
MAX_CUE_CHARS = 500
STAGE_TIMEOUT = 120
VERIFY_TIMEOUT = 300
MAX_EVIDENCE = 1024 * 1024
ENVIRONMENT = 'FFMPEG_EXECUTABLE'
CAPTION_STATUS = ('machineDraft', 'declaredHumanReviewed')
MARKUP = '<>{}\\'
LOCATION = '$.nodes[0].options.'
# Source-stage names are shared with the single-video operations; output stages are listed with their products.
STAGES = {'encode': OUTPUT, 'probe': 'probe.stdout', 'decode': 'decoded.rgb',
          'decode-audio': 'decoded-audio.wav', 'extract-captions': 'extracted.srt'}
SOURCE_STAGES = ('source-probe', 'source-decode')
# The frame timeline is read only by the fresh verification pass; the retained receipt format is unchanged.
TIMELINE = 'timeline'
# The published audio packets are read, also only by the fresh pass, to refuse internal gaps and overlaps. PCM16 packets are
# at most 1024 sample frames in the muxed output, so a 32 MiB source yields at most 16384; both bounds are explicit.
AUDIO_PACKETS = 'audio-packets'
MAX_PACKETS = 32768
MAX_PACKET_PROBE = 8 * 1024 * 1024
FRESH_ONLY = (TIMELINE, AUDIO_PACKETS)
# Matroska rounds timestamps to milliseconds; the same bound video.inspect applies to the captured source.
TIMESTAMP_TOLERANCE = Fraction(11, 10000)
SECONDS = re.compile(r'-?[0-9]{1,9}(\.[0-9]{1,9})?')
POLICY = ('Audio and video must differ in duration by at most one video frame period (|samples/rate - frames/fps| <= 1/fps, '
          'exact rational arithmetic); no trimming, padding or resampling; every caption must end within the video duration.')
LOSSES = ['FFV1 video and PCM16 audio are stream-copied; SubRip captions are soft (selectable), never burned in',
          'caption text is machine-draft or author-declared status; recognition accuracy and human review are not verified',
          'no metadata, chapters, attachments or fonts; no trimming, padding, resampling or caption retiming']


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key ' + key)
        result[key] = value
    return result


def finite_number(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number ' + text[:20])
    return value


def refuse_constant(name):
    raise ValueError('non-finite JSON constant ' + name)


def strict_text(text):
    """Strict JSON: no duplicate keys, NaN/Infinity, numbers that overflow to infinity (1e400) or excess depth."""
    return json.loads(text, object_pairs_hook=unique_object, parse_float=finite_number, parse_constant=refuse_constant)


def strict_json(data, name):
    try:
        text = data.decode('utf-8') if isinstance(data, (bytes, bytearray)) else data
        if text.startswith('\ufeff'):
            raise ValueError('byte-order mark')
        return strict_text(text)
    except (ValueError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained JSON %s: %s' % (name, str(error)[:80]), name)


def same_json(actual, expected):
    """Typed canonical comparison: 1 is not true and 6 is not 6.0, unlike Python equality."""
    try:
        return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return False


def trusted(executable=None):
    """Trusted FFmpeg and the ffprobe beside it: explicit argument, stored/invocation configuration, then environment.

    Receipts, submissions, authored input and PATH never supply an executable."""
    value = executable or configured_executable('ffmpeg') or os.environ.get(ENVIRONMENT)
    paths = {'ffmpeg': value, 'ffprobe': os.path.join(os.path.dirname(value), 'ffprobe') if isinstance(value, str) else None}
    for name, path in paths.items():
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise SchemaxisError(Fault('INTERPRETER_NOT_FOUND',
                'verifying a muxReview publication needs a trusted absolute %s executable to decode the published bytes again'
                % ('FFmpeg' if name == 'ffmpeg' else 'ffprobe beside FFmpeg'), '$.runtime.' + name, 'pipeline',
                recovery='Pass executable= to verify, or configure FFmpeg (schemaxis configure ffmpeg / a stored locations.ffmpeg '
                         'entry in the private configuration file), or set ' + ENVIRONMENT + '. A bare `schemaxis verify` has no '
                         'executable flag and needs the stored configuration or the environment variable; ffprobe must be '
                         'in the same directory. Paths in receipts and PATH are never used.'))
    return paths


def ratio(value):
    return f'{value.numerator}/{value.denominator}'


# FFmpeg writes PCM16 above 48 kHz, and only above 48 kHz, as WAVE_FORMAT_EXTENSIBLE (fmt 40); only its own decoded readback may use it.
EXTENSIBLE = 0xFFFE
PCM_GUID = bytes.fromhex('0100000000001000800000aa00389b71')
CHANNEL_MASK = {1: 0x4, 2: 0x3}


def wav_format(data, location, native):
    """Strict PCM16 WAV. Source audio: canonical 44-byte header only. Native readback: FFmpeg's layout, fmt 40 iff above 48 kHz."""
    def bad(reason, **observed):
        fail('INVALID_RESOURCE', 'audio is not a well-formed canonical PCM WAV: ' + reason, location, **observed)

    def unsupported(reason, **observed):
        fail('UNSUPPORTED_AUDIO', reason, location, **observed)
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        bad('missing RIFF/WAVE header', bytes=len(data))
    if int.from_bytes(data[4:8], 'little') != len(data) - 8:
        bad('RIFF size differs from the file size (streamed, truncated or trailing bytes)')
    if data[12:16] != b'fmt ':
        unsupported('the first chunk must be fmt')
    fmt_size = int.from_bytes(data[16:20], 'little')
    extensible = native and fmt_size == 40
    if fmt_size != 16 and not extensible:
        unsupported('only the 16-byte PCM fmt chunk is supported (not extensible or extended formats)')
    header = 20 + fmt_size
    if len(data) < header + 8:
        bad('truncated header', bytes=len(data))
    tag, channels, rate, byte_rate, align, bits = struct.unpack('<HHIIHH', data[20:36])
    if tag != (EXTENSIBLE if extensible else 1) or bits != 16:
        unsupported('only integer PCM at 16 bits per sample is supported', formatTag=tag, bitsPerSample=bits)
    if channels not in (1, 2) or not 8000 <= rate <= 96000:
        unsupported('only mono or stereo audio from 8000 to 96000 Hz is supported', channels=channels, sampleRate=rate)
    if native and extensible != (rate > 48000):
        unsupported('the native readback header layout must be the extensible fmt above 48000 Hz and the canonical fmt otherwise',
                    fmtBytes=fmt_size, sampleRate=rate)
    if extensible:
        extension, valid_bits, mask = struct.unpack('<HHI', data[36:44])
        if extension != 22 or valid_bits != 16 or data[44:60] != PCM_GUID:
            unsupported('the extensible fmt must declare 22 extension bytes, 16 valid bits and the integer PCM sub-format',
                        extensionBytes=extension, validBits=valid_bits)
        if mask != CHANNEL_MASK[channels]:
            unsupported('the extensible channel mask must be front-centre for mono or front-left and right for stereo',
                        channelMask=mask, channels=channels)
    if align != channels * 2 or byte_rate != rate * align:
        bad('fmt block alignment or byte rate is inconsistent')
    if data[header:header + 4] != b'data':
        unsupported('only fmt followed directly by data is supported; LIST, fact and other chunks are not accepted')
    size = int.from_bytes(data[header + 4:header + 8], 'little')
    if header + 8 + size != len(data):
        bad('data chunk size differs from the remaining bytes')
    if size == 0 or size % align:
        bad('data must hold a whole, positive number of sample frames', bytes=size)
    return {'channels': channels, 'sampleRate': rate, 'samples': size // align, 'bytes': size,
            'pcm': memoryview(data)[header + 8:]}


def parse_wav(data, location=LOCATION + 'audio'):
    """Canonical 44-byte-header PCM16 WAV only; anything else is named, never repaired."""
    return wav_format(data, location, False)


def parse_native_wav(data, location='decoded-audio.wav'):
    """The trusted FFmpeg's own PCM16 readback: fmt-40 extensible header above 48 kHz, canonical otherwise, same format limits.

    The bytes are produced by the verified runtime, so any refusal is a verification fault, not a source-input fault."""
    try:
        return wav_format(data, location, True)
    except SchemaxisError as error:
        fail('VERIFICATION_FAILED', 'native decoded audio is not a well-formed PCM16 WAV: ' + error.fault.message,
             location, stage='decode-audio', cause=error.fault.code)


CLOCK = r'([0-9]{2}):([0-5][0-9]):([0-5][0-9]),([0-9]{3})'
TIMING = re.compile(f'^{CLOCK} --> {CLOCK}$')


def parse_srt(data, location=LOCATION + 'captions'):
    """Strict bounded SubRip: contiguous indices, ms intervals, plain visible text. Returns [(startMs, endMs, text)]."""
    def bad(reason, **observed):
        fail('INVALID_RESOURCE', 'captions are not strict SubRip: ' + reason, location, **observed)
    if len(data) > MAX_CAPTION_BYTES:
        fail('RESOURCE_LIMIT', 'caption byte budget exceeded', location, maximumBytes=MAX_CAPTION_BYTES)
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        bad('not UTF-8')
    if text.startswith('﻿'):
        bad('a byte-order mark is not accepted')
    if '\r' in text:
        if text.count('\r\n') != text.count('\n') or text.count('\r') != text.count('\r\n'):
            bad('mixed or bare carriage-return line endings')
        text = text.replace('\r\n', '\n')
    if not text.endswith('\n'):
        bad('the final line must end with a newline')
    body = text[:-2] if text.endswith('\n\n') else text[:-1]
    if not body or body.endswith('\n'):
        bad('no cues, or extra blank lines at the end')
    cues, previous = [], 0
    for position, block in enumerate(body.split('\n\n'), 1):
        lines = block.split('\n')
        if len(cues) >= MAX_CUES:
            fail('RESOURCE_LIMIT', 'caption cue budget exceeded', location, maximumCues=MAX_CUES)
        if len(lines) < 3 or lines[0] != str(position):
            bad('cue indices must be contiguous decimal numbers starting at 1', cue=position)
        match = TIMING.match(lines[1])
        if not match:
            bad('timing must be HH:MM:SS,mmm --> HH:MM:SS,mmm without positions', cue=position)
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
        start, end = [((h * 60 + m) * 60 + s) * 1000 + ms for h, m, s, ms in ((h1, m1, s1, ms1), (h2, m2, s2, ms2))]
        if end <= start:
            bad('cue intervals must be positive', cue=position)
        if start < previous:
            bad('cues must be monotonic and must not overlap', cue=position)
        previous = end
        lines = lines[2:]
        if len(lines) > MAX_CUE_LINES or sum(map(len, lines)) > MAX_CUE_CHARS:
            fail('RESOURCE_LIMIT', 'caption cue text budget exceeded', location, cue=position,
                 maximumLines=MAX_CUE_LINES, maximumCharacters=MAX_CUE_CHARS)
        for line in lines:
            if line != line.strip(' '):
                bad('cue text lines must not begin or end with a space (FFmpeg would silently trim it)', cue=position)
            for char in line:
                category = unicodedata.category(char)
                if char in MARKUP:
                    fail('UNSUPPORTED_CAPTIONS', 'markup characters < > { } \\ are not accepted; captions are plain text',
                         location, cue=position)
                if char != ' ' and category[0] not in 'LMNPS':
                    fail('UNSUPPORTED_CAPTIONS', 'control, format (including bidirectional), separator and unassigned '
                         'characters are not accepted', location, cue=position, codePoint=f'U+{ord(char):04X}')
        cues.append((start, end, '\n'.join(lines)))
    return cues


def cue_digest(cues):
    return hashlib.sha256(json.dumps(cues, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def alignment(samples, rate, frames, fps, cues):
    """Exact rational duration policy; a violation names the measured values and never alters media."""
    video_seconds, audio_seconds, tolerance = Fraction(frames, fps), Fraction(samples, rate), Fraction(1, fps)
    difference = abs(video_seconds - audio_seconds)
    record = {'policy': POLICY, 'videoSeconds': ratio(video_seconds), 'audioSeconds': ratio(audio_seconds),
              'differenceSeconds': ratio(difference), 'toleranceSeconds': ratio(tolerance),
              'lastCaptionEndMs': cues[-1][1], 'accepted': difference <= tolerance}
    if difference > tolerance:
        raise SchemaxisError(Fault('MEDIA_DURATION_MISMATCH', 'audio and video durations differ by more than one video frame',
            LOCATION + 'audio', 'pipeline', observed=record,
            recovery='Trim or pad the audio (SoX) or select the matching video range so both last the same time; '
                     'this operation never trims, pads or resamples.'))
    if cues[-1][1] * fps > frames * 1000:
        raise SchemaxisError(Fault('CAPTIONS_OUT_OF_RANGE', 'a caption ends after the video ends', LOCATION + 'captions',
            'pipeline', observed=record,
            recovery='Correct the caption timing or use a longer video; captions are never clipped.'))
    return record


def seconds(value):
    """Exact seconds from an FFprobe decimal string; N/A, NaN, infinity, exponents, spaces and non-strings are refused."""
    if type(value) is not str or not SECONDS.fullmatch(value):
        raise ValueError('timestamp %r is not a finite decimal number of seconds' % (value if isinstance(value, str) else type(value).__name__)[:24])
    return Fraction(value)


def check_timeline(listing, count, rate):
    """Every published video frame carries a best-effort timestamp that starts at zero and follows index/fps.

    The frame list is read from a bounded video-only probe of the published file and must match the captured count exactly."""
    try:
        frames = listing['frames']
        if not isinstance(frames, list) or len(frames) != count or count > video.MAX_FRAMES:
            raise ValueError('expected exactly %d video frame timestamps, found %s' % (count, len(frames) if isinstance(frames, list) else 'none'))
        for index, frame in enumerate(frames):
            stamp = seconds(frame['best_effort_timestamp_time'])
            if abs(stamp - Fraction(index) / rate) > TIMESTAMP_TOLERANCE:
                raise ValueError('video frame %d is at %s s instead of %s s: the timeline must start at zero and follow the constant frame rate'
                                 % (index, float(stamp), float(Fraction(index) / rate)))
    except (KeyError, TypeError, ZeroDivisionError) as error:
        fail('VERIFICATION_FAILED', 'published video timeline differs: %s %s' % (type(error).__name__, str(error)[:60]), stage=TIMELINE)
    except ValueError as error:
        fail('VERIFICATION_FAILED', 'published video timeline differs: ' + str(error), stage=TIMELINE)


def check_audio_packets(listing, audio):
    """Every published PCM16 packet is whole sample frames and follows the cumulative sample clock from zero.

    The captured sample count is the anchor: packet sizes must sum to it, each timestamp must equal the frames before it over
    the sample rate (Matroska millisecond quantisation allowed), so an internal gap or overlap is refused even when the stream
    start and the container duration are plausible. Recorded packet durations, when present, must match the frame count."""
    try:
        packets = listing['packets']
        if not isinstance(packets, list) or not 0 < len(packets) <= MAX_PACKETS:
            raise ValueError('expected between 1 and %d audio packets, found %s' % (MAX_PACKETS, len(packets) if isinstance(packets, list) else 'none'))
        align, rate, done = audio['channels'] * 2, audio['sampleRate'], 0
        for index, packet in enumerate(packets):
            size = packet['size']
            if type(size) is not str or not size.isascii() or not size.isdigit() or int(size) == 0 or int(size) % align:
                raise ValueError('audio packet %d does not hold a whole positive number of PCM16 sample frames' % index)
            frames = int(size) // align
            expected = Fraction(done, rate)
            stamp = seconds(packet['pts_time'])
            if abs(stamp - expected) > TIMESTAMP_TOLERANCE:
                raise ValueError('audio packet %d is at %s s instead of %s s: the audio has a gap, overlap or offset'
                                 % (index, float(stamp), float(expected)))
            if 'duration_time' in packet and abs(seconds(packet['duration_time']) - Fraction(frames, rate)) > TIMESTAMP_TOLERANCE:
                raise ValueError('audio packet %d records a duration that differs from its %d sample frames' % (index, frames))
            done += frames
        if done != audio['samples']:
            raise ValueError('published audio packets hold %d sample frames instead of the captured %d' % (done, audio['samples']))
    except (KeyError, TypeError, ZeroDivisionError, AttributeError) as error:
        fail('VERIFICATION_FAILED', 'published audio packet timeline differs: %s %s' % (type(error).__name__, str(error)[:60]), stage=AUDIO_PACKETS)
    except ValueError as error:
        fail('VERIFICATION_FAILED', 'published audio packet timeline differs: ' + str(error), stage=AUDIO_PACKETS)


def commands(executable, directory, options):
    prefix = [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
    out = str(directory / OUTPUT)
    threads = str(options['threads'])
    reopen = ['-protocol_whitelist', 'file', '-f', 'matroska', '-i', out]
    # Stream maps are explicit: one video, one audio and one subtitle stream, copied as they are. Metadata and chapters
    # are dropped and +bitexact removes the writer version, so identical inputs yield identical output bytes.
    return {
        'encode': prefix + ['-threads', threads, '-protocol_whitelist', 'file',
            '-f', 'matroska', '-i', str(directory / 'input-0000'), '-f', 'wav', '-i', str(directory / 'input-0001'),
            '-f', 'srt', '-i', str(directory / 'input-0002'),
            '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0', '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy',
            '-map_metadata', '-1', '-map_chapters', '-1', '-fflags', '+bitexact', '-fs', str(MAX_OUTPUT + 1),
            '-f', 'matroska', out],
        'probe': [str(Path(executable).with_name('ffprobe')), '-v', 'error', '-count_frames', '-show_streams',
                  '-show_format', '-show_chapters', '-of', 'json', '-protocol_whitelist', 'file', '-f', 'matroska', out],
        'decode': prefix + ['-threads', threads, *reopen, '-map', '0:v:0', '-an', '-sn', '-dn',
            '-fps_mode', 'passthrough', '-fs', str(MAX_RGB + 1), '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(directory / 'decoded.rgb')],
        'decode-audio': prefix + [*reopen, '-map', '0:a:0', '-vn', '-sn', '-dn', '-c:a', 'pcm_s16le',
            '-fflags', '+bitexact', '-fs', str(MAX_BYTES + 1), '-f', 'wav', str(directory / 'decoded-audio.wav')],
        'extract-captions': prefix + [*reopen, '-map', '0:s:0', '-vn', '-an', '-dn', '-c:s', 'srt',
            '-fflags', '+bitexact', '-fs', str(MAX_CAPTION_BYTES * 2), '-f', 'srt', str(directory / 'extracted.srt')],
        TIMELINE: [str(Path(executable).with_name('ffprobe')), '-v', 'error', '-select_streams', 'v:0', '-read_intervals', '%+#602',
                   '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', '-protocol_whitelist', 'file',
                   '-f', 'matroska', out],
        AUDIO_PACKETS: [str(Path(executable).with_name('ffprobe')), '-v', 'error', '-select_streams', 'a:0', '-show_packets',
                        '-show_entries', 'packet=pts_time,duration_time,size', '-of', 'json', '-protocol_whitelist', 'file',
                        '-f', 'matroska', out],
        'version': [executable, '-version'],
    }


def stage_inputs(directory, stage):
    if stage == 'encode':
        return [directory / f'input-000{i}' for i in range(3)]
    return [directory / OUTPUT]


def launcher(directory, stage, command):
    """Bind each native stage to the digests of the exact files it opens, then exec the trusted argv."""
    limit = {'encode': MAX_OUTPUT + MAX_BYTES, 'decode': MAX_RGB + 4 * 1024 * 1024,
             AUDIO_PACKETS: MAX_PACKET_PROBE + 1}.get(stage, MAX_BYTES + 4 * 1024 * 1024)
    limits = ('import resource\nresource.setrlimit(resource.RLIMIT_AS, (2147483648,2147483648))\n'
              + f'resource.setrlimit(resource.RLIMIT_FSIZE, ({limit},)*2)\n' if os.name == 'posix' else '')
    paths = [str(path) for path in stage_inputs(directory, stage)]
    return ('import hashlib, json, os, stat\nfrom pathlib import Path\n' + limits
        + f'paths={paths!r}\ncommand={command!r}\nbinding={{}}\n'
        + 'for name in paths:\n    path=Path(name)\n'
        + '    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode): raise ValueError("native input is not regular")\n'
        + f'    if path.stat().st_size>{MAX_OUTPUT}: raise ValueError("native input byte budget exceeded")\n'
        + '    digest=hashlib.sha256()\n    with path.open("rb") as stream:\n'
        + '        for block in iter(lambda:stream.read(1048576), b""): digest.update(block)\n'
        + '    binding[str(path)]=digest.hexdigest()\n'
        + f'Path({str(directory / (stage + "-inputs.json"))!r}).write_text(json.dumps(binding,sort_keys=True))\n'
        + 'os.execvpe(command[0],command,os.environ)\n')


def evidence(directory, command_set, submissions, stages):
    """Shared launcher/binding verification for the output stages; source stages reuse the base helper."""
    result = {}
    for stage in stages:
        script, binding = directory / (stage + '-launcher.py'), directory / (stage + '-inputs.json')
        for path in (script, binding):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PROBE:
                fail('VERIFICATION_FAILED', 'required bounded native stage evidence is absent', stage)
        if script.read_text() != launcher(directory, stage, command_set[stage]):
            fail('VERIFICATION_FAILED', 'native stage launcher differs', stage)
        record = submissions[stage].get('interpreter')
        interpreter = record.get('executable') if isinstance(record, dict) else None
        if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submissions[stage]['nativeCommand'] != [interpreter, str(script)]:
            fail('VERIFICATION_FAILED', 'native stage wrapper differs', stage)
        if not same_json(strict_json(binding.read_bytes(), stage + '-inputs.json'),
                         {str(path): file_digest(path) for path in stage_inputs(directory, stage)}):
            fail('VERIFICATION_FAILED', 'native stage consumed different input bytes (captured source or encoded review file changed)', stage)
        result[stage] = {'launcherSHA256': file_digest(script), 'inputBindingSHA256': file_digest(binding),
                         'outputSHA256': file_digest(directory / STAGES[stage])}
    return result


def source_pseudo_plan(options):
    return {'nodes': [{'options': {'file': options['video'], 'threads': options['threads']}}], 'output': OUTPUT}


def source_read(directory, count_limit=video.MAX_FRAMES):
    probe_path, raw_path = directory / 'source-probe.stdout', directory / 'source-decoded.rgb'
    for path, limit in ((probe_path, video.MAX_PROBE), (raw_path, MAX_RGB)):
        if path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED', 'required regular source readback is absent', path.name)
        if path.stat().st_size > limit:
            fail('RESOURCE_LIMIT', 'source readback exceeds byte budget', path.name)
    width, height, count, rate = video.inspect(strict_json(probe_path.read_bytes(), probe_path.name), LOCATION + 'video')
    raw = raw_path.read_bytes()
    if len(raw) != count * width * height * 3:
        fail('VERIFICATION_FAILED', 'source decode count/dimensions differ from source probe')
    return width, height, count, rate, raw


def validate_probe(probe, width, height, count, rate, audio):
    """Exact three-stream membership and supported codec/pixel-format metadata of the published file."""
    try:
        streams = probe['streams']
        if not isinstance(streams, list) or len(streams) != 3 or not all(isinstance(s, dict) for s in streams):
            raise ValueError('expected exactly three streams: video, audio, subtitle')
        if [s['codec_type'] for s in streams] != ['video', 'audio', 'subtitle'] or [s['index'] for s in streams] != [0, 1, 2]:
            raise ValueError('stream order must be video, audio, subtitle')
        v, a, s = streams
        if (v['codec_name'] != 'ffv1' or v['pix_fmt'] != 'bgr0' or (v['width'], v['height']) != (width, height)
                or int(v['nb_read_frames']) != count or Fraction(v['avg_frame_rate']) != rate):
            raise ValueError('video stream is not FFV1 bgr0 with the captured dimensions, frame count and rate')
        if (a['codec_name'] != 'pcm_s16le' or a['sample_fmt'] != 's16' or a['bits_per_sample'] != 16
                or int(a['sample_rate']) != audio['sampleRate'] or a['channels'] != audio['channels']):
            raise ValueError('audio stream is not PCM16 with the captured rate and channels')
        if s['codec_name'] != 'subrip':
            raise ValueError('subtitle stream is not SubRip')
        for stream in streams:
            tags = stream.get('tags', {})
            if not isinstance(tags, dict) or set(tags) - {'DURATION'}:
                raise ValueError('streams must carry no tags beyond the container duration')
        form = probe['format']
        if not isinstance(form, dict) or form['format_name'] != 'matroska,webm' or form['nb_streams'] != 3 or form['nb_programs'] != 0:
            raise ValueError('container is not a three-stream Matroska file')
        # Timeline: the source video is constant-rate with no offset, so the published video and audio must start at zero.
        # The first caption may start later; a subtitle stream only has to report a finite, non-negative start.
        for name, stream in (('video', v), ('audio', a), ('container', form)):
            if seconds(stream['start_time']) != 0:
                raise ValueError('published %s starts at %s s; video and audio must start at 0 s (no audio/video offset)' % (name, stream['start_time']))
        if seconds(s['start_time']) < 0:
            raise ValueError('the subtitle stream starts before zero')
        span = max(Fraction(count) / rate, Fraction(audio['samples'], audio['sampleRate']))
        if abs(seconds(form['duration']) - span) > Fraction(1) / rate + TIMESTAMP_TOLERANCE:
            raise ValueError('container duration %s s differs from the captured media by more than one video frame' % form['duration'])
        if probe['chapters'] != [] or form.get('tags', {}) not in ({}, {'encoder': 'Lavf'}):
            raise ValueError('chapters and metadata must be absent')
    except (KeyError, ValueError, TypeError, ZeroDivisionError, AttributeError) as error:
        fail('VERIFICATION_FAILED', 'published file membership or metadata differs: ' + str(error), stage='probe')


def check_video(source, decoded, stride, count):
    if len(decoded) != len(source):
        fail('VERIFICATION_FAILED', 'decoded frame count or dimensions differ from the captured source', stage='decode')
    source, decoded = memoryview(source), memoryview(decoded)
    for index in range(count):
        a, b = source[index * stride:(index + 1) * stride], decoded[index * stride:(index + 1) * stride]
        if a != b:
            error = sum(abs(x - y) for x, y in zip(a, b)) / stride
            fail('VERIFICATION_FAILED', 'decoded video frame differs from the captured source frame', stage='decode', frame=index, meanError=error)


def assess(held, observed, published, fresh=False):
    """Rebuild every expectation from the held captured sources and compare the native readbacks in ``observed``.

    ``held`` is the three captured source payloads read once by the caller; ``published`` is the published review file as
    read once. ``observed`` is a directory of readbacks: the retained ones (no native launch) or, with ``fresh``, a private
    set produced by the trusted runtime from ``published`` (which adds the published video frame timeline)."""
    audio = parse_wav(held[1])
    cues = parse_srt(held[2])
    width, height, count, rate, raw = source_read(observed)
    clock = alignment(audio['samples'], audio['sampleRate'], count, rate, cues)
    if len(published) > MAX_OUTPUT:
        fail('RESOURCE_LIMIT', 'review file exceeds byte budget')
    names = [('probe.stdout', MAX_PROBE), ('decoded.rgb', MAX_RGB), ('decoded-audio.wav', MAX_READBACK_WAV), ('extracted.srt', MAX_CAPTION_BYTES * 2)]
    for name, limit in names + ([(TIMELINE + '.stdout', MAX_PROBE), (AUDIO_PACKETS + '.stdout', MAX_PACKET_PROBE)] if fresh else []):
        path = observed / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            fail('VERIFICATION_FAILED', 'required bounded native readback is absent or oversized', name)
    probe = strict_json((observed / 'probe.stdout').read_bytes(), 'probe.stdout')
    validate_probe(probe, width, height, count, rate, audio)
    if fresh:
        check_timeline(strict_json((observed / (TIMELINE + '.stdout')).read_bytes(), TIMELINE + '.stdout'), count, rate)
        check_audio_packets(strict_json((observed / (AUDIO_PACKETS + '.stdout')).read_bytes(), AUDIO_PACKETS + '.stdout'), audio)
    decoded = (observed / 'decoded.rgb').read_bytes()
    check_video(raw, decoded, width * height * 3, count)
    echo = parse_native_wav((observed / 'decoded-audio.wav').read_bytes())
    if (echo['channels'], echo['sampleRate'], echo['samples']) != (audio['channels'], audio['sampleRate'], audio['samples']) or echo['pcm'] != audio['pcm']:
        fail('VERIFICATION_FAILED', 'decoded PCM samples differ from the captured audio', stage='decode-audio')
    extracted = parse_srt((observed / 'extracted.srt').read_bytes(), 'extracted.srt')
    if extracted != cues:
        index = next((i for i, pair in enumerate(zip(cues, extracted)) if pair[0] != pair[1]), min(len(cues), len(extracted)))
        fail('VERIFICATION_FAILED', 'extracted caption cues differ from the captured captions in text or millisecond timing',
             stage='extract-captions', cue=index + 1, captured=len(cues), extracted=len(extracted))
    digests = {'review': hashlib.sha256(published).hexdigest(), 'sourceDecoded': hashlib.sha256(raw).hexdigest(),
               'decoded': hashlib.sha256(decoded).hexdigest(), 'decodedPCM': hashlib.sha256(echo['pcm']).hexdigest(),
               'cues': cue_digest(cues)}
    return {'width': width, 'height': height, 'frames': count, 'fps': int(rate), 'audio': audio, 'cues': cues, 'alignment': clock,
            'sizes': {'review': len(published)}, 'probe': probe, 'digests': digests}


def fact_view(facts):
    """The typed facts a fresh decode must reproduce: dimensions, timeline, alignment, cues, audio format and digests."""
    audio = facts['audio']
    return {'width': facts['width'], 'height': facts['height'], 'frames': facts['frames'], 'fps': facts['fps'],
            'alignment': facts['alignment'], 'cues': [list(cue) for cue in facts['cues']],
            'audio.channels': audio['channels'], 'audio.sampleRate': audio['sampleRate'], 'audio.samples': audio['samples'],
            'audio.bytes': audio['bytes'], **{'digest.' + name: value for name, value in facts['digests'].items()}}


def bind_fresh(retained, fresh_facts, receipt, rebuild):
    """Facts from the fresh decode must equal the retained readback facts and the retained receipt, by exact type."""
    before, now = fact_view(retained), fact_view(fresh_facts)
    differing = sorted(name for name in before if not same_json(before[name], now[name]))
    if differing:
        fail('VERIFICATION_FAILED', 'fresh native facts differ from the retained readbacks: ' + ', '.join(differing),
             stage='facts', differing=differing)
    core = {name: value for name, value in receipt.items() if name not in ('nativeReadback', 'sourceReadback')}
    if not same_json(core, rebuild(fresh_facts)):
        fail('VERIFICATION_FAILED', 'fresh native facts differ from the retained receipt', stage='facts')


def observed_fresh(action):
    """Run the fresh verification pass; any fault it raises is tagged ``observed.fresh = True``."""
    try:
        return action()
    except SchemaxisError as error:
        fault = error.fault
        raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase, fault.retryable,
                                   {**fault.to_dict()['observed'], 'fresh': True}, fault.recovery)) from None


def receipt_for(directory, prepared, facts, sources, runtime):
    options = prepared['nodes'][0]['options']
    review = directory / OUTPUT
    audio, cues, digests = facts['audio'], facts['cues'], facts['digests']
    frames, fps = facts['frames'], facts['fps']
    return {
        'artifacts': [{'file': str(review), 'kind': 'video', 'sha256': digests['review'], 'frames': frames,
                       'duration': frames / fps, 'dimensions': [facts['width'], facts['height']]}],
        'sources': sources, 'width': facts['width'], 'height': facts['height'], 'frames': frames, 'fps': fps,
        'duration': frames / fps,
        'streams': [{'index': 0, 'type': 'video', 'codec': 'ffv1', 'pixelFormat': 'bgr0'},
                    {'index': 1, 'type': 'audio', 'codec': 'pcm_s16le', 'channels': audio['channels'], 'sampleRate': audio['sampleRate']},
                    {'index': 2, 'type': 'subtitle', 'codec': 'subrip'}],
        'video': {'decodedSHA256': digests['decoded'], 'maximumMeanRGBError': 0, 'sourceDecodedSHA256': digests['sourceDecoded']},
        'audio': {'samples': audio['samples'], 'bytes': audio['bytes'], 'pcmSHA256': hashlib.sha256(audio['pcm']).hexdigest(),
                  'decodedPCMSHA256': digests['decodedPCM']},
        'alignment': facts['alignment'],
        'captions': {'cues': len(cues), 'firstStartMs': cues[0][0], 'lastEndMs': cues[-1][1], 'cueSHA256': digests['cues'],
                     'extractedSHA256': file_digest(directory / 'extracted.srt'),
                     'status': options['captionStatus'], 'statusBasis': 'declared by the author; not verified',
                     'recognitionAccuracyCertified': False, 'humanReviewVerified': False},
        'runtime': runtime, 'losses': prepared['losses']}


def fresh(stage, deadline):
    if cancellation_requested():
        fail('RUNNER_CANCELLED', 'review publication cancelled', stage)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        fail('RUNNER_TIMED_OUT', 'review publication exhausted the total timeout', stage)
    return remaining


def quiet(directory, stage):
    path = directory / (stage + '.stderr')
    text = path.read_bytes()[:video.MAX_DIAGNOSTIC].decode('utf-8', 'replace').strip() if path.is_file() else ''
    if text:
        raise SchemaxisError(Fault('RUNNER_FAILED', 'native stage reported diagnostics although it exited successfully',
            '$', 'pipeline', observed={'stage': stage, 'diagnostics': text.replace(str(directory), '<run>')},
            recovery='Inspect the retained stage diagnostics and the runtime, then retry in a fresh directory.'))


def run(prepared, directory, executable, deadline):
    """Publish and verify; any failure removes the unverified review file (best effort) before the fault propagates."""
    try:
        return publish(prepared, directory, executable, deadline)
    except Exception:
        try:
            (directory / OUTPUT).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def publish(prepared, directory, executable, deadline):
    from . import adaptor as base
    options = prepared['nodes'][0]['options']
    sources, payloads = base.read_sources(directory, prepared, True)
    # Host-only structure checks come first so malformed or unsupported assets never reach a native tool.
    video.check_source(payloads[0], options['video'], LOCATION + 'video')
    audio, cues = parse_wav(payloads[1]), parse_srt(payloads[2])
    pseudo = source_pseudo_plan(options)
    source_commands = video.commands(executable, directory, pseudo)
    for stage in SOURCE_STAGES:
        script = directory / (stage + '-launcher.py')
        script.write_text(base.readback_launcher(directory, pseudo, stage, source_commands[stage]))
        execute([sys.executable, str(script)], directory, stage, fresh(stage, deadline))
        video.check_diagnostics(directory, stage, LOCATION + 'video')
        if stage == 'source-probe' and (directory / 'source-probe.stdout').stat().st_size > video.MAX_PROBE:
            fail('RESOURCE_LIMIT', 'source probe exceeded byte budget')
    video.inspect(json.loads((directory / 'source-probe.stdout').read_text()), LOCATION + 'video')
    _width, _height, count, rate, _raw = source_read(directory)
    alignment(audio['samples'], audio['sampleRate'], count, rate, cues)
    command_set = commands(executable, directory, options)
    for stage in STAGES:
        script = directory / (stage + '-launcher.py')
        script.write_text(launcher(directory, stage, command_set[stage]))
        execute([sys.executable, str(script)], directory, stage, fresh(stage, deadline))
        quiet(directory, stage)
        if stage == 'encode' and (directory / OUTPUT).stat().st_size > MAX_OUTPUT:
            fail('RESOURCE_LIMIT', 'review file exceeds byte budget')
    execute(command_set['version'], directory, 'version', fresh('version', deadline))
    facts = assess(payloads, directory, bounded_bytes(directory / OUTPUT, MAX_OUTPUT, OUTPUT))
    version = (directory / 'version.stdout').read_text().splitlines()[0]
    receipt = receipt_for(directory, prepared, facts, sources, version)
    submissions = {stage: json.loads((directory / (stage + '-submission.json')).read_text()) for stage in (*STAGES, *SOURCE_STAGES)}
    receipt['nativeReadback'] = evidence(directory, command_set, submissions, tuple(STAGES))
    receipt['sourceReadback'] = base.readback_evidence(directory, pseudo, source_commands, submissions, SOURCE_STAGES, strict_text)
    atomic_json(directory / 'verification.json', receipt)
    result = outcome(receipt)
    # The run's own trusted executable also decodes the published bytes again in a private directory.
    verify(directory, prepared, {'ffmpeg': executable, 'ffprobe': str(Path(executable).with_name('ffprobe'))},
           require_result=False, deadline=deadline)
    fresh('verify', deadline)
    atomic_json(directory / 'result.json', result)
    return result


def outcome(receipt):
    return {'status': 'succeeded', 'verified': True, 'artifacts': 1, 'video': receipt['artifacts'][0]['file'],
            'streams': len(receipt['streams']), 'alignment': receipt['alignment'], 'captionStatus': receipt['captions']['status'],
            'recognitionAccuracyCertified': False, 'humanReviewVerified': False}


def bounded_bytes(path, limit, name):
    """One bounded read of a regular, non-symlink file; the bytes read are the bytes judged."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('not a regular file within %d bytes' % limit)
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('byte budget exceeded')
        return data
    except (OSError, ValueError) as error:
        fail('VERIFICATION_FAILED', 'required bounded regular file is unavailable: ' + str(error)[:80], name)


def budget(stage, deadline):
    """Per-launch time: the stage cap, the enclosing execution deadline and cancellation, and the run deadline if any."""
    remaining = remaining_timeout(STAGE_TIMEOUT)
    return remaining if deadline is None else min(remaining, fresh(stage, deadline))


def launch(scratch, stage, script, deadline):
    """One fixed launcher through the shared cancellable runner; native failure means the bytes do not verify."""
    path = scratch / (stage + '-launcher.py')
    path.write_text(script)
    try:
        execute([sys.executable, str(path)], scratch, stage, budget(stage, deadline))
        if stage in SOURCE_STAGES:
            video.check_diagnostics(scratch, stage, LOCATION + 'video')
        else:
            quiet(scratch, stage)
    except SchemaxisError as error:
        if error.fault.code not in ('RUNNER_FAILED', 'INVALID_RESOURCE'):
            raise    # timeout, cancellation and unavailable-runtime faults keep their own codes
        fail('VERIFICATION_FAILED', 'fresh native %s of the retained bytes failed: %s' % (stage, error.fault.message), stage,
             cause=error.fault.to_dict())


def hold_sources(directory, prepared):
    """Read all three captured sources exactly once; the held bytes are what every later check judges.

    The captured copies in the run directory are the trust anchor: the original authored paths are never resolved again."""
    from . import adaptor as base
    paths = video.source_paths(prepared['nodes'][0])
    held = [base.source_bytes(directory / f'input-{index:04d}') for index in range(len(paths))]
    if sum(map(len, held)) > MAX_RGB:
        fail('RESOURCE_LIMIT', 'input byte budget exceeded')
    return [{'file': path, 'retained': f'input-{index:04d}', 'sha256': hashlib.sha256(data).hexdigest()}
            for index, (path, data) in enumerate(zip(paths, held))], held


def fresh_observation(directory, prepared, paths, held, published, deadline):
    """Decode the exact published bytes and the captured video again with the trusted runtime, in a private directory.

    Expectations come from the held captured sources; nothing retained by the run is consulted. Returns the fresh facts and
    the identity line of the trusted FFmpeg."""
    options = prepared['nodes'][0]['options']
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-ffmpeg-review-'))
    try:
        if directory.resolve() in scratch.resolve().parents or scratch.resolve() in directory.resolve().parents:
            fail('VERIFICATION_FAILED', 'the private verification directory must not overlap the submitted directory', str(scratch))
        (scratch / 'input-0000').write_bytes(held[0])
        (scratch / OUTPUT).write_bytes(published)
        pseudo = source_pseudo_plan(options)
        from . import adaptor as base
        recipe = {**commands(paths['ffmpeg'], scratch, options), **video.commands(paths['ffmpeg'], scratch, pseudo)}
        execute(recipe['version'], scratch, 'version', budget('version', deadline))
        identity = (scratch / 'version.stdout').read_text(errors='replace').splitlines()[:1]
        if not identity or not identity[0].startswith('ffmpeg version '):
            fail('UNSUPPORTED_RUNTIME', 'the trusted executable does not identify as FFmpeg', 'version', observed=identity[:1])
        for stage in SOURCE_STAGES:
            launch(scratch, stage, base.readback_launcher(scratch, pseudo, stage, recipe[stage]), deadline)
        for stage in (*(stage for stage in STAGES if stage != 'encode'), *FRESH_ONLY):
            launch(scratch, stage, launcher(scratch, stage, recipe[stage]), deadline)
        # Each stage opened exactly the held bytes, never a file swapped in after they were read.
        for stage, digests in (('source-probe', {'input-0000': held[0]}), ('source-decode', {'input-0000': held[0]}),
                               *((stage, {OUTPUT: published}) for stage in (*STAGES, *FRESH_ONLY) if stage != 'encode')):
            expected = {str(scratch / name): hashlib.sha256(data).hexdigest() for name, data in digests.items()}
            if not same_json(strict_json((scratch / (stage + '-inputs.json')).read_bytes(), stage + '-inputs.json'), expected):
                fail('VERIFICATION_FAILED', 'fresh native stage consumed different bytes than were verified', stage)
        facts = assess(held, scratch, published, fresh=True)
        return facts, identity[0]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def verify(directory, prepared, paths=None, require_result=True, deadline=None, executable=None):
    """Judge the published bytes by decoding them again with a trusted runtime, from the captured sources.

    Fresh decision (trusted FFmpeg and sibling ffprobe from the explicit argument, stored configuration or the
    environment; never a path from a receipt, submission or PATH): in a private temporary directory, the captured
    video, the published review file, its probe, video decode, audio decode and caption extraction are produced again
    with fixed arguments; expectations are derived from the captured WAV, SRT and video; the published bytes read once
    must reproduce every frame, PCM byte and cue and have the exact three-stream membership.
    Retained files are strictly parsed, typed-compared consistency diagnostics (launchers, bindings, exit codes, readbacks,
    receipt and, when required, the result record); retained commands are data and are never launched.
    Limit: the published container bytes are judged by decoding and membership, not by byte-for-byte remuxing."""
    from . import adaptor as base
    directory = Path(directory).absolute()
    try:
        with execution_deadline(VERIFY_TIMEOUT):
            def read(name):
                path = directory / name
                if path.is_symlink() or not path.is_file():
                    fail('VERIFICATION_FAILED', 'required regular file is absent', name)
                value = strict_json(bounded_bytes(path, MAX_EVIDENCE, name), name)
                if not isinstance(value, dict):
                    fail('VERIFICATION_FAILED', 'expected an evidence object', name)
                return value
            if not same_json(read('authored.json'), json.loads((directory / 'authored.json').read_text())):
                fail('VERIFICATION_FAILED', 'retained authored input is not typed-equal to its decoded form', 'authored.json')
            if not same_json(read('plan.json'), prepared):
                fail('VERIFICATION_FAILED', 'plan differs')
            receipt = read('verification.json')
            result = read('result.json')
            if require_result and (result.get('status') != 'succeeded' or result.get('verified') is not True):
                fail('INCOMPLETE_EXECUTION', 'video did not complete')
            paths = paths or trusted(executable)
            required = ['version.stdout', 'source-probe.stdout', 'source-decoded.rgb', OUTPUT, *STAGES.values(),
                        *[f'input-000{i}' for i in range(3)]]
            for name in required:
                path = directory / name
                if path.is_symlink() or not path.is_file():
                    fail('VERIFICATION_FAILED', 'required regular file is absent', name)
            options = prepared['nodes'][0]['options']
            published = bounded_bytes(directory / OUTPUT, MAX_OUTPUT, OUTPUT)
            published_digest = hashlib.sha256(published).hexdigest()
            # All three captured sources are held once; the retained and the fresh pass both judge these bytes.
            sources, held = hold_sources(directory, prepared)
            # Retained-run consistency: readbacks, launchers and bindings agree with the captured sources and the receipt.
            facts = assess(held, directory, published)
            submissions = {stage: read(stage + '-submission.json') for stage in (*STAGES, *SOURCE_STAGES, 'version')}
            version = submissions['version'].get('nativeCommand')
            if (not isinstance(version, list) or len(version) != 2 or version[1] != '-version' or not isinstance(version[0], str)
                    or not Path(version[0]).is_absolute()):
                fail('VERIFICATION_FAILED', 'missing absolute FFmpeg command evidence', 'version')
            # The recorded path only reconstructs the retained command text for comparison; it is never executed.
            command_set = commands(version[0], directory, options)
            pseudo = source_pseudo_plan(options)
            command_set.update(video.commands(version[0], directory, pseudo))
            for stage, submission in submissions.items():
                if type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                    fail('VERIFICATION_FAILED', 'native stage did not complete', stage)
                if stage == 'version' and submission.get('nativeCommand') != command_set['version']:
                    fail('VERIFICATION_FAILED', 'native stage command differs', stage)
            expected = receipt_for(directory, prepared, facts, sources, (directory / 'version.stdout').read_text().splitlines()[0])
            expected['nativeReadback'] = evidence(directory, command_set, submissions, tuple(STAGES))
            expected['sourceReadback'] = base.readback_evidence(directory, pseudo, command_set, submissions, SOURCE_STAGES, strict_text)
            if not same_json(receipt, expected):
                fail('VERIFICATION_FAILED', 'review evidence differs')
            if receipt['artifacts'][0]['sha256'] != published_digest:
                fail('VERIFICATION_FAILED', 'published review file differs from the bytes verified in this call', OUTPUT)
            # Fresh decision from the trusted runtime; its facts must reproduce the retained readbacks and receipt.
            def decide():
                found, line = fresh_observation(directory, prepared, paths, held, published, deadline)
                bind_fresh(facts, found, receipt, lambda value: receipt_for(directory, prepared, value, sources, receipt['runtime']))
                return found, line
            fresh_facts, identity = observed_fresh(decide)
            if (file_digest(directory / OUTPUT) != published_digest
                    or [hashlib.sha256(base.source_bytes(directory / record['retained'])).hexdigest() for record in sources]
                    != [record['sha256'] for record in sources]):
                fail('VERIFICATION_FAILED', 'the published review or a captured source changed while it was being verified', OUTPUT)
            if require_result and not same_json(result, outcome(expected)):
                fail('VERIFICATION_FAILED', 'retained result claims differ from the verified outcome', 'result.json')
            return {'verified': True, 'artifacts': 1, 'frames': fresh_facts['frames'], 'duration': fresh_facts['frames'] / fresh_facts['fps'],
                    'runtime': receipt['runtime'], 'streams': 3, 'alignment': fresh_facts['alignment'],
                    'captionStatus': receipt['captions']['status'], 'recognitionAccuracyCertified': False,
                    'humanReviewVerified': False, 'nativeReadbackBound': True, 'freshNativeVerification': True,
                    'freshRuntime': identity}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained review evidence: %s %s' % (type(error).__name__, str(error)[:80]))
