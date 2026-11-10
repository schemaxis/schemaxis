#!/usr/bin/env python3
"""Native acceptance of the muxReview operation: FFV1 + PCM16 + SubRip in Matroska with independent readbacks."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave

from schemaxis.adaptors.ffmpeg import adaptor, review as review_module
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.publication_metadata import finalise

FPS, FRAMES, WIDTH, HEIGHT, RATE = 10, 6, 32, 24, 16000
CUES = [(0, 250, 'First caption, with punctuation & an accent: café'), (300, 600, 'Second caption\nover two lines')]


def pixels(index, width=WIDTH, height=HEIGHT):
    return bytes((30 + index * 25 + x * 2 + y + channel * 18) % 230
                 for y in range(height) for x in range(width) for channel in range(3))


def samples(count, step=977):
    return [((i * step) % 24001) - 12000 for i in range(count)]


def write_wav(path, values, rate=RATE, channels=1):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(channels); stream.setsampwidth(2); stream.setframerate(rate)
        stream.writeframes(b''.join(struct.pack('<h', value) for value in values))
    return path


def clock(ms):
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def srt(cues):
    return ''.join(f'{i}\n{clock(s)} --> {clock(e)}\n{t}\n\n' for i, (s, e, t) in enumerate(cues, 1))


def native(command):
    return subprocess.run(command, check=True, timeout=60, capture_output=True).stdout


def fault(callback, expected):
    try:
        callback()
    except SchemaxisError as error:
        assert error.fault.code == expected, (expected, error.fault.to_dict())
        return error.fault.to_dict()
    raise AssertionError('expected ' + expected)


def document(video, audio, captions, status=None):
    options = {'video': str(video), 'audio': str(audio), 'captions': str(captions)}
    if status:
        options['captionStatus'] = status
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'review', 'filter': 'muxReview', 'options': options}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    executable = str(Path(args.executable).absolute())
    probe_tool = str(Path(executable).with_name('ffprobe'))
    root = args.output_directory.absolute(); root.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parent.parent
    fixtures = repository / 'examples/schemaxis/fixtures/ffmpeg'
    checks, probes = {}, {}

    def verify(path, **keywords):
        return adaptor.verify(path, executable=executable, **keywords)

    def encode(label, count=FRAMES, shift=0, fps=FPS):
        raw = root / (label + '.rgb')
        raw.write_bytes(b''.join(pixels(i + shift) for i in range(count)))
        path = root / (label + '.mkv')
        native([executable, '-v', 'error', '-y', '-filter_threads', '1', '-f', 'rawvideo', '-pixel_format', 'rgb24',
                '-video_size', f'{WIDTH}x{HEIGHT}', '-framerate', str(fps), '-i', str(raw), '-an', '-threads', '1',
                '-c:v', 'ffv1', '-level', '1', '-pix_fmt', 'bgr0', str(path)])
        return path
    video = encode('video')
    audio = write_wav(root / 'speech.wav', samples(9600))
    captions = root / 'captions.srt'; captions.write_text(srt(CUES), encoding='utf-8', newline='\n')
    # The committed three-stream literal fixture must be exactly what this tool would construct.
    assert (fixtures / 'review-speech.wav').read_bytes() == audio.read_bytes(), 'committed WAV differs from its construction'
    assert (fixtures / 'review-captions.srt').read_bytes() == captions.read_bytes(), 'committed SRT differs from its construction'

    def independent(directory, expected_audio, expected_cues, count=FRAMES):
        """Re-read the published file with separate FFprobe/FFmpeg invocations and literal expectations."""
        review = directory / 'review.mkv'
        listing = json.loads(native([probe_tool, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(review)]))
        assert [(s['codec_type'], s['codec_name']) for s in listing['streams']] == [
            ('video', 'ffv1'), ('audio', 'pcm_s16le'), ('subtitle', 'subrip')], listing['streams']
        assert listing['format']['nb_streams'] == 3
        out = directory / 'independent'; out.mkdir()
        native([executable, '-v', 'error', '-y', '-i', str(review), '-map', '0:v:0', '-an', '-sn', '-fps_mode', 'passthrough',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(out / 'v.rgb')])
        assert (out / 'v.rgb').read_bytes() == b''.join(pixels(i) for i in range(count)), 'video frames differ from literal pixels'
        native([executable, '-v', 'error', '-y', '-i', str(review), '-map', '0:a:0', '-vn', '-sn', '-c:a', 'pcm_s16le',
                '-f', 'wav', str(out / 'a.wav')])
        with wave.open(str(out / 'a.wav')) as stream:
            decoded = struct.unpack(f'<{stream.getnframes()}h', stream.readframes(stream.getnframes()))
        assert list(decoded) == expected_audio, 'PCM samples differ from literal samples'
        native([executable, '-v', 'error', '-y', '-i', str(review), '-map', '0:s:0', '-c:s', 'srt', '-f', 'srt', str(out / 's.srt')])
        assert (out / 's.srt').read_text(encoding='utf-8') == srt(expected_cues), 'caption cues differ'
        return {'streams': 3, 'video': 'ffv1 bgr0', 'audio': 'pcm_s16le', 'subtitle': 'subrip'}

    # 1. Committed fixtures and a generated literal fixture, native run plus independent readback.
    good = document(video, audio, captions)
    output = root / 'good'
    result = adaptor.run(good, output, executable=executable, timeout=120)
    assert result['verified'] and result['streams'] == 3 and result['captionStatus'] == 'machineDraft', result
    assert result['recognitionAccuracyCertified'] is False and result['humanReviewVerified'] is False
    verified = verify(output)
    assert verified['verified'] and verified['nativeReadbackBound'] and verified['streams'] == 3
    assert verified['freshNativeVerification'] is True and verified['freshRuntime'].startswith('ffmpeg version '), verified
    checks['freshRuntime'] = verified['freshRuntime']
    checks['good'] = independent(output, samples(9600), CUES)
    again = root / 'good-again'
    adaptor.run(good, again, executable=executable, timeout=120)
    checks['deterministicBytes'] = file_digest(again / 'review.mkv') == file_digest(output / 'review.mkv')
    assert checks['deterministicBytes']
    declared = root / 'declared'
    adaptor.run(document(video, audio, captions, 'declaredHumanReviewed'), declared, executable=executable, timeout=120)
    receipt = json.loads((declared / 'verification.json').read_text())['captions']
    assert receipt['status'] == 'declaredHumanReviewed' and receipt['humanReviewVerified'] is False
    # Stereo 48 kHz audio and a caption limit case (exact video end).
    stereo = write_wav(root / 'stereo.wav', [v for s in samples(28800) for v in (s, -s)], 48000, 2)
    adaptor.run(document(video, stereo, captions), root / 'stereo', executable=executable, timeout=120)
    checks['stereo48k'] = verify(root / 'stereo')['verified']
    # Native readback header forms: FFmpeg decodes PCM16 above 48 kHz as fmt-40 WAVE_FORMAT_EXTENSIBLE while the source stays the
    # canonical 16-byte fmt. Odd final sample counts exercise a partial last packet at every supported rate class.
    checks['nativeReadbackRates'] = {}
    for rate, channels in ((8000, 1), (16000, 1), (22050, 1), (48000, 1), (48000, 2), (96000, 1), (96000, 2)):
        label = 'rate-%d-%dch' % (rate, channels)
        frames_count = int(rate * 6 // 10) | 1
        values = [v for s in samples(frames_count) for v in ((s,) if channels == 1 else (s, -s))]
        clip_audio = write_wav(root / (label + '.wav'), values, rate, channels)
        adaptor.run(document(video, clip_audio, captions), root / label, executable=executable, timeout=120)
        verified_rate = verify(root / label)
        assert verified_rate['verified'] and verified_rate['freshNativeVerification'], verified_rate
        readback = (root / label / 'decoded-audio.wav').read_bytes()
        extensible = int.from_bytes(readback[16:20], 'little') == 40
        assert extensible == (rate > 48000), (label, readback[16:20])
        assert readback[-len(values) * 2:] == b''.join(struct.pack('<h', v) for v in values), 'readback PCM differs from literal samples'
        checks['nativeReadbackRates'][label] = {'samples': frames_count, 'readbackFmtChunkBytes': int.from_bytes(readback[16:20], 'little')}
    probes['rate192000'] = fault(lambda: adaptor.run(document(video, write_wav(root / 'rate192k.wav', samples(115201), 192000), captions),
                                                    root / 'run-rate192k', executable=executable), 'UNSUPPORTED_AUDIO')['code']
    assert not (root / 'run-rate192k' / 'review.mkv').exists(), 'a refused rate must not publish'
    # Native valid timelines: 24 and 30 fps (Matroska rounds frame timestamps to milliseconds) and a first caption that
    # starts after zero, so the subtitle stream starts late while video and audio start at zero.
    checks['millisecondQuantisedTimelines'] = {}
    for fps, frames, samples_count, cues in ((24, 12, 8000, [(100, 300, 'Late first cue'), (310, 500, 'Second cue')]),
                                             (30, 15, 8000, [(40, 250, 'Late first cue'), (260, 500, 'Second cue')])):
        label = 'timeline-%dfps' % fps
        clip = encode(label, frames, 0, fps)
        clip_audio = write_wav(root / (label + '.wav'), samples(samples_count))
        clip_captions = root / (label + '.srt'); clip_captions.write_text(srt(cues), encoding='utf-8', newline='\n')
        adaptor.run(document(clip, clip_audio, clip_captions), root / label, executable=executable, timeout=120)
        verified_clip = verify(root / label)
        assert verified_clip['verified'] and verified_clip['freshNativeVerification'] and verified_clip['frames'] == frames, verified_clip
        listing = json.loads(native([probe_tool, '-v', 'error', '-show_streams', '-of', 'json', str(root / label / 'review.mkv')]))
        starts = {s['codec_type']: s['start_time'] for s in listing['streams']}
        assert float(starts['video']) == 0 and float(starts['audio']) == 0, starts
        # This FFmpeg reports the subtitle stream start as 0 whatever the first cue; the first subtitle packet carries the cue time.
        cue_packets = json.loads(native([probe_tool, '-v', 'error', '-select_streams', 's:0', '-show_packets', '-show_entries', 'packet=pts_time',
                                         '-of', 'json', str(root / label / 'review.mkv')]))['packets']
        assert abs(float(cue_packets[0]['pts_time']) - cues[0][0] / 1000) < .0011 and cues[0][0] > 0, cue_packets
        stamps = [f['best_effort_timestamp_time'] for f in json.loads(native([probe_tool, '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                  '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(root / label / 'review.mkv')]))['frames']]
        assert len(stamps) == frames and stamps[1] != '%.6f' % (1 / fps), 'the stamps must be millisecond-rounded, not exact: %s' % stamps[:3]
        checks['millisecondQuantisedTimelines'][label] = {'frames': frames, 'streamStarts': starts, 'firstCuePacketSeconds': cue_packets[0]['pts_time'], 'firstStamps': stamps[:4]}

    # 2. Duration policy at the exact boundary: 0.7 s accepted, one sample longer rejected, no trim or pad.
    edge = write_wav(root / 'edge.wav', samples(11200))
    adaptor.run(document(video, edge, captions), root / 'edge', executable=executable, timeout=120)
    over = write_wav(root / 'over.wav', samples(11201))
    probes['durationJustOver'] = fault(lambda: adaptor.run(document(video, over, captions), root / 'over', executable=executable),
                                       'MEDIA_DURATION_MISMATCH')['observed']['differenceSeconds']
    long = write_wav(root / 'long.wav', samples(16000))
    probes['durationLong'] = fault(lambda: adaptor.run(document(video, long, captions), root / 'long', executable=executable),
                                   'MEDIA_DURATION_MISMATCH')['code']
    short = write_wav(root / 'short.wav', samples(1600))
    probes['durationShort'] = fault(lambda: adaptor.run(document(video, short, captions), root / 'short', executable=executable),
                                    'MEDIA_DURATION_MISMATCH')['code']
    for label in ('over', 'long', 'short'):
        assert not (root / label / 'review.mkv').exists(), 'rejected alignment must not publish'

    # 3. Wrong sources and stream membership.
    two = root / 'two-stream.mkv'
    native([executable, '-v', 'error', '-y', '-i', str(video), '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', str(two)])
    probes['videoWithAudio'] = fault(lambda: adaptor.run(document(two, audio, captions), root / 'two', executable=executable), 'UNSUPPORTED_VIDEO')['code']
    h264 = root / 'h264.mp4'
    native([executable, '-v', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{WIDTH}x{HEIGHT}', '-framerate',
            str(FPS), '-i', str(root / 'video.rgb'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(h264)])
    probes['h264Video'] = fault(lambda: adaptor.run(document(h264, audio, captions), root / 'h264', executable=executable), 'UNSUPPORTED_VIDEO')['code']
    text_video = root / 'text.mkv'; text_video.write_text('not a video')
    probes['textVideo'] = fault(lambda: adaptor.run(document(text_video, audio, captions), root / 'textv', executable=executable), 'INVALID_RESOURCE')['code']
    probes['missingVideo'] = fault(lambda: adaptor.run(document(root / 'absent.mkv', audio, captions), root / 'missv', executable=executable), 'RESOURCE_NOT_FOUND')['code']
    probes['missingAudio'] = fault(lambda: adaptor.run(document(video, root / 'absent.wav', captions), root / 'missa', executable=executable), 'RESOURCE_NOT_FOUND')['code']
    probes['missingCaptions'] = fault(lambda: adaptor.run(document(video, audio, root / 'absent.srt'), root / 'missc', executable=executable), 'RESOURCE_NOT_FOUND')['code']
    probes['mp4Name'] = fault(lambda: adaptor.plan(document(root / 'v.mp4', audio, captions)), 'UNSUPPORTED_VIDEO')['code']
    probes['mp3Name'] = fault(lambda: adaptor.plan(document(video, root / 'a.mp3', captions)), 'UNSUPPORTED_AUDIO')['code']
    probes['vttName'] = fault(lambda: adaptor.plan(document(video, audio, root / 'c.vtt')), 'UNSUPPORTED_CAPTIONS')['code']
    probes['deliverableRejected'] = fault(lambda: adaptor.plan({**good, 'deliverable': {'frames': 6}}), 'INVALID_ARGUMENT')['code']
    wav = audio.read_bytes()
    bad_audio = {
        'floatWav': (wav[:20] + struct.pack('<H', 3) + wav[22:], 'UNSUPPORTED_AUDIO'),
        'eightBitWav': (wav[:34] + struct.pack('<H', 8) + wav[36:], 'UNSUPPORTED_AUDIO'),
        'listChunkWav': (wav[:12] + wav[12:36] + b'LIST\x04\x00\x00\x00abcd' + wav[36:], 'INVALID_RESOURCE'),
        'truncatedWav': (wav[:-100], 'INVALID_RESOURCE'),
        'garbageWav': (b'ID3' + bytes(range(256)) * 4, 'INVALID_RESOURCE'),
    }
    for label, (data, code) in bad_audio.items():
        path = root / (label + '.wav'); path.write_bytes(data)
        probes[label] = fault(lambda: adaptor.run(document(video, path, captions), root / ('run-' + label), executable=executable), code)['code']
    good_srt = srt(CUES)
    bad_captions = {
        'markup': (good_srt.replace('First caption', '<i>First</i> caption'), 'UNSUPPORTED_CAPTIONS'),
        'assOverride': (good_srt.replace('First', '{\\an8}First'), 'UNSUPPORTED_CAPTIONS'),
        'bidiControl': (good_srt.replace('Second', 'Second ‮'), 'UNSUPPORTED_CAPTIONS'),
        'overlap': (srt([(0, 400, 'a'), (300, 600, 'b')]), 'INVALID_RESOURCE'),
        'nonContiguousIndex': (good_srt.replace('2\n00:00:00,300', '3\n00:00:00,300'), 'INVALID_RESOURCE'),
        'zeroLength': (srt([(100, 100, 'a')]), 'INVALID_RESOURCE'),
        'position': (good_srt.replace('00:00:00,250', '00:00:00,250 X1:0'), 'INVALID_RESOURCE'),
        'leadingSpace': (good_srt.replace('Second', ' Second'), 'INVALID_RESOURCE'),
        'noCues': ('', 'INVALID_RESOURCE'),
        'tooManyCues': (srt([(i * 10, i * 10 + 5, 'x') for i in range(1001)]), 'RESOURCE_LIMIT'),
        'afterVideoEnd': (srt([(0, 250, 'a'), (300, 601, 'b')]), 'CAPTIONS_OUT_OF_RANGE'),
    }
    for label, (text, code) in bad_captions.items():
        path = root / (label + '.srt'); path.write_text(text, encoding='utf-8', newline='\n')
        probes[label] = fault(lambda: adaptor.run(document(video, audio, path), root / ('run-' + label), executable=executable), code)['code']
    (root / 'bom.srt').write_bytes(b'\xef\xbb\xbf' + good_srt.encode())
    probes['bom'] = fault(lambda: adaptor.run(document(video, audio, root / 'bom.srt'), root / 'run-bom', executable=executable), 'INVALID_RESOURCE')['code']
    (root / 'latin1.srt').write_bytes(good_srt.encode('latin-1', 'replace'))
    probes['notUtf8'] = fault(lambda: adaptor.run(document(video, audio, root / 'latin1.srt'), root / 'run-latin1', executable=executable), 'INVALID_RESOURCE')['code']
    (root / 'crlf.srt').write_bytes(good_srt.replace('\n', '\r\n').encode())
    adaptor.run(document(video, audio, root / 'crlf.srt'), root / 'run-crlf', executable=executable, timeout=120)
    checks['crlfCaptions'] = verify(root / 'run-crlf')['verified']
    existing = fault(lambda: adaptor.run(good, output, executable=executable), 'OUTPUT_EXISTS')['code']
    probes['outputExists'] = existing

    # 4. Cancellation, timeout and incomplete results, including after the mux stage has produced a file.
    event = threading.Event(); event.set()
    with allocation({'threads': 1}, cancel=event):
        probes['cancelled'] = fault(lambda: adaptor.run(good, root / 'cancelled', executable=executable), 'RUNNER_CANCELLED')['code']
    probes['timeout'] = fault(lambda: adaptor.run(good, root / 'timeout', executable=executable, timeout=.000001), 'RUNNER_TIMED_OUT')['code']
    real_execute, real_time = review_module.execute, review_module.time

    class Clock:
        offset = 0
        monotonic = staticmethod(lambda: real_time.monotonic() + Clock.offset)

    def after_encode(action):
        def wrapper(command, directory, stage, timeout, environment=None):
            report = real_execute(command, directory, stage, timeout, environment)
            if stage == 'encode':
                assert (Path(directory) / 'review.mkv').is_file(), 'the mux stage should have produced a file first'
                action()
            return report
        return wrapper
    late = threading.Event()
    review_module.execute = after_encode(late.set)
    try:
        with allocation({'threads': 1}, cancel=late):
            probes['cancelledAfterMux'] = fault(lambda: adaptor.run(good, root / 'cancelled-late', executable=executable), 'RUNNER_CANCELLED')['code']
    finally:
        review_module.execute = real_execute
    review_module.execute, review_module.time = after_encode(lambda: setattr(Clock, 'offset', 100000)), Clock
    try:
        probes['timeoutAfterMux'] = fault(lambda: adaptor.run(good, root / 'timeout-late', executable=executable, timeout=120), 'RUNNER_TIMED_OUT')['code']
    finally:
        review_module.execute, review_module.time = real_execute, real_time
    for label in ('cancelled', 'timeout', 'cancelled-late', 'timeout-late'):
        assert json.loads((root / label / 'result.json').read_text())['verified'] is False
        assert json.loads((root / label / 'result.json').read_text())['status'] == 'failed'
        assert not (root / label / 'review.mkv').exists(), 'a failed run must not leave an unverified review file'
        probes[label + 'NotVerifiable'] = fault(lambda: verify(root / label), 'VERIFICATION_FAILED')['code']
    shutil.copytree(output, root / 'incomplete', symlinks=True)
    atomic_json(root / 'incomplete' / 'result.json', {'status': 'incomplete', 'verified': False})
    probes['incomplete'] = fault(lambda: verify(root / 'incomplete'), 'INCOMPLETE_EXECUTION')['code']

    # 4b. Fresh verification lifecycle: its private directory is outside the run and removed on cancellation or timeout.
    def temporary():
        return sorted(name for name in os.listdir(tempfile.gettempdir()) if name.startswith('schemaxis-ffmpeg-review-'))
    before = temporary(); seen = []

    def watching(action):
        def wrapper(command, directory, stage, timeout, environment=None):
            report = real_execute(command, directory, stage, timeout, environment)
            seen.append((Path(directory), stage))
            if stage == 'source-probe':
                action()
            return report
        return wrapper
    stop = threading.Event()
    review_module.execute = watching(stop.set)
    try:
        with allocation({'threads': 1}, cancel=stop):
            probes['verifyCancelled'] = fault(lambda: verify(output), 'RUNNER_CANCELLED')['code']
    finally:
        review_module.execute = real_execute
    assert seen and all(output.resolve() not in d.resolve().parents and not d.exists() for d, _ in seen), 'fresh directory must be private and removed'
    assert [stage for _, stage in seen] == ['version', 'source-probe'], seen
    saved_timeout = review_module.VERIFY_TIMEOUT
    review_module.VERIFY_TIMEOUT = 0.0001
    try:
        probes['verifyTimedOut'] = fault(lambda: verify(output), 'RUNNER_TIMED_OUT')['code']
    finally:
        review_module.VERIFY_TIMEOUT = saved_timeout
    assert temporary() == before, 'fresh verification left a temporary directory'
    checks['freshDirectoryCleanup'] = 'private directory outside the run, removed after cancel and timeout'
    assert verify(output)['verified']

    # 4c. Trusted runtime resolution: no runtime means a structured fault, never a PATH or receipt fallback.
    empty_config = root / 'empty-config.json'; atomic_json(empty_config, {'version': 1, 'locations': {}})
    saved_environment = {key: os.environ.get(key) for key in ('FFMPEG_EXECUTABLE', 'PATH', 'SCHEMAXIS_CONFIG')}
    try:
        os.environ.pop('FFMPEG_EXECUTABLE', None)
        os.environ['SCHEMAXIS_CONFIG'] = str(empty_config)
        os.environ['PATH'] = str(Path(executable).parent) + os.pathsep + saved_environment['PATH']    # ffmpeg is on PATH
        refusal = fault(lambda: adaptor.verify(output), 'INTERPRETER_NOT_FOUND')
        assert 'FFMPEG_EXECUTABLE' in refusal['recovery'] and 'bare `schemaxis verify`' in refusal['recovery'], refusal
        probes['noTrustedRuntime'] = refusal['code']
        cli = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(output)], capture_output=True, text=True, timeout=120,
                             env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)})
        assert cli.returncode != 0 and 'INTERPRETER_NOT_FOUND' in cli.stdout + cli.stderr, (cli.stdout[-500:], cli.stderr[-500:])
        probes['bareCliVerifyWithoutRuntime'] = 'INTERPRETER_NOT_FOUND'
        # With the variable or stored configuration the same bare invocation verifies.
        cli = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(output)], capture_output=True, text=True, timeout=300,
                             env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path), 'FFMPEG_EXECUTABLE': executable})
        assert cli.returncode == 0 and json.loads(cli.stdout)['freshNativeVerification'], (cli.stdout[-500:], cli.stderr[-500:])
        stored = root / 'stored-config.json'; atomic_json(stored, {'version': 1, 'locations': {'ffmpeg': executable}})
        cli = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(output)], capture_output=True, text=True, timeout=300,
                             env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path), 'SCHEMAXIS_CONFIG': str(stored)})
        assert cli.returncode == 0, (cli.stdout[-500:], cli.stderr[-500:])
        checks['bareCliVerify'] = 'verifies with FFMPEG_EXECUTABLE or a stored locations.ffmpeg entry'
    finally:
        for key, value in saved_environment.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)

    # 5. Tamper probes with refreshed ordinary publication metadata. Each must still fail verification.
    def tamper(label, name, mutate, retarget=None):
        path = output / name; saved = path.read_bytes(); receipt_path = output / 'verification.json'; saved_receipt = receipt_path.read_bytes()
        try:
            path.write_bytes(mutate(saved))
            if retarget:
                receipt = json.loads(saved_receipt); retarget(receipt); atomic_json(receipt_path, receipt)
            finalise(output)
            probes['tamper-' + label] = fault(lambda: verify(output), 'VERIFICATION_FAILED')['message']
        finally:
            path.write_bytes(saved); receipt_path.write_bytes(saved_receipt); finalise(output)
        assert verify(output)['verified'], 'restored run must verify'

    def flip(data):
        return data[:-3] + bytes([data[-3] ^ 1]) + data[-2:]

    def republish(receipt):
        receipt['artifacts'][0]['sha256'] = file_digest(output / 'review.mkv')
    tamper('review-bytes', 'review.mkv', flip, republish)
    other_srt = srt([(0, 250, 'Changed caption text'), (300, 600, 'Second caption\nover two lines')]).encode()
    tamper('captured-captions', 'input-0002', lambda _: other_srt,
           lambda r: r['sources'][2].__setitem__('sha256', __import__('hashlib').sha256(other_srt).hexdigest()))
    other_audio = write_wav(root / 'other.wav', samples(9600, 331)).read_bytes()
    tamper('captured-audio', 'input-0001', lambda _: other_audio,
           lambda r: r['sources'][1].__setitem__('sha256', __import__('hashlib').sha256(other_audio).hexdigest()))
    other_video = encode('other-video', FRAMES, 100).read_bytes()
    tamper('captured-video', 'input-0000', lambda _: other_video,
           lambda r: r['sources'][0].__setitem__('sha256', __import__('hashlib').sha256(other_video).hexdigest()))
    tamper('extracted-text', 'extracted.srt', lambda d: d.replace(b'Second', b'Secund'))
    tamper('extracted-timing', 'extracted.srt', lambda d: d.replace(b'00:00:00,300', b'00:00:00,301'))
    tamper('decoded-audio', 'decoded-audio.wav', flip)
    tamper('decoded-video', 'decoded.rgb', flip)
    tamper('probe-streams', 'probe.stdout', lambda d: d.replace(b'"subrip"', b'"ass"'))
    for stage in ('encode', 'decode-audio'):
        name = stage + '-submission.json'
        tamper('exit-' + stage, name, lambda d: json.dumps({**json.loads(d), 'exitCode': 1}).encode())
    tamper('binding', 'encode-inputs.json', lambda d: d.replace(b'0', b'1', 1))
    # 5b. Full-refresh adversary: the published file is changed and every retained binding, receipt hash and publication
    # hash is rewritten to agree, so the retained evidence is self-consistent. Only a fresh native decode can refuse it.
    def snapshot(directory):
        return {path: path.read_bytes() for path in directory.rglob('*') if path.is_file() and not path.is_symlink()}

    def restore(directory, saved):
        for path in [p for p in directory.rglob('*') if p.is_file() and not p.is_symlink() and p not in saved]:
            path.unlink()
        for path, data in saved.items():
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)

    def forge_refresh(directory):
        published = directory / 'review.mkv'
        receipt = json.loads((directory / 'verification.json').read_text())
        for stage in review_module.STAGES:
            if stage == 'encode':
                continue
            binding = directory / (stage + '-inputs.json')
            binding.write_text(json.dumps({str(published): file_digest(published)}, sort_keys=True))
            receipt['nativeReadback'][stage]['inputBindingSHA256'] = file_digest(binding)
        receipt['nativeReadback']['encode']['outputSHA256'] = file_digest(published)
        receipt['artifacts'][0]['sha256'] = file_digest(published)
        atomic_json(directory / 'verification.json', receipt); finalise(directory)

    def forged(label, edit, expected_stage_word):
        saved = snapshot(output)
        try:
            published = output / 'review.mkv'; data = published.read_bytes(); changed = edit(data)
            assert changed != data, label + ': the edit must change the published file'
            published.write_bytes(changed); forge_refresh(output)
            refusal = fault(lambda: verify(output), 'VERIFICATION_FAILED')
            assert expected_stage_word in refusal['message'], refusal
            probes['forged-' + label] = refusal['message']
        finally:
            restore(output, saved)
        assert verify(output)['verified'], 'restored run must verify'
    pcm = audio.read_bytes()[44:44 + 64]
    forged('caption-text', lambda d: d.replace(b'Second caption', b'Secund caption'), 'caption')
    forged('audio-samples', lambda d: d.replace(pcm, pcm[:10] + bytes([pcm[10] ^ 1]) + pcm[11:], 1), 'PCM')

    # 5b2. M-A: the retained facts (readbacks, receipt and result) are forged coherently while the captured sources and the published
    # bytes are unchanged; the fresh decode of those unchanged bytes must contradict them, tagged observed.fresh.
    def full_refresh(directory, receipt):
        published = directory / 'review.mkv'
        for stage in review_module.STAGES:
            if stage == 'encode':
                continue
            binding = directory / (stage + '-inputs.json')
            binding.write_text(json.dumps({str(published): file_digest(published)}, sort_keys=True))
            receipt['nativeReadback'][stage]['inputBindingSHA256'] = file_digest(binding)
        for stage, name in review_module.STAGES.items():
            receipt['nativeReadback'][stage]['outputSHA256'] = file_digest(directory / name)
        for stage, name in (('source-probe', 'source-probe.stdout'), ('source-decode', 'source-decoded.rgb')):
            receipt['sourceReadback'][stage]['outputSHA256'] = file_digest(directory / name)
        receipt['artifacts'][0]['sha256'] = file_digest(published)
        receipt['video']['decodedSHA256'] = file_digest(directory / 'decoded.rgb')
        receipt['video']['sourceDecodedSHA256'] = file_digest(directory / 'source-decoded.rgb')
        receipt['audio']['decodedPCMSHA256'] = hashlib.sha256(review_module.parse_native_wav((directory / 'decoded-audio.wav').read_bytes())['pcm']).hexdigest()
        receipt['captions']['extractedSHA256'] = file_digest(directory / 'extracted.srt')
        atomic_json(directory / 'verification.json', receipt)
        atomic_json(directory / 'result.json', review_module.outcome(receipt)); finalise(directory)

    def fresh_refusal(label, apply, stage=None):
        saved = snapshot(output)
        sources = [(output / ('input-000%d' % i)).read_bytes() for i in range(3)]
        try:
            apply()
            assert [(output / ('input-000%d' % i)).read_bytes() for i in range(3)] == sources, label + ': captured sources must be unchanged'
            refusal = fault(lambda: verify(output), 'VERIFICATION_FAILED')
            assert refusal['observed'].get('fresh') is True, label + ': the fault must come from the fresh pass: %s' % refusal
            if stage:
                assert refusal['observed'].get('stage') == stage, (label, stage, refusal)
            probes[label] = {'message': refusal['message'], 'stage': refusal['observed'].get('stage'), 'fresh': True}
        finally:
            restore(output, saved)
        assert verify(output)['verified'], 'restored run must verify'

    def forge_frames():
        for name in ('source-decoded.rgb', 'decoded.rgb'):
            (output / name).write_bytes((output / name).read_bytes() + pixels(5))
        listing = json.loads((output / 'source-probe.stdout').read_text())
        extra = copy.deepcopy(listing['frames'][-1]); extra['best_effort_timestamp_time'] = '0.600000'; listing['frames'].append(extra)
        (output / 'source-probe.stdout').write_text(json.dumps(listing))
        listing = json.loads((output / 'probe.stdout').read_text()); listing['streams'][0]['nb_read_frames'] = '7'
        (output / 'probe.stdout').write_text(json.dumps(listing))
        receipt = json.loads((output / 'verification.json').read_text())
        receipt['frames'] = 7; receipt['duration'] = 0.7
        receipt['artifacts'][0].update(frames=7, duration=0.7)
        receipt['alignment'] = review_module.alignment(9600, 16000, 7, 10, CUES)
        full_refresh(output, receipt)

    def forge_dimensions():
        for name in ('source-probe.stdout', 'probe.stdout'):
            listing = json.loads((output / name).read_text())
            listing['streams'][0]['width'], listing['streams'][0]['height'] = HEIGHT, WIDTH
            for frame in listing.get('frames', []):
                frame['width'], frame['height'] = HEIGHT, WIDTH
            (output / name).write_text(json.dumps(listing))
        receipt = json.loads((output / 'verification.json').read_text())
        receipt.update(width=HEIGHT, height=WIDTH); receipt['artifacts'][0]['dimensions'] = [HEIGHT, WIDTH]
        full_refresh(output, receipt)
    fresh_refusal('forgedFacts-frameCount7', forge_frames, 'facts')
    fresh_refusal('forgedFacts-dimensionsSwapped', forge_dimensions, 'facts')

    # 5b3. M-B and the audio-packet gap: native retimings of the published file with the same bytes, frames and cues. Every
    # retained binding, receipt hash and publication hash is refreshed; only the fresh timeline checks can refuse them.
    published = output / 'review.mkv'; pristine = published.read_bytes()

    def retimed(label, arguments, stage, clean=False):
        shifted = root / (label + '.mkv')
        native([executable, '-v', 'error', '-y', *arguments, '-map_metadata', '-1', '-map_chapters', '-1', '-fflags', '+bitexact',
                '-flags:a', '+bitexact', '-f', 'matroska', str(shifted)])
        if clean:
            tidy = root / (label + '-clean.mkv')
            native([executable, '-v', 'error', '-y', '-i', str(shifted), '-map', '0:v:0', '-map', '0:a:0', '-map', '0:s:0', '-c', 'copy',
                    '-map_metadata', '-1', '-map_metadata:s', '-1', '-map_chapters', '-1', '-fflags', '+bitexact', str(tidy)])
            shifted = tidy
        def apply():
            published.write_bytes(shifted.read_bytes())
            full_refresh(output, json.loads((output / 'verification.json').read_text()))
        assert shifted.read_bytes() != pristine
        listing = json.loads(native([probe_tool, '-v', 'error', '-show_streams', '-of', 'json', str(shifted)]))
        decoded = root / (label + '.wav')
        native([executable, '-v', 'error', '-y', '-f', 'matroska', '-i', str(shifted), '-map', '0:a:0', '-vn', '-sn', '-c:a', 'pcm_s16le',
                '-fflags', '+bitexact', '-f', 'wav', str(decoded)])
        fresh_refusal(label, apply, stage)
        probes[label]['starts'] = {s['codec_type']: s['start_time'] for s in listing['streams']}
        probes[label]['decodedWavBytesEqualCaptured'] = decoded.stat().st_size == audio.stat().st_size
    both = ['-c', 'copy']
    retimed('timeline-audioStartsAt+0.5', ['-i', str(published), '-itsoffset', '0.5', '-i', str(published), '-map', '0:v', '-map', '1:a', '-map', '0:s', *both], 'probe')
    retimed('timeline-audioStartsAt-0.05', ['-i', str(published), '-itsoffset', '-0.05', '-i', str(published), '-map', '0:v', '-map', '1:a', '-map', '0:s', *both], 'probe')
    retimed('timeline-videoPtsShift+0.5', ['-itsoffset', '0.5', '-i', str(published), '-i', str(published), '-map', '0:v', '-map', '1:a', '-map', '1:s', *both], 'probe')
    retimed('timeline-videoPtsShift-0.1', ['-itsoffset', '-0.1', '-i', str(published), '-i', str(published), '-map', '0:v', '-map', '1:a', '-map', '1:s', *both], 'probe')
    gap = ['-i', str(published), '-map', '0:v:0', '-map', '0:a:0', '-map', '0:s:0', '-c:v', 'copy', '-c:s', 'copy', '-c:a', 'pcm_s16le']
    retimed('timeline-audioGap+30ms', [*gap[:-2], '-c:a', 'pcm_s16le', '-af', r'asetpts=PTS+gte(T\,0.2)*0.03/TB'], 'audio-packets', clean=True)
    retimed('timeline-audioOverlap-30ms', [*gap[:-2], '-c:a', 'pcm_s16le', '-af', r'asetpts=PTS-gte(T\,0.2)*0.03/TB'], 'audio-packets', clean=True)
    assert published.read_bytes() == pristine and verify(output)['verified']
    checks['timelineForgeries'] = 'audio and video offsets, a 30 ms internal audio gap and overlap: refused by the fresh pass with every retained hash refreshed'

    # A planted executable in every retained command is inert: the evidence is rewritten consistently to name it, yet
    # verification launches only the trusted runtime and never the planted files.
    sentinel = root / 'planted'; sentinel.mkdir(); marker = root / 'planted-was-run'
    for name in ('ffmpeg', 'ffprobe'):
        (sentinel / name).write_text(f'#!/bin/sh\ntouch {marker}\nexit 1\n'); (sentinel / name).chmod(0o755)

    def plant(directory):
        old, new = str(Path(executable).parent), str(sentinel)
        for path in list(directory.glob('*-launcher.py')) + list(directory.glob('*-submission.json')):
            path.write_text(path.read_text().replace(old, new))
        receipt = json.loads((directory / 'verification.json').read_text())
        for group in ('nativeReadback', 'sourceReadback'):
            for stage, record in receipt[group].items():
                record['launcherSHA256'] = file_digest(directory / (stage + '-launcher.py'))
        atomic_json(directory / 'verification.json', receipt); finalise(directory)
    saved = snapshot(output)
    try:
        plant(output)
        assert str(sentinel) in (output / 'encode-launcher.py').read_text() and str(sentinel) in (output / 'version-submission.json').read_text()
        planted = verify(output)
        assert planted['verified'] and planted['freshRuntime'].startswith('ffmpeg version '), planted
        assert not marker.exists(), 'verification ran a planted executable named by the retained evidence'
        probes['plantedExecutableConsistentEvidence'] = 'verified with the trusted runtime; planted ffmpeg/ffprobe never run'
        published = output / 'review.mkv'; published.write_bytes(published.read_bytes().replace(b'Second caption', b'Secund caption'))
        forge_refresh(output)
        probes['plantedExecutableAndTamper'] = fault(lambda: verify(output), 'VERIFICATION_FAILED')['message']
        assert not marker.exists(), 'verification ran a planted executable'
    finally:
        restore(output, saved)
    assert verify(output)['verified'] and not marker.exists()

    # 5c. Retained result claims must equal the verified outcome by exact type: promotion, numeric/boolean confusion, extras.
    def result_probe(label, mutate):
        path = output / 'result.json'; saved_result = path.read_bytes()
        try:
            claims = json.loads(saved_result); mutate(claims); atomic_json(path, claims); finalise(output)
            probes['result-' + label] = fault(lambda: verify(output), 'VERIFICATION_FAILED')['message']
            assert verify(output, require_result=False)['verified'], 'ordinary evidence is untouched by a result-only change'
        finally:
            path.write_bytes(saved_result); finalise(output)
        assert verify(output)['verified']
    result_probe('human-review-promotion', lambda r: r.update(humanReviewVerified=True))
    result_probe('accuracy-promotion', lambda r: r.update(recognitionAccuracyCertified=True))
    result_probe('status-promotion', lambda r: r.update(captionStatus='declaredHumanReviewed'))
    result_probe('false-as-zero', lambda r: r.update(humanReviewVerified=0))
    result_probe('integer-as-float', lambda r: r.update(streams=3.0))
    result_probe('extra-claim', lambda r: r.update(certified=True))
    result_probe('video-path', lambda r: r.update(video=str(output / 'other.mkv')))
    for label, text in (('duplicate-key', '"streams": 3, "streams": 3,'), ('infinite', '"x": 1e400,')):
        path = output / 'result.json'; saved_result = path.read_bytes()
        try:
            edited = saved_result.decode().replace('"streams": 3,', text, 1)
            assert edited != saved_result.decode(), 'the result edit must change the file'
            path.write_text(edited); finalise(output)
            probes['result-strict-' + label] = fault(lambda: verify(output), 'VERIFICATION_FAILED')['message']
        finally:
            path.write_bytes(saved_result); finalise(output)
    assert verify(output)['verified']

    # Elevating the declared caption status in the authored document must not verify against the retained receipt.
    authored, plan_path = output / 'authored.json', output / 'plan.json'
    saved_authored, saved_plan = authored.read_bytes(), plan_path.read_bytes()
    try:
        promoted = copy.deepcopy(good); promoted['nodes'][0]['options']['captionStatus'] = 'declaredHumanReviewed'
        atomic_json(authored, promoted); atomic_json(plan_path, adaptor.plan(promoted)); finalise(output)
        probes['tamper-status-promotion'] = fault(lambda: verify(output), 'VERIFICATION_FAILED')['code']
    finally:
        authored.write_bytes(saved_authored); plan_path.write_bytes(saved_plan); finalise(output)
    assert verify(output)['verified']

    # 6. Workflow handoff: a verified encodeVideo clip is the muxReview video through $artifact.
    clip_audio = write_wav(root / 'clip.wav', samples(6400))
    clip_srt = root / 'clip.srt'; clip_srt.write_text(srt([(0, 150, 'Clip caption'), (200, 400, 'Clip end')]), encoding='utf-8', newline='\n')
    workflow = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'clip', 'document': {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo', 'options': {
            'file': str(video), 'startFrame': 1, 'endFrame': 5, 'fps': FPS, 'codec': 'ffv1', 'threads': 1}}]}},
        {'id': 'review', 'document': document(video, clip_audio, clip_srt)}]}
    workflow['operations'][1]['document']['nodes'][0]['options']['video'] = {'$artifact': 'clip', 'index': 0}
    workflow_path = root / 'workflow.json'; workflow_path.write_text(json.dumps(workflow))
    environment = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}
    run = subprocess.run([sys.executable, '-m', 'schemaxis', 'run', str(workflow_path), '--output-directory', str(root / 'workflow'),
                          '--ffmpeg', executable], capture_output=True, text=True, timeout=300, env=environment)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    flow = sorted((root / 'workflow' / 'review').glob('batch-*/attempt-*'))[-1]
    whole = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(root / 'workflow')], capture_output=True, text=True,
                           timeout=300, env={**environment, 'FFMPEG_EXECUTABLE': executable})
    assert whole.returncode == 0 and json.loads(whole.stdout)['verified'], whole.stdout[-1000:] + whole.stderr[-1000:]
    checks['workflowVerify'] = json.loads(whole.stdout)
    checks['workflowHandoff'] = verify(flow)['verified']
    out = root / 'workflow' / 'independent'; out.mkdir()
    native([executable, '-v', 'error', '-y', '-i', str(flow / 'review.mkv'), '-map', '0:v:0', '-fps_mode', 'passthrough', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', str(out / 'v.rgb')])
    assert (out / 'v.rgb').read_bytes() == b''.join(pixels(i) for i in range(1, 5)), 'handoff video frames'
    checks['workflowHandoffFrames'] = 'selected frames 1..4 present'
    for label in ('good', 'declared', 'stereo', 'edge', 'run-crlf'):
        assert verify(root / label)['verified'], label

    receipt = {'version': 'schemaxis.ffmpeg.review-qualification/1', 'verified': True,
               'runtime': native([executable, '-version']).decode().splitlines()[0], 'checks': checks, 'probes': probes,
               'limits': ['Verification re-decodes the published review file and the captured video with a trusted FFmpeg and sibling ffprobe (explicit argument, stored configuration or FFMPEG_EXECUTABLE; never a receipt path or PATH) in a private directory and compares against expectations derived from the captured sources; a bare schemaxis verify therefore needs the stored configuration or the environment variable. The captured sources are the trust anchor: a coherent rewrite of captures, receipt and publication is not authenticated against the original paths. Fresh facts must equal the retained facts and receipt by exact type, video and audio must start at 0 s, published frames follow index/fps within Matroska millisecond rounding and audio packets follow the cumulative sample clock; this is timeline consistency, not speech accuracy. The published container bytes are judged by decoding, exact membership and timeline, not by byte-for-byte remuxing. The encodeFrames, encodeSheet and encodeVideo operations use the same fresh decode decision (see qualify_ffmpeg_fresh.py).',
                          'Caption text is a machine draft unless the author declares otherwise; recognition accuracy and human review are never certified.',
                          'Plain-text SubRip only; PCM16 mono/stereo canonical WAV; FFV1 bgr0 Matroska video. No burn-in, AAC, H.264, WebVTT, attachments or arbitrary streams.',
                          'Only the encodeVideo to muxReview handoff ran in this qualifier; the committed fixtures stand in for the SoX WAV and whisper.cpp SRT, which the maintainer ran once separately as a four-job chain on a single clip (not a corpus).'],
               'scope': 'One 6-frame 32x24 10 fps FFV1 video, literal PCM16 and SubRip fixtures; native mux, ffprobe membership, fresh native decode of video/audio/captions compared with literal expectations by a second invocation; duration boundary, wrong-source, extra-stream, malformed/unsupported audio and captions, cancellation and timeout (including after the mux stage, with the unverified file removed), fresh-verification private-directory cleanup, missing trusted runtime (bare CLI verify), incomplete, ordinary and fully-refreshed forged tamper probes, planted executables, and typed result-claim probes; fully refreshed forged retained facts (frame count, dimensions) and timelines (audio offset, video PTS shift, 30 ms audio gap and overlap) each refused by the fresh pass with observed.fresh true; valid 24 and 30 fps millisecond-quantised clips with a late first caption; native readback of PCM16 at 8, 16, 22.05, 48 and 96 kHz (mono and stereo where listed) with odd final sample counts, including the FFmpeg fmt-40 extensible readback above 48 kHz, and a 192 kHz source refused as UNSUPPORTED_AUDIO; workflow handoff of an encodeVideo artifact. Serial, single process; no exhaustive native coverage.'}
    atomic_json(root / 'qualification.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
