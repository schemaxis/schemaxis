"""Verified AAC-LC/M4A publishing: one prepared canonical PCM16 WAV to ``audio.m4a`` with a numeric error budget.

``encodeAudio`` captures one local canonical PCM16 WAV (mono or stereo at 16000, 22050, 44100 or 48000 Hz, at most 600 s and 32 MiB),
encodes it with FFmpeg's native AAC-LC encoder at an explicit bitrate into an MP4/M4A container, and then judges the *published
bytes*: ffprobe describes the closed container, a bounded frame listing proves the timeline starts at zero, and a fresh native decode
back to PCM16 at the source rate and channel count must have exactly the source frame count. Every interleaved decoded sample is
compared with the captured source; the integer sum of absolute errors divided by the sample count is compared with the authored budget
as an exact rational. That budget is a waveform numeric error in signed PCM16 units. It is not a psychoacoustic, listening,
audibility, recognition or identity measure, and AAC is lossy: nothing here is lossless or high quality. Nothing is resampled, mixed,
normalised, trimmed or padded to fake a count. Verification decodes the published bytes again with the trusted FFmpeg and sibling
ffprobe; it does not re-encode, so an equivalent legitimate encoding is accepted when the declared criteria hold, and the captured
source remains an unauthenticated trust anchor."""
from array import array
from fractions import Fraction
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
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail
from schemaxis.native_command import execute
from . import audio, review

OUTPUT = 'audio.m4a'
SUMMARY = 'audio-publish-summary.json'
DECODED = 'decoded.wav'
SUMMARY_VERSION = 'schemaxis.ffmpeg.audio-publish-summary/1'
LOCATION = '$.nodes[0].options.'
RATES = (16000, 22050, 44100, 48000)
BITRATES = (64, 96, 128, 192)
MAX_SECONDS = 600
MAX_WAV = 32 * 1024 * 1024
MAX_BYTES = 32 * 1024 * 1024
MAX_PCM = MAX_WAV - audio.HEADER
MAX_ERROR = 65535
# A 32 MiB mono WAV holds at most 16777194 sample frames: 16385 AAC packets plus the priming packet, so no accepted source lists more.
MAX_PACKETS = 16500
MAX_PROBE = audio.MAX_PROBE
MAX_EVIDENCE = audio.MAX_EVIDENCE
OUTPUT_SLACK = 4096
CHUNK = 1 << 18
STAGES = ('encode', 'probe', 'frames', 'decode')
PRODUCED = {'encode': OUTPUT, 'probe': 'probe.stdout', 'frames': 'frames.stdout', 'decode': DECODED}
FRAME_SAMPLES = 1024
STAGE_FAULTS = ('RUNNER_FAILED', 'INVALID_RESOURCE', 'NATIVE_EXECUTION_FAILED', 'RESOURCE_LIMIT')
POLICY = ('One AAC-LC stream from a canonical PCM16 WAV at 16000, 22050, 44100 or 48000 Hz (mono or stereo, at most 600 s and 32 MiB); '
          'the published M4A must decode natively at the source rate and channel count to exactly the source frame count on a timeline '
          'that starts at zero under its MP4 edit list; every interleaved sample is compared and sum|error|/samples must not exceed '
          'maxMeanPCMError (exact rational arithmetic, endpoints accepted); the file must not exceed maxBytes; no resampling, channel '
          'mixing, normalising, trimming or padding.')
LOSSES = ['AAC is lossy: the published M4A is not the source samples and is never labelled lossless or high quality',
          'maxMeanPCMError is a mean absolute waveform error in signed PCM16 sample units; it does not measure or certify listening '
          'quality, audibility, speech recognition accuracy or speaker/source identity',
          'AAC removes high-frequency content and quantises the signal, and the decoded waveform can clip at full scale; the budget '
          'bounds the average sample error only, not any single sample, band or passage (the largest sample error is reported)',
          'encoder priming is carried in the MP4 edit list and counted, not assumed; metadata, chapters, cover art and every other '
          'stream are dropped and the encoder identification tag is suppressed',
          'the captured WAV is an unauthenticated local file; a coherent rewrite of the source, output and summary together is not detected']


def trusted(executable=None):
    """review.trusted with encodeAudio wording: explicit argument, stored configuration, environment; never PATH or receipts."""
    try:
        return review.trusted(executable)
    except SchemaxisError as error:
        fault = error.fault
        raise SchemaxisError(Fault(fault.code, fault.message.replace('verifying a muxReview publication', 'running or verifying an encodeAudio publication'),
                                   fault.location, fault.phase, fault.retryable, fault.to_dict()['observed'],
                                   (fault.recovery or '').replace('Pass executable= to verify', 'Pass executable= (--executable or --ffmpeg) to run or verify', 1))) from None


def plan(document, identity, options):
    if 'deliverable' in document:
        fail('INVALID_ARGUMENT', 'encodeAudio verifies its own budgets; deliverable is not accepted', '$.deliverable')
    path = options['file']
    if '\0' in path or not Path(path).is_absolute():
        fail('INVALID_RESOURCE', 'input paths must be absolute and contain no NUL', LOCATION + 'file')
    if Path(path).suffix.lower() != '.wav':
        fail('UNSUPPORTED_AUDIO', 'use an absolute canonical PCM16 .wav source path', LOCATION + 'file')
    budget(options)
    return {'version': 'schemaxis.ffmpeg.plan/1', 'nodes': [{'id': identity, 'filter': 'encodeAudio', 'options': options}],
            'output': OUTPUT, 'summary': SUMMARY, 'losses': LOSSES, 'policy': POLICY}


def budget(options):
    """The authored error budget as an exact rational: its shortest decimal text, never a binary float comparison."""
    value = options['maxMeanPCMError']
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_ERROR:
        fail('INVALID_ARGUMENT', 'maxMeanPCMError must be a finite number from 0 to %d' % MAX_ERROR, LOCATION + 'maxMeanPCMError')
    return Fraction(str(value))


# ---------------------------------------------------------------- source: bounded read and host-side validation (no native process)
def read_source(path):
    """Bounded read of one local regular file; devices and FIFOs are refused before opening and the descriptor is rechecked."""
    try:
        if not stat.S_ISREG(Path(path).stat().st_mode):
            fail('INVALID_RESOURCE', 'input must be a regular file', str(path))
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                fail('INVALID_RESOURCE', 'input must be a regular file', str(path))
            if info.st_size > MAX_WAV:
                fail('RESOURCE_LIMIT', 'WAV input exceeds %d MiB' % (MAX_WAV >> 20), str(path))
            data = stream.read(MAX_WAV + 1)
    except (OSError, ValueError) as error:
        fail('RESOURCE_NOT_FOUND', str(error), str(path))
    if len(data) > MAX_WAV:
        fail('RESOURCE_LIMIT', 'WAV input exceeds %d MiB' % (MAX_WAV >> 20), str(path))
    return data


def source_facts(data):
    """Canonical 44-byte PCM16 WAV in the supported subset; anything else is named and refused, never repaired."""
    wav = review.parse_wav(data, LOCATION + 'file')
    rate, channels, frames = wav['sampleRate'], wav['channels'], wav['samples']
    if rate not in RATES:
        fail('UNSUPPORTED_AUDIO', 'only 16000, 22050, 44100 and 48000 Hz sources are supported; nothing is resampled', LOCATION + 'file',
             sampleRate=rate)
    if frames > MAX_SECONDS * rate:
        fail('RESOURCE_LIMIT', 'audio is longer than %d seconds' % MAX_SECONDS, LOCATION + 'file', frames=frames, sampleRate=rate)
    if len(data) > MAX_WAV:
        fail('RESOURCE_LIMIT', 'the WAV would exceed 32 MiB', LOCATION + 'file', bytes=len(data))
    return {'sampleRate': rate, 'channels': channels, 'frames': frames, 'bytes': wav['bytes'], 'pcm': bytes(wav['pcm'])}


def sha(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- native recipe
def commands(executable, directory, options, rate):
    """The fixed recipe: forced demuxers, file protocol only, no external references, no authored flags, no filters."""
    probe = str(Path(executable).with_name('ffprobe'))
    published = str(directory / OUTPUT)
    reopen = ['-protocol_whitelist', 'file', '-f', 'mov']
    fixed = ['-enable_drefs', '0', '-use_absolute_path', '0']
    return {
        'version': [executable, '-version'],
        'encode': [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-filter_threads', '1',
                   '-protocol_whitelist', 'file', '-f', 'wav', '-i', str(directory / 'input-0000'), '-map', '0:a:0', '-vn', '-sn', '-dn',
                   '-map_metadata', '-1', '-map_chapters', '-1', '-c:a', 'aac', '-profile:a', 'aac_low', '-b:a', '%dk' % options['bitrateKbps'],
                   '-flags:a', '+bitexact', '-fflags', '+bitexact', '-threads', str(options['threads']), '-movflags', '+faststart',
                   '-movie_timescale', str(rate), '-f', 'mp4', published],
        'probe': [probe, '-v', 'error', *reopen, *fixed, '-show_streams', '-show_format', '-show_chapters', '-show_programs',
                  '-of', 'json', published],
        'frames': [probe, '-v', 'error', *reopen, *fixed, '-select_streams', '0', '-read_intervals', '%%+#%d' % (MAX_PACKETS + 100),
                   '-show_frames', '-show_entries', 'frame=pts,nb_samples', '-of', 'json', published],
        'decode': [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-filter_threads', '1',
                   '-threads', str(options['threads']), *reopen, *fixed, '-i', published, '-map', '0:a:0', '-vn', '-sn', '-dn',
                   '-map_metadata', '-1', '-map_chapters', '-1', '-c:a', 'pcm_s16le', '-fflags', '+bitexact', '-f', 'wav',
                   str(directory / DECODED)],
    }


def bound_name(stage):
    return 'input-0000' if stage == 'encode' else OUTPUT


def limit_for(stage, options, frames=None, channels=None):
    """Kernel file-size cap of a stage's output: nothing larger than the byte budget (or the counted decode) is ever produced."""
    if stage == 'encode':
        return options['maxBytes'] + OUTPUT_SLACK
    if stage == 'decode':
        return frames * channels * 2 + OUTPUT_SLACK
    return MAX_PROBE + 1


def launcher(directory, stage, command, limit):
    """Bind the stage to the digest of the exact file it opens, apply resource limits, then exec the fixed argv."""
    path = directory / bound_name(stage)
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


def reached_cap(directory, stage, limit, failure=None):
    """True when the stage's output reached its kernel file-size cap or the stage was killed by the file-size signal (the Python
    launcher ignores SIGXFSZ and the exec'd child inherits that, so a capped stage may leave truncated output and exit zero)."""
    path = directory / PRODUCED[stage]
    if not path.is_symlink() and path.is_file() and path.stat().st_size >= limit:
        return True
    return failure is not None and failure.fault.to_dict()['observed'].get('exitCode') == -signal.SIGXFSZ


def cap_fault(stage, limit, options):
    if stage == 'encode':
        return SchemaxisError(Fault('DELIVERABLE_NOT_MET', 'the encoded M4A reached %d bytes, above the %d-byte maxBytes budget; it was refused, '
            'not truncated' % (limit, options['maxBytes']), LOCATION + 'maxBytes', 'pipeline',
            observed={'stage': stage, 'maxBytes': options['maxBytes'], 'limitBytes': limit},
            recovery='Lower bitrateKbps, shorten the source, or raise maxBytes (at most %d).' % MAX_BYTES))
    if stage == 'decode':
        return SchemaxisError(Fault('RESOURCE_LIMIT', 'the native decode is larger than the counted source frames (%d bytes of output allowed); '
            'it was refused, not truncated' % limit, OUTPUT, 'pipeline', observed={'stage': stage, 'limitBytes': limit},
            recovery='The decoded audio exceeds the source frame count, so the published file does not have the source timeline.'))
    return SchemaxisError(Fault('RESOURCE_LIMIT', 'ffprobe output for %s exceeded the %d-byte probe budget; it was refused, not truncated'
        % (stage, MAX_PROBE), OUTPUT, 'pipeline', observed={'stage': stage, 'limitBytes': MAX_PROBE},
        recovery='The generated container reports more than the bounded probe allows; use a shorter source.'))


def launch(directory, stage, command, limit, deadline, verifying, options):
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
        if reached_cap(directory, stage, limit, failure):
            raise cap_fault(stage, limit, options)
        if failure is not None:
            raise failure
        review.quiet(directory, stage)
        path = directory / PRODUCED[stage]
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise SchemaxisError(Fault('RUNNER_FAILED', 'native stage %s exited successfully but produced no output' % stage, OUTPUT, 'pipeline',
                observed={'stage': stage, 'output': PRODUCED[stage]},
                recovery='Inspect the retained stage logs and the configured runtime, then retry in a fresh directory.'))
    except SchemaxisError as error:
        if verifying and error.fault.code in STAGE_FAULTS:
            fail('VERIFICATION_FAILED', 'fresh native %s of the published bytes failed: %s' % (stage, error.fault.message), stage,
                 cause=error.fault.to_dict())
        raise


def bound_input(directory, stage, data):
    expected = {str(directory / bound_name(stage)): sha(data)}
    path = directory / (stage + '-inputs.json')
    if not review.same_json(review.strict_json(review.bounded_bytes(path, MAX_EVIDENCE, path.name), path.name), expected):
        fail('VERIFICATION_FAILED', 'native stage consumed different bytes than were verified', stage)


# ---------------------------------------------------------------- the closed published container (host-side, no native process)
def refuse(reason, **observed):
    fail('VERIFICATION_FAILED', 'the published M4A is not the closed AAC-LC container: ' + reason, OUTPUT, **observed)


def scan(data, start, end):
    try:
        return list(audio.boxes(data, start, end))
    except SchemaxisError as error:
        refuse(error.fault.message)


def kinds_of(found):
    return [kind for kind, _, _ in found]


def u32(data, offset):
    return struct.unpack('>I', data[offset:offset + 4])[0]


def chunk_layout(data, stsc, stco, sizes, mdat):
    """Account for every payload byte physically: the muxer starts a new chunk before one would reach 1 MiB, so the sample-to-chunk and
    chunk-offset tables are expanded into per-chunk sample counts and byte lengths, and the chunks must tile the mdat payload exactly
    (first offset at the payload start, each offset the previous offset plus the bytes of the samples assigned to it, the last chunk ending
    at the payload end). Table sizes are fixed by their counts, and the counts are bounded by the packet count, before any entry is read."""
    packets = len(sizes)
    if data[stco[1]:stco[1] + 4] != bytes(4) or data[stsc[1]:stsc[1] + 4] != bytes(4):
        refuse('the chunk tables must be version 0 with no flags')
    chunks = u32(data, stco[1] + 4)
    if not 1 <= chunks <= packets or stco[2] - stco[1] != 8 + 4 * chunks:
        refuse('the chunk offset table must hold one entry per chunk (at least one and at most one per packet)', chunks=chunks, packets=packets)
    runs = u32(data, stsc[1] + 4)
    if not 1 <= runs <= chunks or stsc[2] - stsc[1] != 8 + 12 * runs:
        refuse('the sample-to-chunk table must hold between one and one entry per chunk', runs=runs, chunks=chunks)
    table = struct.unpack('>%dI' % (3 * runs), data[stsc[1] + 8:stsc[2]])
    firsts, counts = table[0::3], table[1::3]
    if firsts[0] != 1 or any(b <= a for a, b in zip(firsts, firsts[1:])) or firsts[-1] > chunks:
        refuse('sample-to-chunk runs must start at chunk 1, strictly increase and stay within the chunk offset table', chunks=chunks)
    if any(c < 1 for c in counts) or any(d != 1 for d in table[2::3]):
        refuse('every chunk run must hold at least one sample of sample description 1')
    per_chunk = []
    for index, count in enumerate(counts):
        end = firsts[index + 1] if index + 1 < runs else chunks + 1
        per_chunk.extend([count] * (end - firsts[index]))
    if sum(per_chunk) != packets:
        refuse('the sample-to-chunk table must place exactly the listed packets', placed=sum(per_chunk), packets=packets)
    offsets = struct.unpack('>%dI' % chunks, data[stco[1] + 8:stco[2]])
    sample, expected = 0, mdat[1]
    for index, count in enumerate(per_chunk):
        if offsets[index] != expected:
            refuse('chunk %d does not start where the previous chunk ended (gap, overlap, duplicate or reordered chunk)' % (index + 1),
                   chunk=index + 1, offset=offsets[index], expected=expected)
        expected += sum(sizes[sample:sample + count])
        sample += count
    if expected != mdat[2]:
        refuse('the chunks must end exactly at the end of the mdat payload', chunkEnd=expected, mdatEnd=mdat[2])
    return chunks


def container(data, rate, channels, frames):
    """Byte-accounted geometry of the generated file: boxes, timescales, the edit list, sample tables and mdat all agree."""
    top = scan(data, 0, len(data))
    names = kinds_of(top)
    if names not in ([b'ftyp', b'moov', b'free', b'mdat'], [b'ftyp', b'moov', b'mdat']):
        refuse('top-level boxes must be ftyp, moov, optional empty free, mdat in that order', boxes=[n.decode('latin-1') for n in names])
    ftyp, moov, mdat = top[0], top[1], top[-1]
    if len(top) == 4 and top[2][2] != top[2][1]:
        refuse('the free box must be empty')
    if data[ftyp[1]:ftyp[2]] != b'isom' + struct.pack('>I', 512) + b'isomiso2mp41':
        refuse('unexpected ftyp brands')
    children = scan(data, moov[1], moov[2])
    if kinds_of(children) != [b'mvhd', b'trak', b'udta']:
        refuse('moov must hold exactly one movie header, one track and one metadata container')
    try:
        audio.references(data, moov[1], moov[2])
    except SchemaxisError as error:
        refuse(error.fault.message)
    mvhd, trak, udta = children
    if mvhd[2] - mvhd[1] != 100 or data[mvhd[1]] != 0 or u32(data, mvhd[1] + 12) != rate or u32(data, mvhd[1] + 16) != frames:
        refuse('the movie header must be version 0 at the sample-rate timescale with the source frame count as duration')
    parts = scan(data, trak[1], trak[2])
    if kinds_of(parts) != [b'tkhd', b'edts', b'mdia']:
        refuse('the track must hold exactly tkhd, edts and mdia')
    tkhd, edts, mdia = parts
    if (tkhd[2] - tkhd[1] != 84 or data[tkhd[1]] != 0 or not data[tkhd[1] + 3] & 1 or u32(data, tkhd[1] + 12) != 1
            or u32(data, tkhd[1] + 20) != frames):
        refuse('the track header must be an enabled version 0 track 1 with the source frame count as duration')
    edit = scan(data, edts[1], edts[2])
    if kinds_of(edit) != [b'elst'] or edit[0][2] - edit[0][1] != 20:
        refuse('the edit list must hold exactly one version 0 entry')
    elst = edit[0][1]
    segment, media_time, rate_whole, rate_fraction = struct.unpack('>IiHH', data[elst + 8:elst + 20])
    if data[elst] != 0 or u32(data, elst + 4) != 1 or segment != frames or media_time < 0 or media_time > 2 * FRAME_SAMPLES or (rate_whole, rate_fraction) != (1, 0):
        refuse('the edit list must play frames samples after the priming at unit rate', segmentDuration=segment, mediaTime=media_time)
    media = scan(data, mdia[1], mdia[2])
    if kinds_of(media) != [b'mdhd', b'hdlr', b'minf']:
        refuse('the media must hold exactly mdhd, hdlr and minf')
    mdhd, hdlr, minf = media
    if (mdhd[2] - mdhd[1] != 24 or data[mdhd[1]] != 0 or u32(data, mdhd[1] + 12) != rate or u32(data, mdhd[1] + 16) != frames + media_time
            or data[hdlr[1] + 8:hdlr[1] + 12] != b'soun'):
        refuse('the media header must be a sound track at the sample-rate timescale lasting priming plus frames')
    info = scan(data, minf[1], minf[2])
    if kinds_of(info) != [b'smhd', b'dinf', b'stbl']:
        refuse('the media information must hold exactly smhd, dinf and stbl')
    table = scan(data, info[2][1], info[2][2])
    names = kinds_of(table)
    if names[:5] != [b'stsd', b'stts', b'stsc', b'stsz', b'stco'] or any(n not in (b'sgpd', b'sbgp') for n in names[5:]) or len(set(names)) != len(names):
        refuse('the sample table must hold exactly stsd, stts, stsc, stsz and stco plus optional roll-recovery groups')
    stsd, stts, stsc, stsz, stco = table[:5]
    if u32(data, stsd[1] + 4) != 1:
        refuse('exactly one sample description is required')
    entry = scan(data, stsd[1] + 8, stsd[2])
    if len(entry) != 1 or entry[0][0] != b'mp4a' or entry[0][2] - entry[0][1] < 28:
        refuse('the sample description must be one mp4a entry')
    body = entry[0][1]
    if (struct.unpack('>H', data[body + 16:body + 18])[0] != channels or struct.unpack('>H', data[body + 18:body + 20])[0] != 16
            or u32(data, body + 24) != rate << 16):
        refuse('the mp4a entry must declare the source channel count and sample rate')
    if kinds_of(scan(data, body + 28, entry[0][2])) not in ([b'esds'], [b'esds', b'btrt']):
        refuse('the mp4a entry must hold an esds box and optionally btrt')
    count = u32(data, stts[1] + 4)
    if stts[2] - stts[1] != 8 + 8 * count or not 1 <= count <= 4:
        refuse('unexpected time-to-sample table')
    entries = [struct.unpack('>II', data[stts[1] + 8 + 8 * i:stts[1] + 16 + 8 * i]) for i in range(count)]
    packets = sum(c for c, _ in entries)
    if packets > MAX_PACKETS or sum(c * d for c, d in entries) != frames + media_time:
        refuse('the packet durations must sum to priming plus frames', packets=packets)
    constant = u32(data, stsz[1] + 4)
    if u32(data, stsz[1] + 8) != packets or stsz[2] - stsz[1] != 12 + (0 if constant else 4 * packets):
        refuse('the sample size table must give every packet a size (one constant size, or one entry per packet)')
    # Equal-size packets (silence, a one-frame source) are written as one constant size and no entry table.
    sizes = [constant] * packets if constant else struct.unpack('>%dI' % packets, data[stsz[1] + 12:stsz[2]])
    if sum(sizes) != mdat[2] - mdat[1]:
        refuse('the mdat payload must be exactly the listed packets', mdatBytes=mdat[2] - mdat[1], packetBytes=sum(sizes))
    chunk_layout(data, stsc, stco, sizes, mdat)
    meta = scan(data, udta[1], udta[2])
    if kinds_of(meta) != [b'meta'] or u32(data, meta[0][1]) != 0:
        refuse('the metadata container must hold exactly one meta box')
    items = scan(data, meta[0][1] + 4, meta[0][2])
    if kinds_of(items) != [b'hdlr', b'ilst'] or data[items[0][1] + 8:items[0][1] + 12] != b'mdir' or items[1][2] != items[1][1]:
        refuse('the metadata must be an empty item list (no tags)')
    return {'brand': 'isom', 'bytes': len(data), 'boxes': ['ftyp', 'moov', 'mdat'], 'movieTimescale': rate, 'mediaTimescale': rate,
            'editList': {'entries': 1, 'segmentDuration': segment, 'mediaTime': media_time, 'mediaRate': 1},
            'packets': packets, 'primingFrames': media_time, 'sampleRate': rate, 'channels': channels, 'metadataItems': 0}


def inspect(probe, listing, source, geometry, size):
    """The probe and the decoded-frame timeline must describe exactly the closed container; returns the observed facts."""
    rate, channels, frames = source['sampleRate'], source['channels'], source['frames']
    try:
        streams, form = probe['streams'], probe['format']
        if (not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict) or not isinstance(form, dict)
                or form.get('nb_streams') != 1 or 'mp4' not in str(form.get('format_name')) or probe.get('chapters') or probe.get('programs')):
            refuse('ffprobe must report exactly one stream, no chapters and no programs')
        stream = streams[0]
        if (stream.get('index') != 0 or stream.get('codec_type') != 'audio' or stream.get('codec_name') != 'aac' or stream.get('profile') != 'LC'
                or stream.get('codec_tag_string') != 'mp4a'):
            refuse('the only stream must be AAC-LC (mp4a) audio', codec=stream.get('codec_name'), profile=stream.get('profile'))
        if (int(stream['sample_rate']) != rate or stream['sample_rate'] != str(rate) or type(stream['channels']) is not int
                or stream['channels'] != channels):
            refuse('the stream rate or channel count differs from the source', sampleRate=stream.get('sample_rate'), channels=stream.get('channels'))
        if stream.get('time_base') != '1/%d' % rate or stream.get('start_pts') != 0 or stream.get('start_time') != '0.000000':
            refuse('the stream must start at zero in a 1/sample-rate time base under its edit list', startPts=stream.get('start_pts'))
        if type(stream.get('duration_ts')) is not int or stream['duration_ts'] != frames:
            refuse('the stream duration must be exactly the source frame count', durationTs=stream.get('duration_ts'), frames=frames)
        if type(stream.get('initial_padding')) is not int or stream['initial_padding'] != geometry['primingFrames']:
            refuse('the native priming differs from the edit list', initialPadding=stream.get('initial_padding'))
        if stream.get('nb_frames') != str(geometry['packets']) or form.get('size') != str(size):
            refuse('the packet count or file size differs from the container', nbFrames=stream.get('nb_frames'))
        listed = listing['frames']
        if not isinstance(listed, list) or not listed or len(listed) > geometry['packets']:
            refuse('the decoded frame listing is empty or longer than the packet count')
        position = 0
        for frame in listed:
            samples = audio.integer(frame['nb_samples'], 'nb_samples')
            if audio.integer(frame['pts'], 'pts') != position or not 1 <= samples <= 2 * FRAME_SAMPLES:
                refuse('decoded frames must be contiguous from timestamp zero (gap, overlap or offset found)', expectedPts=position, pts=frame['pts'])
            position += samples
        if position != frames:
            refuse('the decoded frame listing must total exactly the source frame count', listedFrames=position, frames=frames)
    except SchemaxisError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        refuse('unreadable stream facts: %s' % str(error)[:80])
    return {'sampleRate': rate, 'channels': channels, 'frames': frames, 'packets': geometry['packets'], 'primingFrames': geometry['primingFrames'],
            'decodedFrames': len(listed), 'durationTs': stream['duration_ts']}


# ---------------------------------------------------------------- the exact comparison
def samples_of(pcm):
    values = array('h')
    values.frombytes(bytes(pcm))
    if sys.byteorder == 'big':
        values.byteswap()
    return values


def compare(source_pcm, decoded_pcm, channels):
    """Every interleaved sample, in order. Integers throughout: sums of |source - decoded|, the largest error and full-scale counts."""
    if len(source_pcm) != len(decoded_pcm):
        fail('VERIFICATION_FAILED', 'decoded and source sample counts differ', DECODED, sourceBytes=len(source_pcm), decodedBytes=len(decoded_pcm))
    a, b = samples_of(source_pcm), samples_of(decoded_pcm)
    total, largest, per_channel = 0, 0, [0] * channels
    rails = [0, 0]
    step = CHUNK - CHUNK % channels
    for start in range(0, len(a), step):
        x, y = a[start:start + step], b[start:start + step]
        errors = [abs(p - q) for p, q in zip(x, y)]
        total += sum(errors)
        largest = max(largest, max(errors))
        for channel in range(channels):
            per_channel[channel] += sum(errors[channel::channels])
        rails[0] += x.count(32767) + x.count(-32768)
        rails[1] += y.count(32767) + y.count(-32768)
    return {'samples': len(a), 'errorSum': total, 'maxAbsError': largest, 'channelErrorSums': per_channel,
            'sourceFullScale': rails[0], 'decodedFullScale': rails[1]}


def ratio(value):
    return review.ratio(Fraction(value))


def assess(options, measured, size):
    """Replayable budget decision: exact rational mean error against the authored decimal, and the byte budget; endpoints pass."""
    mean = Fraction(measured['errorSum'], measured['samples'])
    limit = budget(options)
    checks = [{'requirement': 'maxMeanPCMError', 'expected': options['maxMeanPCMError'], 'expectedExact': ratio(limit), 'observedExact': ratio(mean),
               'passed': mean <= limit,
               'nextAction': 'Accept this requirement.' if mean <= limit else 'Raise bitrateKbps or revise the declared waveform error budget.'},
              {'requirement': 'maxBytes', 'expected': options['maxBytes'], 'observed': size, 'passed': size <= options['maxBytes'],
               'nextAction': 'Accept this requirement.' if size <= options['maxBytes'] else 'Lower bitrateKbps, shorten the source or revise the byte budget.'}]
    return {'accepted': all(check['passed'] for check in checks), 'checks': checks}


# ---------------------------------------------------------------- observation of the published bytes
def observe(directory, paths, options, source, deadline, verifying, published, version=True):
    """Probe, list and decode the held published bytes (already in ``directory``) and compare every sample with the source.

    A run has already identified the runtime before encoding (``version=False``); verification identifies it in its private directory."""
    recipe = commands(paths['ffmpeg'], directory, options, source['sampleRate'])
    if version:
        execute(recipe['version'], directory, 'version', review.budget('version', deadline))
    identity = (directory / 'version.stdout').read_text(errors='replace').splitlines()[:1]
    if not identity or not identity[0].startswith('ffmpeg version '):
        fail('UNSUPPORTED_RUNTIME', 'the trusted executable does not identify as FFmpeg', 'version', observed=identity[:1])
    for stage in ('probe', 'frames'):
        launch(directory, stage, recipe[stage], limit_for(stage, options), deadline, verifying, options)
        bound_input(directory, stage, published)
    probe = review.strict_json(review.bounded_bytes(directory / 'probe.stdout', MAX_PROBE, 'probe.stdout'), 'probe.stdout')
    listing = review.strict_json(review.bounded_bytes(directory / 'frames.stdout', MAX_PROBE, 'frames.stdout'), 'frames.stdout')
    geometry = container(published, source['sampleRate'], source['channels'], source['frames'])
    facts = inspect(probe, listing, source, geometry, len(published))
    launch(directory, 'decode', recipe['decode'], limit_for('decode', options, source['frames'], source['channels']), deadline, verifying, options)
    bound_input(directory, 'decode', published)
    expected = source['frames'] * source['channels'] * 2
    native = review.parse_native_wav(review.bounded_bytes(directory / DECODED, expected + OUTPUT_SLACK, DECODED), DECODED)
    if (native['sampleRate'], native['channels']) != (source['sampleRate'], source['channels']) or native['bytes'] != expected:
        fail('VERIFICATION_FAILED', 'native decode produced %d PCM frames at %d Hz x %d but the source has %d at %d Hz x %d (trimmed, padded or '
             'resampled output is refused)' % (native['samples'], native['sampleRate'], native['channels'], source['frames'], source['sampleRate'],
                                               source['channels']), DECODED)
    decoded = bytes(native['pcm'])
    return {'facts': facts, 'geometry': geometry, 'decodedPCM': decoded, 'comparison': compare(source['pcm'], decoded, source['channels']),
            'identity': identity[0]}


# ---------------------------------------------------------------- summary, receipt and result
def summarize(options, capture, source, published, found):
    measured, geometry, facts = found['comparison'], found['geometry'], found['facts']
    mean = Fraction(measured['errorSum'], measured['samples'])
    verdict = assess(options, measured, len(published))
    duration = Fraction(source['frames'], source['sampleRate'])
    return {'version': SUMMARY_VERSION, 'operation': 'encodeAudio',
            'source': {'file': 'input-0000', 'container': 'wav', 'bytes': len(capture), 'sha256': sha(capture), 'sampleRate': source['sampleRate'],
                       'channels': source['channels'], 'frames': source['frames'], 'durationSeconds': float(duration),
                       'pcmSHA256': sha(source['pcm'])},
            'encoding': {'codec': 'aac', 'profile': 'LC', 'bitrateKbps': options['bitrateKbps'], 'bitrateBasis': 'encoder target (-b:a); not measured',
                         'container': 'mp4', 'faststart': True, 'lossy': True},
            'published': {'file': OUTPUT, 'bytes': len(published), 'sha256': sha(published),
                          'averageBitsPerSecond': ratio(Fraction(8 * len(published)) / duration)},
            'geometry': {**geometry, 'decodedFrameListing': facts['decodedFrames'], 'durationTs': facts['durationTs']},
            'decoded': {'sampleRate': source['sampleRate'], 'channels': source['channels'], 'frames': source['frames'],
                        'pcmSHA256': sha(found['decodedPCM']), 'evidenceFile': DECODED, 'published': False},
            'comparison': {'unit': 'signed PCM16 sample units', 'samples': measured['samples'], 'absoluteErrorSum': measured['errorSum'],
                           'meanAbsPCMError': ratio(mean), 'meanAbsPCMErrorApprox': float(mean), 'maxAbsPCMError': measured['maxAbsError'],
                           'channelMeanAbsPCMError': [ratio(Fraction(s, source['frames'])) for s in measured['channelErrorSums']],
                           'sourceFullScaleSamples': measured['sourceFullScale'], 'decodedFullScaleSamples': measured['decodedFullScale']},
            'budgets': {'maxMeanPCMError': options['maxMeanPCMError'], 'maxBytes': options['maxBytes'], 'accepted': verdict['accepted'],
                        'checks': verdict['checks']},
            'losslessClaimed': False, 'highQualityClaimed': False, 'perceptualQualityCertified': False, 'recognitionAccuracyCertified': False,
            'identityCertified': False, 'humanReviewVerified': False, 'byteIdenticalSourceAuthenticated': False,
            'losses': LOSSES, 'policy': POLICY,
            'verification': 'A fresh native probe, frame listing and decode of the published M4A at the source rate and channel count '
                            'reproduce exactly the source frame count on a zero-origin timeline, and every interleaved decoded sample was '
                            'compared with the captured WAV. The mean error is a numeric waveform measure only. The captured WAV is an '
                            'unauthenticated trust anchor; the published file is not claimed to be the unique encoding of it.'}


def outcome(directory, options, summary):
    measured = summary['comparison']
    return {'status': 'succeeded', 'verified': True, 'artifacts': 2, 'audio': str(directory / OUTPUT), 'summary': str(directory / SUMMARY),
            'sampleRate': summary['source']['sampleRate'], 'channels': summary['source']['channels'], 'frames': summary['source']['frames'],
            'durationSeconds': summary['source']['durationSeconds'], 'codec': 'aac', 'profile': 'LC', 'bitrateKbps': options['bitrateKbps'],
            'bytes': summary['published']['bytes'], 'meanAbsPCMError': measured['meanAbsPCMError'], 'maxMeanPCMError': options['maxMeanPCMError'],
            'maxBytes': options['maxBytes'], 'lossy': True, 'losslessClaimed': False, 'perceptualQualityCertified': False,
            'recognitionAccuracyCertified': False, 'humanReviewVerified': False}


def evidence_names():
    names = {'authored.json', 'plan.json', 'captures.json', 'input-0000', DECODED, 'version.stdout', 'version.stderr', 'version-submission.json'}
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
    source_facts(data)
    return {options['file']: sha(data)}


def recheck(options, capture):
    """The authored path must still hold the bytes that were captured: a source changed around a launch is refused."""
    if sha(read_source(options['file'])) != sha(capture):
        fail('INVALID_RESOURCE', 'the source changed after it was captured; run again with a stable file', LOCATION + 'file')


def run(document, prepared, directory, executable=None, timeout=300):
    options = prepared['nodes'][0]['options']
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be in (0,3600]')
    paths = trusted(executable)
    # Unsupported or oversized sources are refused here: no run directory and no native process exist yet.
    capture = read_source(options['file'])
    source = source_facts(capture)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a fresh directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    deadline = time.monotonic() + timeout
    try:
        (directory / 'input-0000').write_bytes(capture)
        atomic_json(directory / 'captures.json', {'source': options['file'], 'bytes': len(capture), 'sha256': sha(capture)})
        recipe = commands(paths['ffmpeg'], directory, options, source['sampleRate'])
        execute(recipe['version'], directory, 'version', review.budget('version', deadline))
        recheck(options, capture)
        launch(directory, 'encode', recipe['encode'], limit_for('encode', options), deadline, False, options)
        bound_input(directory, 'encode', capture)
        published = review.bounded_bytes(directory / OUTPUT, MAX_BYTES + OUTPUT_SLACK, OUTPUT)
        if len(published) > options['maxBytes']:
            raise cap_fault('encode', len(published), options)
        found = observe(directory, paths, options, source, deadline, False, published, version=False)
        verdict = assess(options, found['comparison'], len(published))
        if not verdict['accepted']:
            fail('DELIVERABLE_NOT_MET', 'the audio decodes correctly but does not meet the authored budgets', LOCATION + 'maxMeanPCMError',
                 assessment=verdict)
        recheck(options, capture)
        summary = summarize(options, capture, source, published, found)
        atomic_json(directory / SUMMARY, summary)
        atomic_json(directory / 'verification.json', {
            'artifacts': publications(directory), 'evidence': {name: file_digest(directory / name) for name in sorted(evidence_names())},
            'runtime': found['identity'], 'executables': paths})
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
    """Probe, list and decode the held published M4A again with a trusted runtime and compare every sample with the captured WAV.

    The trusted FFmpeg and its sibling ffprobe come from the explicit argument, stored configuration or FFMPEG_EXECUTABLE (never PATH,
    receipts or submissions). The captured ``input-0000``, the published M4A, the summary and the retained decode are read once and
    judged; expectations come from a fresh private observation of the held published bytes. There is no re-encode: equivalent
    legitimate encodings pass when the declared criteria hold. Retained launchers, bindings, exit codes, receipt and result are
    strict, typed, closed consistency checks. Limits: a different FFmpeg build that rounds the float-to-PCM16 conversion differently
    is a verification failure, not a tolerance; a coherent rewrite of source, output and summary together is not detected; a writer that
    changes the directory after the bytes were read is not guarded against; the capture itself is unauthenticated."""
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
        fail('INCOMPLETE_EXECUTION', 'audio publication did not complete')
    extra = unreferenced(directory)
    if extra:
        fail('VERIFICATION_FAILED', 'unreferenced files in the publication directory: ' + ', '.join(extra[:8]))
    held = {name: review.bounded_bytes(directory / name, limit, name)
            for name, limit in (('input-0000', MAX_WAV), (OUTPUT, MAX_BYTES + OUTPUT_SLACK), (SUMMARY, MAX_EVIDENCE), (DECODED, MAX_WAV + OUTPUT_SLACK))}
    capture, published = held['input-0000'], held[OUTPUT]
    if not review.same_json(read('captures.json'), {'source': options['file'], 'bytes': len(capture), 'sha256': sha(capture)}):
        fail('VERIFICATION_FAILED', 'source capture record differs from the captured bytes', 'captures.json')
    try:
        source = source_facts(capture)
    except SchemaxisError as error:
        fail('VERIFICATION_FAILED', 'the retained source no longer satisfies the encodeAudio subset (%s): %s' % (error.fault.code, error.fault.message),
             'input-0000', cause=error.fault.to_dict())
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-ffmpeg-publish-'))
    try:
        if directory.resolve() in scratch.resolve().parents or scratch.resolve() in directory.resolve().parents:
            fail('VERIFICATION_FAILED', 'the private verification directory must not overlap the submitted directory', str(scratch))
        (scratch / OUTPUT).write_bytes(published)
        found = review.observed_fresh(lambda: observe(scratch, paths, options, source, deadline, True, published))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    retained = review.parse_native_wav(held[DECODED], DECODED)
    if bytes(retained['pcm']) != found['decodedPCM'] or (retained['sampleRate'], retained['channels']) != (source['sampleRate'], source['channels']):
        fail('VERIFICATION_FAILED', 'the retained native decode differs from a fresh native decode of the published M4A', DECODED, fresh=True)
    summary = summarize(options, capture, source, published, found)
    if not review.same_json(review.strict_json(held[SUMMARY], SUMMARY), summary):
        fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation', SUMMARY)
    if not summary['budgets']['accepted']:
        fail('DELIVERABLE_NOT_MET', 'the published audio is correct but does not meet the authored budgets', LOCATION + 'maxMeanPCMError',
             assessment={'accepted': False, 'checks': summary['budgets']['checks']})
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
    recipe = commands(recorded['ffmpeg'], directory, options, source['sampleRate'])
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
        limit = limit_for(stage, options, source['frames'], source['channels'])
        if review.bounded_bytes(script, MAX_EVIDENCE, script.name).decode() != launcher(directory, stage, recipe[stage], limit):
            fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
        bound = capture if stage == 'encode' else published
        if not review.same_json(read(stage + '-inputs.json'), {str(directory / bound_name(stage)): sha(bound)}):
            fail('VERIFICATION_FAILED', 'native input binding differs', stage)
        if review.bounded_bytes(directory / (stage + '.stderr'), MAX_EVIDENCE, stage + '.stderr'):
            fail('VERIFICATION_FAILED', 'a silent native stage logged output', stage)
    if (sha(review.bounded_bytes(directory / OUTPUT, MAX_BYTES + OUTPUT_SLACK, OUTPUT)) != sha(published)
            or sha(read_source(directory / 'input-0000')) != sha(capture)):
        fail('VERIFICATION_FAILED', 'the published audio or the captured source changed while it was being verified', OUTPUT)
    claims = outcome(directory, options, summary)
    if require_result and not review.same_json(result, claims):
        fail('VERIFICATION_FAILED', 'retained result claims differ from the verified outcome', 'result.json')
    measured = summary['comparison']
    return {'verified': True, 'operation': 'encodeAudio', 'artifacts': 2,
            'audio': {'sampleRate': source['sampleRate'], 'channels': source['channels'], 'frames': source['frames'],
                      'durationSeconds': summary['source']['durationSeconds'], 'bytes': len(published)},
            'encoding': {'codec': 'aac', 'profile': 'LC', 'bitrateKbps': options['bitrateKbps']},
            'comparison': {'samples': measured['samples'], 'meanAbsPCMError': measured['meanAbsPCMError'],
                           'maxAbsPCMError': measured['maxAbsPCMError']},
            'budgets': {'accepted': True, 'checks': summary['budgets']['checks']}, 'lossy': True, 'runtime': receipt['runtime'],
            'freshNativeVerification': True, 'freshRuntime': found['identity'], 'losslessClaimed': False,
            'perceptualQualityCertified': False, 'recognitionAccuracyCertified': False, 'humanReviewVerified': False}
