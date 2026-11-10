"""Verified AAC audio extraction: one captured MP4/M4A to a canonical PCM16 WAV.

``extractAudio`` captures one local MP4/M4A file, refuses every stream, box and codec profile outside a small bounded subset
(one AAC-LC audio stream, optionally one H.264 video stream), counts the decoded audio frames with a bounded ffprobe pass, and
decodes the selected stream natively to PCM16 at the source rate and channel count. The host builds the 44-byte canonical WAV
itself. Verification decodes the captured compressed bytes again in a private directory with the trusted FFmpeg and sibling
ffprobe and compares every PCM byte with the published WAV. AAC is lossy: nothing here claims equality with the recording that
was encoded, recognition accuracy or human review, and the capture is an unauthenticated trust anchor."""
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import struct
import sys
import tempfile
import time

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import execution_deadline
from schemaxis.errors import fail
from schemaxis.native_command import execute
from . import review, video

OUTPUT = 'audio.wav'
SUMMARY = 'audio-summary.json'
SUMMARY_VERSION = 'schemaxis.ffmpeg.audio-summary/1'
LOCATION = '$.nodes[0].options.'
MAX_SOURCE = 64 * 1024 * 1024
MAX_SECONDS = 600
MAX_WAV = 32 * 1024 * 1024
HEADER = 44
MAX_PCM = MAX_WAV - HEADER
# The smallest AAC-LC frame is 960 samples (FFmpeg decodes 1024 or 960): a mono 32 MiB WAV holds at most 17476 of them, so no
# accepted source lists more decoded audio frames than this.
MAX_FRAMES = 17500
# ffprobe's interval counts packets, and packets the edit list trims (the priming packet) decode to no frame. The frame listing is
# only complete when the stream holds no more packets than this bound, so more packets are refused as a probe-bound RESOURCE_LIMIT
# rather than counted partially. Sources with a very long edit-list lead-in can reach this bound before the 32 MiB WAV limit.
MAX_PACKETS = MAX_FRAMES + 100
MAX_PROBE = 4 * 1024 * 1024
MAX_EVIDENCE = 1024 * 1024
OUTPUT_SLACK = 4096
STAGE_TIMEOUT = 120
VERIFY_TIMEOUT = 300
RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000)
BRANDS = (b'isom', b'iso2', b'mp41', b'mp42', b'M4A ', b'M4V ')
CONTAINERS = (b'moov', b'trak', b'mdia', b'minf', b'dinf')
STAGES = ('source-probe', 'source-frames', 'decode')
SOURCE_FAULTS = ('INVALID_RESOURCE', 'UNSUPPORTED_AUDIO', 'RESOURCE_LIMIT', 'INVALID_ARGUMENT')
# Faults a native stage can raise that verification reports as a failed fresh stage; timeouts, cancellation and unavailable runtimes
# keep their own codes.
STAGE_FAULTS = ('RUNNER_FAILED', 'INVALID_RESOURCE', 'NATIVE_EXECUTION_FAILED', 'RESOURCE_LIMIT')
PRODUCED = {'source-probe': 'source-probe.stdout', 'source-frames': 'source-frames.stdout', 'decode': 'decoded.wav'}
POLICY = ('One AAC-LC stream selected by global streamIndex 0..15; the decoded frame count is the sum of the decoded audio-frame '
          'sample counts reported by ffprobe, with contiguous timestamps from zero, and must equal the native PCM frame count; '
          'no resampling, mixing, trimming, padding or silent truncation.')
LOSSES = ['AAC is lossy: the PCM16 WAV is a native FFmpeg decode of the compressed stream, not the recording that was encoded; '
          'no equality with an uncompressed original is claimed',
          'the native decoder output is a machine draft; speech recognition accuracy and human review are not certified',
          'the sample rate and channel count are those of the AAC stream; no resampling or channel mixing; encoder priming and '
          'padding follow the container edit list as applied by FFmpeg 9 and are counted, not assumed',
          'metadata, chapters, cover art, video and every other stream are dropped; the capture is an unauthenticated local file']


def trusted(executable=None):
    """review.trusted with extractAudio wording: explicit argument, stored configuration, environment; never PATH or receipts."""
    try:
        return review.trusted(executable)
    except SchemaxisError as error:
        fault = error.fault
        raise SchemaxisError(Fault(fault.code, fault.message.replace('verifying a muxReview publication', 'running or verifying an extractAudio publication'),
                                   fault.location, fault.phase, fault.retryable, fault.to_dict()['observed'],
                                   (fault.recovery or '').replace('Pass executable= to verify', 'Pass executable= (--executable or --ffmpeg) to run or verify', 1))) from None


def plan(document, identity, options):
    if 'deliverable' in document:
        fail('INVALID_ARGUMENT', 'extractAudio verifies its own audio geometry; deliverable is not accepted', '$.deliverable')
    path = options['file']
    if '\0' in path or not Path(path).is_absolute():
        fail('INVALID_RESOURCE', 'input paths must be absolute and contain no NUL', LOCATION + 'file')
    if Path(path).suffix.lower() not in ('.mp4', '.m4a'):
        fail('UNSUPPORTED_AUDIO', 'use an absolute .mp4 or .m4a source path', LOCATION + 'file')
    return {'version': 'schemaxis.ffmpeg.plan/1', 'nodes': [{'id': identity, 'filter': 'extractAudio', 'options': options}],
            'output': OUTPUT, 'summary': SUMMARY, 'losses': LOSSES, 'policy': POLICY}


# ---------------------------------------------------------------- host-side container checks (no native process)
def read_source(path, limit=None):
    """Bounded read of one local regular file; devices and FIFOs are refused before opening and the descriptor is rechecked."""
    limit = MAX_SOURCE if limit is None else limit
    try:
        if not stat.S_ISREG(Path(path).stat().st_mode):
            fail('INVALID_RESOURCE', 'input must be a regular file', str(path))
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                fail('INVALID_RESOURCE', 'input must be a regular file', str(path))
            if info.st_size > limit:
                fail('RESOURCE_LIMIT', 'compressed input exceeds %d MiB' % (limit >> 20), str(path))
            data = stream.read(limit + 1)
    except (OSError, ValueError) as error:
        fail('RESOURCE_NOT_FOUND', str(error), str(path))
    if len(data) > limit:
        fail('RESOURCE_LIMIT', 'compressed input exceeds %d MiB' % (limit >> 20), str(path))
    return data


def boxes(data, start, end):
    """ISO base media boxes within [start, end): ``(type, payload start, box end)``; malformed sizes are named."""
    position = start
    while position < end:
        if end - position < 8:
            fail('INVALID_RESOURCE', 'truncated MP4 box header', LOCATION + 'file', offset=position)
        size, kind = struct.unpack('>I4s', data[position:position + 8])
        header = 8
        if size == 1:
            if end - position < 16:
                fail('INVALID_RESOURCE', 'truncated MP4 64-bit box header', LOCATION + 'file', offset=position)
            size, header = struct.unpack('>Q', data[position + 8:position + 16])[0], 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            fail('INVALID_RESOURCE', 'MP4 box %r extends beyond the file (truncated or corrupt)' % kind.decode('latin-1'),
                 LOCATION + 'file', offset=position)
        yield kind, position + header, position + size
        position += size


def references(data, start, end, depth=0):
    """Reject data references that are not self-contained: the demuxer is also told not to follow them."""
    if depth > 8:
        fail('INVALID_RESOURCE', 'MP4 box nesting is too deep', LOCATION + 'file')
    for kind, payload, stop in boxes(data, start, end):
        if kind in CONTAINERS:
            references(data, payload, stop, depth + 1)
        elif kind == b'dref':
            if stop - payload < 8:
                fail('INVALID_RESOURCE', 'truncated MP4 data reference box', LOCATION + 'file')
            for entry, body, _ in boxes(data, payload + 8, stop):
                if entry not in (b'url ', b'urn ') or stop - body < 4 or not data[body + 3] & 1:
                    fail('UNSUPPORTED_AUDIO', 'external or unrecognised MP4 data reference; only self-contained media is accepted',
                         LOCATION + 'file', entry=entry.decode('latin-1'))


def check_structure(data):
    """Native-free MP4/M4A structure: ftyp first, known brand, intact box sizes, one moov, mdat, not fragmented, self-contained."""
    found = list(boxes(data, 0, len(data)))
    kinds = [kind for kind, _, _ in found]
    if not found or kinds[0] != b'ftyp' or found[0][2] - found[0][1] < 8:
        fail('INVALID_RESOURCE', 'source bytes are not an MP4/M4A file (no leading ftyp box)', LOCATION + 'file', bytes=len(data))
    brand = data[found[0][1]:found[0][1] + 4]
    if brand not in BRANDS:
        fail('UNSUPPORTED_AUDIO', 'unsupported MP4 brand %r; use isom, iso2, mp41, mp42, M4A or M4V' % brand.decode('latin-1'),
             LOCATION + 'file')
    if kinds.count(b'moov') != 1 or b'mdat' not in kinds:
        fail('INVALID_RESOURCE', 'MP4 needs exactly one moov box and an mdat box (incomplete or damaged file)', LOCATION + 'file')
    if any(kind in (b'moof', b'sidx', b'mfra') for kind in kinds):
        fail('UNSUPPORTED_AUDIO', 'fragmented MP4 is not supported', LOCATION + 'file')
    for kind, payload, stop in found:
        if kind == b'moov':
            references(data, payload, stop)
    return {'brand': brand.decode('latin-1'), 'boxes': [kind.decode('latin-1') for kind in kinds]}


# ---------------------------------------------------------------- native recipe
def commands(executable, directory, options):
    """The fixed recipe: forced mov demuxer, file protocol only, no external references, no authored flags."""
    probe = str(Path(executable).with_name('ffprobe'))
    source = str(directory / 'input-0000')
    reopen = ['-protocol_whitelist', 'file', '-f', 'mov']
    fixed = ['-enable_drefs', '0', '-use_absolute_path', '0']
    return {
        'version': [executable, '-version'],
        'source-probe': [probe, '-v', 'error', *reopen, *fixed, '-show_streams', '-show_format', '-show_chapters', '-show_programs',
                         '-of', 'json', source],
        'source-frames': [probe, '-v', 'error', *reopen, *fixed, '-select_streams', str(options['streamIndex']), '-read_intervals',
                          '%%+#%d' % MAX_PACKETS, '-show_frames', '-show_entries', 'frame=pts,nb_samples', '-of', 'json', source],
        'decode': [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-filter_threads', '1',
                   '-threads', str(options['threads']), *reopen, *fixed, '-i', source, '-map', '0:%d' % options['streamIndex'],
                   '-vn', '-sn', '-dn', '-map_metadata', '-1', '-map_chapters', '-1', '-c:a', 'pcm_s16le',
                   '-fflags', '+bitexact', '-f', 'wav', str(directory / 'decoded.wav')],
    }


def limit_for(stage, facts=None):
    """Kernel file-size cap of a stage's output. Probe output over MAX_PROBE bytes is over the host reader's budget, so the cap is one
    byte more: output of exactly MAX_PROBE completes, and a file that reaches the cap is refused rather than read truncated."""
    if stage == 'decode':
        return facts['frames'] * facts['channels'] * 2 + OUTPUT_SLACK
    return MAX_PROBE + 1


def launcher(directory, stage, command, limit):
    """Bind the stage to the digest of the exact file it opens, apply resource limits, then exec the fixed argv."""
    path = directory / 'input-0000'
    return ('import hashlib, json, os, resource, stat\nfrom pathlib import Path\n'
            + 'resource.setrlimit(resource.RLIMIT_AS, (2147483648,)*2)\n'
            + f'resource.setrlimit(resource.RLIMIT_FSIZE, ({limit},)*2)\n'
            + 'resource.setrlimit(resource.RLIMIT_CPU, (300,)*2)\nresource.setrlimit(resource.RLIMIT_CORE, (0,)*2)\n'
            + f'path=Path({str(path)!r})\ncommand={command!r}\n'
            + 'if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode): raise ValueError("native input is not regular")\n'
            + 'digest=hashlib.sha256()\nwith path.open("rb") as stream:\n'
            + '    for block in iter(lambda:stream.read(1048576), b""): digest.update(block)\n'
            + f'Path({str(directory / (stage + "-inputs.json"))!r}).write_text(json.dumps({{str(path):digest.hexdigest()}},sort_keys=True))\n'
            + 'os.execvpe(command[0],command,os.environ)\n')


def converted(verifying, action, what):
    """Source refusals found while verifying retained bytes are verification failures, never input faults."""
    try:
        return action()
    except SchemaxisError as error:
        if not verifying or error.fault.code not in SOURCE_FAULTS:
            raise
        fail('VERIFICATION_FAILED', 'retained %s no longer satisfies the extractAudio subset (%s): %s'
             % (what, error.fault.code, error.fault.message), what, cause=error.fault.to_dict())


def reached_cap(directory, stage, limit, failure=None):
    """True when the stage's output file reached its kernel file-size cap, or the stage was killed by the file-size signal.

    The launcher is a Python process, which ignores SIGXFSZ, and the exec'd native child inherits that: a capped stage normally gets
    EFBIG, leaves truncated output and may still exit zero. The file size is therefore the primary signal, the exit status secondary."""
    path = directory / PRODUCED[stage]
    if not path.is_symlink() and path.is_file() and path.stat().st_size >= limit:
        return True
    return failure is not None and failure.fault.to_dict()['observed'].get('exitCode') == -signal.SIGXFSZ


def cap_fault(stage, limit):
    """A stage that hit its output cap was refused, never truncated: a bounded-probe limit says nothing about the source's validity."""
    if stage == 'decode':
        return SchemaxisError(Fault('RESOURCE_LIMIT', 'the native decode is larger than the audio-frame probe counted (%d bytes of output '
            'allowed); it was refused, not truncated' % limit, LOCATION + 'file', 'pipeline', observed={'stage': stage, 'limitBytes': limit},
            recovery='The decoded audio exceeds the counted frames, so the bounded frame listing cannot be trusted for this source. '
                     'Use a shorter source (the listing bounds are %d packets and %d decoded frames); this is not evidence that the '
                     'source is invalid.' % (MAX_PACKETS, MAX_FRAMES)))
    return SchemaxisError(Fault('RESOURCE_LIMIT', 'ffprobe output for %s exceeded the %d-byte probe budget (for example very large metadata '
        'tags); it was refused, not truncated' % (stage, MAX_PROBE), LOCATION + 'file', 'pipeline',
        observed={'stage': stage, 'limitBytes': MAX_PROBE},
        recovery='Remove or shorten large metadata tags (re-mux the audio without them) or use a smaller source. This is a bounded-probe '
                 'limit, not evidence that the source is invalid.'))


def diagnose(directory, stage, failure):
    """A nonzero native exit raises before any diagnostics are read: classify its stderr exactly as a zero exit would be.

    Source-reading diagnostics become INVALID_RESOURCE; loader, allocation and unclassified output stay RUNNER_FAILED (source validity
    was not established); no stderr at all re-raises the original runner fault."""
    path = directory / (stage + '.stderr')
    if not path.is_symlink() and path.is_file() and path.stat().st_size:
        video.check_diagnostics(directory, stage, LOCATION + 'file')
    raise failure


def produced_nothing(directory, stage):
    """A zero exit that wrote no output examined nothing; it says nothing about whether the source is valid."""
    path = directory / PRODUCED[stage]
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise SchemaxisError(Fault('RUNNER_FAILED', 'native stage %s exited successfully but produced no output' % stage, LOCATION + 'file',
            'pipeline', observed={'stage': stage, 'output': PRODUCED[stage]},
            recovery='Inspect the retained stage logs and the configured runtime/environment, then retry in a fresh directory; source '
                     'validity was not established.'))


def launch(directory, stage, command, limit, deadline, verifying):
    script = directory / (stage + '-launcher.py')
    script.write_text(launcher(directory, stage, command, limit))
    try:
        failure = None
        try:
            execute([sys.executable, str(script)], directory, stage, review.budget(stage, deadline))
        except SchemaxisError as error:
            if error.fault.code != 'RUNNER_FAILED':
                raise    # timeout, cancellation and unavailable-runtime faults keep their own codes
            failure = error
        if reached_cap(directory, stage, limit, failure):    # before any source diagnostic: a killed stage says nothing about the source
            raise cap_fault(stage, limit)
        if failure is not None:
            diagnose(directory, stage, failure)
        video.check_diagnostics(directory, stage, LOCATION + 'file')
        produced_nothing(directory, stage)
    except SchemaxisError as error:
        if verifying and error.fault.code in STAGE_FAULTS:
            fail('VERIFICATION_FAILED', 'fresh native %s of the retained bytes failed: %s' % (stage, error.fault.message), stage,
                 cause=error.fault.to_dict())
        raise


def bound_input(directory, stage, data):
    expected = {str(directory / 'input-0000'): hashlib.sha256(data).hexdigest()}
    path = directory / (stage + '-inputs.json')
    if not review.same_json(review.strict_json(review.bounded_bytes(path, MAX_EVIDENCE, path.name), path.name), expected):
        fail('VERIFICATION_FAILED', 'native stage consumed different bytes than were verified', stage)


# ---------------------------------------------------------------- stream and frame facts
def integer(value, name):
    if type(value) is not int:
        raise ValueError('%s must be an integer' % name)
    return value


def inspect(probe, listing, index):
    """Validate the stream set and the complete audio-frame timeline before any decode; returns the source geometry."""
    where = LOCATION + 'streamIndex'
    try:
        streams, form = probe['streams'], probe['format']
        if not isinstance(streams, list) or not isinstance(form, dict) or not 1 <= len(streams) <= 2:
            fail('UNSUPPORTED_AUDIO', 'source must hold one AAC audio stream and optionally one H.264 video stream', where)
        if form.get('nb_streams') != len(streams) or 'mp4' not in str(form.get('format_name')):
            fail('UNSUPPORTED_AUDIO', 'source is not an MP4/M4A container with the probed streams', where)
        if probe.get('chapters') or probe.get('programs'):
            fail('UNSUPPORTED_AUDIO', 'chapters and programs are not supported; nothing is selected implicitly', where)
        if index >= len(streams):
            fail('INVALID_ARGUMENT', 'streamIndex %d does not exist; the source has %d stream(s)' % (index, len(streams)), where,
                 streams=[s.get('codec_type') for s in streams])
        if not isinstance(streams[index], dict) or streams[index].get('codec_type') != 'audio':
            fail('INVALID_ARGUMENT', 'streamIndex %d is not an audio stream' % index, where,
                 audioIndex=[s.get('index') for s in streams if isinstance(s, dict) and s.get('codec_type') == 'audio'])
        listed = []
        for position, stream in enumerate(streams):
            if not isinstance(stream, dict) or stream.get('index') != position:
                fail('UNSUPPORTED_AUDIO', 'stream indices must be contiguous from zero', where)
            kind, codec = stream.get('codec_type'), stream.get('codec_name')
            listed.append({'index': position, 'type': kind, 'codec': codec})
            if position != index and not (kind == 'video' and codec == 'h264' and (stream.get('disposition') or {}).get('attached_pic') == 0):
                fail('UNSUPPORTED_AUDIO', 'stream %d (%s/%s) is not the selected audio or the single permitted H.264 video; '
                     'extra audio, subtitle, data and cover-art streams are refused rather than ignored' % (position, kind, codec), where)
        audio = streams[index]
        if audio.get('codec_name') != 'aac' or audio.get('profile') != 'LC' or audio.get('codec_tag_string') != 'mp4a':
            fail('UNSUPPORTED_AUDIO', 'only AAC-LC (mp4a) audio is supported', where, codec=audio.get('codec_name'),
                 profile=audio.get('profile'))
        rate, channels = int(audio['sample_rate']), integer(audio['channels'], 'channels')
        if rate not in RATES or channels not in (1, 2):
            fail('UNSUPPORTED_AUDIO', 'only mono or stereo AAC at the standard rates from 8000 to 96000 Hz is supported', where,
                 sampleRate=rate, channels=channels)
        if audio.get('time_base') != '1/%d' % rate or audio.get('start_pts') != 0:
            fail('UNSUPPORTED_AUDIO', 'the audio stream must start at zero in a 1/sample-rate time base (no start offset)', where,
                 timeBase=audio.get('time_base'), startPts=audio.get('start_pts'))
        packets = audio['nb_frames']
        if not isinstance(packets, str) or not packets.isascii() or not packets.isdigit():
            raise ValueError('nb_frames must be a decimal packet count')
        if int(packets) > MAX_PACKETS:
            fail('RESOURCE_LIMIT', 'the selected stream holds more than %d packets, the bound within which the audio-frame listing is '
                 'complete; this is a probe limit, not evidence that the source is invalid' % MAX_PACKETS, where,
                 packets=int(packets), packetBound=MAX_PACKETS)
        frames = listing['frames']
        if not isinstance(frames, list) or not frames:
            fail('UNSUPPORTED_AUDIO', 'the selected stream decodes no audio frames', where)
        if len(frames) > MAX_FRAMES:
            fail('RESOURCE_LIMIT', 'more than %d decoded audio frames; the canonical WAV would exceed 32 MiB' % MAX_FRAMES, where)
        position = 0
        for frame in frames:
            samples = integer(frame['nb_samples'], 'nb_samples')
            if integer(frame['pts'], 'pts') != position or not 1 <= samples <= 2048:
                fail('UNSUPPORTED_AUDIO', 'decoded audio frames must be contiguous from timestamp zero (gap, overlap or offset found)',
                     where, expectedPts=position, pts=frame['pts'])
            position += samples
        if position > MAX_SECONDS * rate:
            fail('RESOURCE_LIMIT', 'audio is longer than %d seconds' % MAX_SECONDS, where, frames=position, sampleRate=rate)
        if position * channels * 2 > MAX_PCM:
            fail('RESOURCE_LIMIT', 'the canonical WAV would exceed 32 MiB', where, frames=position)
        return {'sampleRate': rate, 'channels': channels, 'frames': position, 'streams': listed}
    except SchemaxisError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        fail('UNSUPPORTED_AUDIO', 'unreadable stream facts: %s' % str(error)[:80], where)


def canonical_wav(rate, channels, pcm):
    align = 2 * channels
    return (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, channels, rate, rate * align, align, 16)
            + b'data' + struct.pack('<I', len(pcm)) + bytes(pcm))


def peaks(pcm, channels):
    samples = array('h')
    samples.frombytes(bytes(pcm))
    if sys.byteorder == 'big':
        samples.byteswap()
    return [min(samples[c::channels]) for c in range(channels)], [max(samples[c::channels]) for c in range(channels)]


def observe(directory, paths, options, capture, deadline, verifying):
    """Decode the held captured bytes in ``directory`` and return the facts, canonical WAV and runtime identity."""
    recipe = commands(paths['ffmpeg'], directory, options)
    execute(recipe['version'], directory, 'version', review.budget('version', deadline))
    identity = (directory / 'version.stdout').read_text(errors='replace').splitlines()[:1]
    if not identity or not identity[0].startswith('ffmpeg version '):
        fail('UNSUPPORTED_RUNTIME', 'the trusted executable does not identify as FFmpeg', 'version', observed=identity[:1])
    for stage in STAGES[:2]:
        launch(directory, stage, recipe[stage], limit_for(stage), deadline, verifying)
        bound_input(directory, stage, capture)
    probe = review.strict_json(review.bounded_bytes(directory / 'source-probe.stdout', MAX_PROBE, 'source-probe.stdout'), 'source-probe.stdout')
    listing = review.strict_json(review.bounded_bytes(directory / 'source-frames.stdout', MAX_PROBE, 'source-frames.stdout'), 'source-frames.stdout')
    facts = converted(verifying, lambda: inspect(probe, listing, options['streamIndex']), 'input-0000')
    launch(directory, 'decode', recipe['decode'], limit_for('decode', facts), deadline, verifying)
    bound_input(directory, 'decode', capture)
    expected = facts['frames'] * facts['channels'] * 2
    native = review.parse_native_wav(review.bounded_bytes(directory / 'decoded.wav', expected + OUTPUT_SLACK, 'decoded.wav'), 'decoded.wav')
    if (native['sampleRate'], native['channels']) != (facts['sampleRate'], facts['channels']) or native['bytes'] != expected:
        fail('VERIFICATION_FAILED' if verifying else 'UNSUPPORTED_AUDIO',
             'native decode produced %d PCM frames at %d Hz x %d but the audio-frame probe counted %d at %d Hz x %d (partial, '
             'truncated or edit-list-dependent decode)' % (native['samples'], native['sampleRate'], native['channels'],
                                                           facts['frames'], facts['sampleRate'], facts['channels']), 'decode')
    pcm = native['pcm']
    return {'facts': facts, 'pcm': bytes(pcm), 'wav': canonical_wav(facts['sampleRate'], facts['channels'], pcm), 'identity': identity[0]}


# ---------------------------------------------------------------- summary, receipt and result
def sha(data):
    return hashlib.sha256(data).hexdigest()


def summarize(options, capture, structure, observation):
    facts, pcm, wav = observation['facts'], observation['pcm'], observation['wav']
    low, high = peaks(pcm, facts['channels'])
    return {'version': SUMMARY_VERSION, 'operation': 'extractAudio',
            'source': {'file': 'input-0000', 'container': 'mp4', 'brand': structure['brand'], 'bytes': len(capture), 'sha256': sha(capture),
                       'streams': facts['streams']},
            'capturedAudio': {'streamIndex': options['streamIndex'], 'codec': 'aac', 'profile': 'LC', 'lossy': True},
            'audio': {'sampleRate': facts['sampleRate'], 'channels': facts['channels'], 'bitsPerSample': 16, 'frames': facts['frames'],
                      'durationSeconds': facts['frames'] / facts['sampleRate']},
            'pcm': {'bytes': len(pcm), 'sha256': sha(pcm), 'peakMin': low, 'peakMax': high},
            'wav': {'file': OUTPUT, 'format': 'canonical 44-byte PCM16 WAV', 'bytes': len(wav), 'sha256': sha(wav)},
            'status': 'machineDraft', 'equalityToOriginalClaimed': False, 'asrAccuracyCertified': False, 'humanReviewVerified': False,
            'losses': LOSSES, 'policy': POLICY,
            'verification': 'Every PCM byte of a fresh native decode of the captured AAC equals the published WAV payload and the '
                            'decoded frame count equals the ffprobe audio-frame total. The capture is an unauthenticated trust anchor: '
                            'no encoder history, signature or authenticity of the recording is claimed.'}


def outcome(directory, options, summary):
    audio = summary['audio']
    return {'status': 'succeeded', 'verified': True, 'artifacts': 2, 'audio': str(directory / OUTPUT), 'summary': str(directory / SUMMARY),
            'sampleRate': audio['sampleRate'], 'channels': audio['channels'], 'frames': audio['frames'],
            'durationSeconds': audio['durationSeconds'], 'codec': 'aac', 'streamIndex': options['streamIndex'], 'lossy': True,
            'equalityToOriginalClaimed': False, 'asrAccuracyCertified': False, 'humanReviewVerified': False}


def evidence_names():
    names = {'authored.json', 'plan.json', 'captures.json', 'input-0000', 'decoded.wav', 'version.stdout', 'version.stderr', 'version-submission.json'}
    for stage in STAGES:
        names.update(stage + suffix for suffix in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr'))
    return names


def publications(directory, held=None):
    held = held or {}
    return [{'file': str(directory / name), 'kind': kind, 'sha256': sha(held[name]) if name in held else file_digest(directory / name)}
            for name, kind in ((OUTPUT, 'file'), (SUMMARY, 'text'))]


def unreferenced(directory):
    """Exact top-level membership, including only declared framework sidecars."""
    known = evidence_names() | {'verification.json', 'result.json', 'schema.snapshot.json', 'publication-metadata.json', 'job.json',
                                OUTPUT, SUMMARY, OUTPUT + '.metadata.json', SUMMARY + '.metadata.json'}
    extra = []
    for path in Path(directory).iterdir():
        if path.name == '.dispatch':
            if path.is_symlink() or not path.is_dir():
                extra.append(path.name)
        elif path.name not in known or path.is_symlink() or not path.is_file():
            extra.append(path.name)
    return sorted(extra)


# ---------------------------------------------------------------- run
def reusable(options):
    data = read_source(options['file'])
    check_structure(data)
    return {options['file']: sha(data)}


def run(document, prepared, directory, executable=None, timeout=300):
    options = prepared['nodes'][0]['options']
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be in (0,3600]')
    paths = trusted(executable)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a fresh directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    deadline = time.monotonic() + timeout
    try:
        capture = read_source(options['file'])
        structure = check_structure(capture)
        (directory / 'input-0000').write_bytes(capture)
        atomic_json(directory / 'captures.json', {'source': options['file'], 'bytes': len(capture), 'sha256': sha(capture)})
        observation = observe(directory, paths, options, capture, deadline, False)
        (directory / OUTPUT).write_bytes(observation['wav'])
        summary = summarize(options, capture, structure, observation)
        atomic_json(directory / SUMMARY, summary)
        atomic_json(directory / 'verification.json', {
            'artifacts': publications(directory), 'evidence': {name: file_digest(directory / name) for name in sorted(evidence_names())},
            'runtime': observation['identity'], 'executables': paths})
        verify(directory, prepared, require_result=False, executable=paths['ffmpeg'], deadline=deadline)
        review.fresh('verify', deadline)
        result = outcome(directory, options, summary)
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        for name in (OUTPUT, SUMMARY):
            try:
                (directory / name).unlink(missing_ok=True)
            except OSError:
                pass
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error), str(directory))
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


# ---------------------------------------------------------------- verification
def verify(directory, prepared, require_result=True, executable=None, deadline=None):
    """Decode the captured compressed bytes again with a trusted runtime and compare every PCM byte with the published WAV.

    The trusted FFmpeg and its sibling ffprobe come from the explicit argument, stored configuration or FFMPEG_EXECUTABLE (never
    PATH, receipts or submissions). The captured ``input-0000``, the published WAV and the summary are read once and judged;
    expectations come from a fresh private decode of the held capture. Retained launchers, bindings, exit codes, the native
    readback, receipt and result are strict, typed, closed consistency checks. Limits: a different FFmpeg build that rounds the
    float-to-PCM16 conversion differently is a verification failure, not a tolerance; a writer that changes the directory after
    the bytes were read is not guarded against; the capture itself is unauthenticated."""
    directory = Path(directory).absolute()
    options = prepared['nodes'][0]['options']
    paths = trusted(executable)

    def read(name, limit=MAX_EVIDENCE):
        value = review.strict_json(review.bounded_bytes(directory / name, limit, name), name)
        if not isinstance(value, dict):
            fail('VERIFICATION_FAILED', 'expected an evidence object', name)
        return value
    if not review.same_json(read('plan.json'), prepared):
        fail('VERIFICATION_FAILED', 'plan differs')
    result = read('result.json')
    if require_result and (result.get('status') != 'succeeded' or result.get('verified') is not True):
        fail('INCOMPLETE_EXECUTION', 'audio extraction did not complete')
    extra = unreferenced(directory)
    if extra:
        fail('VERIFICATION_FAILED', 'unreferenced files in the publication directory: ' + ', '.join(extra[:8]))
    held = {name: review.bounded_bytes(directory / name, limit, name)
            for name, limit in (('input-0000', MAX_SOURCE), (OUTPUT, MAX_WAV), (SUMMARY, MAX_EVIDENCE), ('decoded.wav', MAX_WAV + OUTPUT_SLACK))}
    capture, published = held['input-0000'], held[OUTPUT]
    if not review.same_json(read('captures.json'), {'source': options['file'], 'bytes': len(capture), 'sha256': sha(capture)}):
        fail('VERIFICATION_FAILED', 'source capture record differs from the captured bytes', 'captures.json')
    structure = converted(True, lambda: check_structure(capture), 'input-0000')
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-ffmpeg-audio-'))
    try:
        if directory.resolve() in scratch.resolve().parents or scratch.resolve() in directory.resolve().parents:
            fail('VERIFICATION_FAILED', 'the private verification directory must not overlap the submitted directory', str(scratch))
        (scratch / 'input-0000').write_bytes(capture)
        found = review.observed_fresh(lambda: observe(scratch, paths, options, capture, deadline, True))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if published != found['wav']:
        offset = next((i for i, (a, b) in enumerate(zip(published, found['wav'])) if a != b), min(len(published), len(found['wav'])))
        fail('VERIFICATION_FAILED', 'the published WAV differs from a fresh native decode of the captured AAC', OUTPUT,
             fresh=True, firstDifferingByte=offset, publishedBytes=len(published), freshBytes=len(found['wav']))
    summary = summarize(options, capture, structure, found)
    if not review.same_json(review.strict_json(held[SUMMARY], SUMMARY), summary):
        fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation', SUMMARY)
    retained = review.parse_native_wav(held['decoded.wav'], 'decoded.wav')
    if canonical_wav(retained['sampleRate'], retained['channels'], retained['pcm']) != published:
        fail('VERIFICATION_FAILED', 'the retained native readback differs from the published WAV', 'decoded.wav')
    receipt = read('verification.json')
    if set(receipt) != {'artifacts', 'evidence', 'runtime', 'executables'}:
        fail('VERIFICATION_FAILED', 'receipt claims are not the closed set', 'verification.json')
    if not review.same_json(receipt['artifacts'], publications(directory, held)):
        fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt', 'verification.json')
    evidence = receipt['evidence']
    if not isinstance(evidence, dict) or set(evidence) != evidence_names():
        fail('VERIFICATION_FAILED', 'retained evidence membership differs', 'verification.json')
    for name in sorted(evidence_names()):
        if (sha(held[name]) if name in held else file_digest(directory / name)) != evidence[name]:
            fail('VERIFICATION_FAILED', 'retained evidence differs', name)
    recorded = receipt['executables']
    if (not isinstance(recorded, dict) or set(recorded) != {'ffmpeg', 'ffprobe'}
            or not all(isinstance(v, str) and os.path.isabs(v) for v in recorded.values())):
        fail('VERIFICATION_FAILED', 'receipt executables must be absolute provenance', 'verification.json')
    if recorded['ffprobe'] != os.path.join(os.path.dirname(recorded['ffmpeg']), 'ffprobe'):
        fail('VERIFICATION_FAILED', 'the recorded ffprobe must be the sibling of the recorded ffmpeg', 'verification.json')
    if receipt['runtime'] != review.bounded_bytes(directory / 'version.stdout', MAX_EVIDENCE, 'version.stdout').decode('utf-8', 'replace').splitlines()[0]:
        fail('VERIFICATION_FAILED', 'recorded runtime differs from the retained version output', 'version.stdout')
    # Recorded paths only reconstruct the retained command text for comparison; they are never executed.
    recipe = commands(recorded['ffmpeg'], directory, options)
    version = read('version-submission.json')
    if version.get('nativeCommand') != recipe['version'] or type(version.get('exitCode')) is not int or version['exitCode'] != 0:
        fail('VERIFICATION_FAILED', 'native stage command or completion differs', 'version')
    for stage in STAGES:
        submission = read(stage + '-submission.json')
        record = submission.get('interpreter')
        interpreter = record.get('executable') if isinstance(record, dict) else None
        script = directory / (stage + '-launcher.py')
        if (not isinstance(interpreter, str) or not os.path.isabs(interpreter) or submission.get('nativeCommand') != [interpreter, str(script)]
                or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0):
            fail('VERIFICATION_FAILED', 'native stage command or completion differs', stage)
        limit = limit_for(stage, found['facts'])
        if review.bounded_bytes(script, MAX_EVIDENCE, script.name).decode() != launcher(directory, stage, recipe[stage], limit):
            fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
        if not review.same_json(read(stage + '-inputs.json'), {str(directory / 'input-0000'): sha(capture)}):
            fail('VERIFICATION_FAILED', 'native input binding differs', stage)
        if stage == 'decode' and review.bounded_bytes(directory / 'decode.stderr', MAX_EVIDENCE, 'decode.stderr'):
            fail('VERIFICATION_FAILED', 'a silent native stage logged output', stage)
    if sha(review.bounded_bytes(directory / OUTPUT, MAX_WAV, OUTPUT)) != sha(published) or sha(read_source(directory / 'input-0000')) != sha(capture):
        fail('VERIFICATION_FAILED', 'the published audio or the captured source changed while it was being verified', OUTPUT)
    claims = outcome(directory, options, summary)
    if require_result and not review.same_json(result, claims):
        fail('VERIFICATION_FAILED', 'retained result claims differ from the verified outcome', 'result.json')
    audio = summary['audio']
    return {'verified': True, 'operation': 'extractAudio', 'artifacts': 2,
            'audio': {'sampleRate': audio['sampleRate'], 'channels': audio['channels'], 'frames': audio['frames'],
                      'durationSeconds': audio['durationSeconds']},
            'source': {'codec': 'aac', 'streamIndex': options['streamIndex']}, 'lossy': True, 'runtime': receipt['runtime'],
            'freshNativeVerification': True, 'freshRuntime': found['identity'], 'equalityToOriginalClaimed': False,
            'asrAccuracyCertified': False, 'humanReviewVerified': False}
