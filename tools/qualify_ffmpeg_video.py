#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native existing-video frame selection with independent per-frame checks."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import threading

from schemaxis.adaptors.ffmpeg import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise
from schemaxis.dispatch import allocation


def pixels(index, variant=0, width=32, height=24):
    # Smooth nonuniform rows/channels exercise order, edges and every pixel
    # while remaining meaningful under 4:2:0 delivery conversion.
    return bytes((30 + index * 25 + x * 2 + y + channel * 18 + variant * 7) % 230
                 for y in range(height) for x in range(width) for channel in range(3))


def native(command):
    return subprocess.run(command, check=True, timeout=40, capture_output=True).stdout


def decode(executable, source, destination):
    native([executable, '-v', 'error', '-y', '-threads', '1', '-noautorotate', '-i', str(source),
        '-map', '0:v:0', '-an', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(destination)])
    return destination.read_bytes()


def per_frame(actual, expected, tolerance=0):
    assert len(actual) == sum(map(len, expected)), (len(actual), len(expected))
    observed = []
    offset = 0
    for index, frame in enumerate(expected):
        raw = actual[offset:offset + len(frame)]; offset += len(frame)
        differences = [abs(left - right) for left, right in zip(frame, raw)]
        error = sum(differences) / len(frame)
        assert error <= tolerance, (index, error, tolerance)
        # Retain frame-specific results; no sample, checksum or aggregate-only check.
        observed.append({'index': index, 'channelsCompared': len(frame), 'meanAbsoluteRGBError': error,
                         'maximumAbsoluteRGBError': max(differences)})
    return observed


def fault(callback, expected):
    try:
        callback()
    except SchemaxisError as error:
        assert error.fault.code == expected, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('expected ' + expected)


def source_decode_refusal(observed):
    """Only the fresh verification's refusal of inconsistent source decodes: no other code, message, field or digest name."""
    details = observed.get('observed')
    return (observed.get('code') == 'VERIFICATION_FAILED'
            and observed.get('message') == 'fresh native facts differ from the retained readbacks: sourceDecodedSHA256'
            and observed.get('location') == '$' and observed.get('phase') == 'pipeline' and observed.get('retryable') is False
            and type(details) is dict and set(details) == {'stage', 'differing', 'fresh'}
            and details['stage'] == 'facts' and details['fresh'] is True
            and type(details['differing']) is list and details['differing'] == ['sourceDecodedSHA256'])

def source_decode_refusal_result(retained, run, observed):
    """The retained result.json of that refusal: the adaptor's own final verification recorded the fault, or the framework's
    later verification rewrote the adaptor's succeeded result. Nothing else is accepted."""
    own = {'status': 'failed', 'verified': False, 'fault': observed}
    framework = {'artifacts': 1, 'status': 'failed', 'verified': False, 'video': str(run / 'video.mkv'),
                 'verificationFault': observed['message']}
    return type(retained) is dict and retained.get('verified') is False and retained in (own, framework)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    executable = str(Path(args.executable).absolute())
    # Verification decodes the published bytes again and takes its trusted runtime from the environment (never PATH or receipts).
    os.environ['FFMPEG_EXECUTABLE'] = executable
    root = args.output_directory.absolute(); root.mkdir(parents=True, exist_ok=False)
    generated = {}
    for codec, variant in (('ffv1', 0), ('ffv1', 1), ('h264', 0)):
        key = f'{codec}-{variant}'; raw = root / (key + '.rgb')
        raw.write_bytes(b''.join(pixels(index, variant) for index in range(6)))
        source = root / (key + ('.mkv' if codec == 'ffv1' else '.mp4'))
        encoder = ['-c:v', 'ffv1', '-level', '1', '-pix_fmt', 'bgr0'] if codec == 'ffv1' else [
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-bf', '0', '-g', '30']
        native([executable, '-v', 'error', '-y', '-filter_threads', '1', '-f', 'rawvideo', '-pixel_format',
            'rgb24', '-video_size', '32x24', '-framerate', '10', '-i', str(raw), '-an', '-threads', '1',
            *encoder, str(source)])
        generated[key] = source
    edited = root / 'edit-list.mp4'
    native([executable, '-v', 'error', '-y', '-ss', '0.2', '-i', str(generated['h264-0']),
            '-map', '0:v:0', '-c', 'copy', str(edited)])
    assert b'elst' in edited.read_bytes(), 'fixture must exercise an MP4 edit list'
    cases = [('baseline', generated['ffv1-0'], 1, 4, 12, 0, 0, 0, 'ffv1'),
             ('range-rate-variant', generated['ffv1-0'], 2, 6, 20, 0, 0, 0, 'ffv1'),
             ('changed-source', generated['ffv1-1'], 1, 4, 12, 1, 0, 0, 'ffv1'),
             ('h264-input', generated['h264-0'], 1, 4, 12, 0, 0, 16, 'ffv1'),
             ('mp4-edit-list', edited, 0, 3, 12, 0, 2, 16, 'ffv1'),
             ('h264-output', generated['ffv1-0'], 1, 4, 12, 0, 0, 0, 'h264')]
    checks = {}
    baseline_document = None
    for label, source, start, end, fps, variant, source_offset, tolerance, output_codec in cases:
        independent = decode(executable, source, root / (label + '-source.rgb'))
        count = 6 - source_offset
        source_checks = per_frame(independent, [pixels(index, variant) for index in range(source_offset, 6)], tolerance)
        stride = 32 * 24 * 3
        expected = [independent[index * stride:(index + 1) * stride] for index in range(start, end)]
        authored = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo',
            'options': {'file': str(source), 'startFrame': start, 'endFrame': end, 'fps': fps, 'codec': output_codec}}],
            'deliverable': {'width': 32, 'height': 24, 'frames': end - start,
                            'durationSeconds': (end - start) / fps, 'maxMeanRGBError': 0 if output_codec == 'ffv1' else 16}}
        output = root / label
        adaptor.run(authored, output, executable=executable, timeout=40)
        verified = adaptor.verify(output)
        actual = decode(executable, output / ('video.mkv' if output_codec == 'ffv1' else 'video.mp4'), root / (label + '-independent.rgb'))
        checks[label] = {'verification': verified, 'sourceFrames': source_checks,
                        'selectedFrames': per_frame(actual, expected, 0 if output_codec == 'ffv1' else 16), 'sourceFrameCount': count}
        assert (output / 'schema.snapshot.json').is_file(), 'normal shared schema capture must occur'
        if label == 'baseline':
            baseline_document = authored
    # A longer clip exercises actual interval extraction and retiming, beyond
    # the tiny codec/edit-list edge fixtures and source-bound conformance cases.
    width, height = 128, 72
    long_frames = [pixels(index, width=width, height=height) for index in range(72)]
    long_raw = root / 'long-source.rgb'; long_raw.write_bytes(b''.join(long_frames))
    long_source = root / 'long-source.mkv'
    native([executable, '-v', 'error', '-y', '-filter_threads', '1', '-f', 'rawvideo',
        '-pixel_format', 'rgb24', '-video_size', '128x72', '-framerate', '24', '-i', str(long_raw),
        '-an', '-threads', '1', '-c:v', 'ffv1', '-level', '1', '-pix_fmt', 'bgr0', str(long_source)])
    long_source_checks = per_frame(decode(executable, long_source, root / 'long-source-independent.rgb'), long_frames)
    for label, start, end, fps in [('long-clip', 12, 60, 12), ('long-clip-variant', 24, 72, 24)]:
        authored = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo',
            'options': {'file': str(long_source), 'startFrame': start, 'endFrame': end, 'fps': fps, 'codec': 'ffv1'}}],
            'deliverable': {'width': width, 'height': height, 'frames': end-start,
                            'durationSeconds': (end-start)/fps, 'maxMeanRGBError': 0}}
        output = root / label
        adaptor.run(authored, output, executable=executable, timeout=40)
        actual = decode(executable, output / 'video.mkv', root / (label + '-independent.rgb'))
        checks[label] = {'verification': adaptor.verify(output), 'sourceFrames': long_source_checks,
                        'selectedFrames': per_frame(actual, long_frames[start:end]), 'sourceFrameCount': 72}
    long_source.unlink()
    for label in ('long-clip', 'long-clip-variant'):
        assert adaptor.verify(root / label)['verified']
    output = root / 'baseline'
    original_fingerprint = adaptor.reusableInputs(baseline_document)
    source = generated['ffv1-0']; original_source = source.read_bytes()
    source.write_bytes(generated['ffv1-1'].read_bytes())
    assert original_fingerprint != adaptor.reusableInputs(baseline_document)
    assert adaptor.verify(output)['verified'], 'captured run must survive changed external source'
    source.write_bytes(original_source)
    probes = {}
    unsupported = root / 'two-streams.mkv'
    native([executable, '-v', 'error', '-y', '-i', str(generated['ffv1-0']),
            '-map', '0:v:0', '-map', '0:v:0', '-c', 'copy', str(unsupported)])
    offset = root / 'offset.mkv'
    native([executable, '-v', 'error', '-y', '-itsoffset', '0.2', '-i', str(generated['ffv1-0']),
            '-map', '0:v:0', '-c', 'copy', '-copyts', str(offset)])
    for label, source in [('two-streams', unsupported), ('offset-timestamps', offset)]:
        candidate = copy.deepcopy(baseline_document); candidate['nodes'][0]['options']['file'] = str(source)
        probes[label] = fault(lambda: adaptor.run(candidate, root / (label + '-rejected'), executable=executable),
                              'UNSUPPORTED_VIDEO')['code']
        source.unlink()
    event = threading.Event(); event.set()
    with allocation({'threads': 1}, cancel=event):
        probes['cancelled'] = fault(lambda: adaptor.run(baseline_document, root / 'cancelled', executable=executable),
                                     'RUNNER_CANCELLED')['code']
    # Falsified receipt with refreshed ordinary publication metadata.
    for name, mutate in (
        ('verification.json', lambda value: value.__setitem__('frames', 2)),
        ('source-decode-inputs.json', lambda value: value.update({str(output / 'input-0000'): '0' * 64})),
        ('source-decode-submission.json', lambda value: value.__setitem__('exitCode', 1)),
    ):
        path = output / name; saved = path.read_bytes()
        try:
            value = json.loads(saved); mutate(value); atomic_json(path, value); finalise(output)
            probes[name] = fault(lambda: adaptor.verify(output), 'VERIFICATION_FAILED')['code']
        finally:
            path.write_bytes(saved); finalise(output)
    # Replacing captured compressed bytes and refreshing ordinary hashes must not
    # sever native source-stage binding. Receipt source hashes alone are insufficient.
    source_path = output / 'input-0000'; saved_source = source_path.read_bytes()
    receipt_path = output / 'verification.json'; saved_receipt = receipt_path.read_bytes()
    try:
        source_path.write_bytes(generated['ffv1-1'].read_bytes())
        receipt = json.loads(saved_receipt); receipt['sources'][0]['sha256'] = adaptor.file_digest(source_path)
        atomic_json(receipt_path, receipt); finalise(output)
        probes['refreshed-captured-source'] = fault(lambda: adaptor.verify(output), 'VERIFICATION_FAILED')['code']
    finally:
        source_path.write_bytes(saved_source); receipt_path.write_bytes(saved_receipt); finalise(output)
    # A changed authored selection plus matching plan/receipt summary still needs
    # to match the actual independently decoded selected frames.
    authored_path = output / 'authored.json'; plan_path = output / 'plan.json'
    saved_authored = authored_path.read_bytes(); saved_plan = plan_path.read_bytes()
    try:
        changed = copy.deepcopy(baseline_document)
        changed['nodes'][0]['options'].update(startFrame=2, endFrame=5)
        atomic_json(authored_path, changed); atomic_json(plan_path, adaptor.plan(changed)); finalise(output)
        probes['dishonest-selection'] = fault(lambda: adaptor.verify(output), 'VERIFICATION_FAILED')['code']
    finally:
        authored_path.write_bytes(saved_authored); plan_path.write_bytes(saved_plan); finalise(output)
    invalid = copy.deepcopy(baseline_document); invalid['nodes'][0]['options']['endFrame'] = 7
    probes['out-of-range'] = fault(lambda: adaptor.run(invalid, root / 'out-of-range', executable=executable),
                                   'INVALID_FRAME_RANGE')['code']
    probes['timeout'] = fault(lambda: adaptor.run(baseline_document, root / 'timeout', executable=executable,
                                                 timeout=.000001), 'RUNNER_TIMED_OUT')['code']
    # Real-world H.264 inputs (default B-frames, the adaptor's own output), the
    # whole-source frame limit and damaged containers, each against native FFmpeg.
    def fixture(label, width, height, count, rate, encoder, extension):
        raw = root / (label + '.rgb')
        raw.write_bytes(b''.join(pixels(index, width=width, height=height) for index in range(count)))
        path = root / (label + extension)
        native([executable, '-v', 'error', '-y', '-filter_threads', '1', '-f', 'rawvideo', '-pixel_format', 'rgb24',
                '-video_size', f'{width}x{height}', '-framerate', str(rate), '-i', str(raw), '-an', '-threads', '1',
                *encoder, str(path)])
        raw.unlink(); return path

    def clip(source, start, end, codec='ffv1', fps=12):
        return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo',
            'options': {'file': str(source), 'startFrame': start, 'endFrame': end, 'fps': fps, 'codec': codec}}]}

    x264 = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18']
    ffv1 = ['-c:v', 'ffv1', '-level', '1', '-pix_fmt', 'bgr0']

    def selected(label, source, start, end, document=None):
        output = root / label
        adaptor.run(document or clip(source, start, end), output, executable=executable, timeout=60)
        verified = adaptor.verify(output)
        independent = decode(executable, source, root / (label + '-source.rgb'))
        stride = 64 * 48 * 3
        actual = decode(executable, output / 'video.mkv', root / (label + '-independent.rgb'))
        checks[label] = {'verification': verified, 'sourceFrameCount': len(independent) // stride,
            'selectedFrames': per_frame(actual, [independent[i * stride:(i + 1) * stride] for i in range(start, end)])}
    bframes = fixture('bframes', 64, 48, 30, 10, x264, '.mp4')
    selected('h264-bframe-source', bframes, 3, 20)
    from qualify_ffmpeg_deliverable import image
    pngs = []
    for index in range(5):
        path = root / f'own-{index}.png'; path.write_bytes(image(64, 48, (40 + index * 40, 200 - index * 30, 90 + index * 10, 255)))
        pngs.append(str(path))
    own = root / 'own-h264'
    adaptor.run({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'movie', 'filter': 'encodeFrames',
        'options': {'files': pngs, 'codec': 'h264', 'fps': 25}}]}, own, executable=executable, timeout=60)
    own_source = root / 'own-published.mp4'; own_source.write_bytes((own / 'video.mp4').read_bytes())
    selected('h264-own-output-as-source', own_source, 1, 4)
    for codec, encoder, extension in (('h264', x264, '.mp4'), ('ffv1', ffv1, '.mkv')):
        at_limit = fixture('frames600-' + codec, 16, 16, 600, 30, encoder, extension)
        adaptor.run(clip(at_limit, 0, 600), root / ('limit-ok-' + codec), executable=executable, timeout=120)
        checks['limit-ok-' + codec] = adaptor.verify(root / ('limit-ok-' + codec))
        assert checks['limit-ok-' + codec]['frames'] == 600
        over = fixture('frames601-' + codec, 16, 16, 601, 30, encoder, extension)
        probes['frames601-' + codec] = fault(lambda: adaptor.run(clip(over, 0, 5), root / ('limit-over-' + codec),
            executable=executable, timeout=120), 'RESOURCE_LIMIT')['code']
        at_limit.unlink(); over.unlink()
    complete_mp4 = fixture('fast', 64, 48, 40, 10, x264 + ['-movflags', '+faststart'], '.mp4')
    complete_mkv = fixture('whole', 64, 48, 40, 10, ffv1, '.mkv')
    slow_mp4 = fixture('slow', 64, 48, 20, 10, x264, '.mp4')
    mp4_bytes, mkv_bytes = complete_mp4.read_bytes(), complete_mkv.read_bytes()

    def flipped(data):
        damaged = bytearray(data); middle = len(damaged) * 3 // 4
        for index in range(middle, middle + 400): damaged[index] ^= 0xA5
        return bytes(damaged)
    malformed = {'junk-mp4': ('.mp4', b'not a video at all', 'INVALID_RESOURCE'),
                 'empty-mkv': ('.mkv', b'', 'INVALID_RESOURCE'),
                 'mp4-named-mkv': ('.mkv', mp4_bytes, 'UNSUPPORTED_VIDEO'),
                 # Intact signature and no moov atom: FFprobe itself fails.
                 'truncated-no-moov-mp4': ('.mp4', slow_mp4.read_bytes()[:3000], 'RUNNER_FAILED'),
                 # FFmpeg decodes what it can and exits 0: damage is reported on stderr only.
                 'truncated-tail-mp4': ('.mp4', mp4_bytes[:int(len(mp4_bytes) * .6)], 'INVALID_RESOURCE'),
                 'truncated-mkv': ('.mkv', mkv_bytes[:int(len(mkv_bytes) * .6)], 'INVALID_RESOURCE'),
                 'flipped-mp4': ('.mp4', flipped(mp4_bytes), 'INVALID_RESOURCE')                 }
    for label, (extension, data, code) in malformed.items():
        path = root / (label + extension); path.write_bytes(data)
        observed = fault(lambda: adaptor.run(clip(path, 0, 5), root / (label + '-rejected'),
            executable=executable, timeout=60), code)
        probes[label] = code
        if label.startswith(('truncated-tail', 'truncated-mkv', 'flipped')):
            assert observed['observed']['diagnostics'] and observed['recovery']
            probes[label + '-stage'] = observed['observed']['stage']
    # FFV1 level 1 stores no checksums: a corrupted payload that FFmpeg decodes
    # without any diagnostic cannot be told from different intended pixels. This
    # is a native limit, so it is recorded, not claimed as rejected. FFmpeg may also
    # decode the same corrupted bytes differently from one process to the next, again
    # without diagnostics; fresh verification then refuses the run because the retained
    # and fresh whole-source decodes disagree. That is a refusal of inconsistent native
    # observations, not detection of the corruption: a consistent decode is accepted.
    path = root / 'flipped-ffv1.mkv'; path.write_bytes(flipped(mkv_bytes))
    run = root / 'flipped-ffv1-run'

    def diagnostics():
        return [(run / (stage + '.stderr')).read_text() for stage in ('source-probe', 'source-decode')]
    try:
        adaptor.run(clip(path, 0, 5), run, executable=executable, timeout=60)
        assert diagnostics() == ['', ''], diagnostics()
        limits = {'flipped-ffv1-level1-payload': 'accepted: FFmpeg reports no error, so decoder diagnostics cannot detect it'}
    except SchemaxisError as error:
        observed = error.fault.to_dict()
        if source_decode_refusal(observed):
            assert diagnostics() == ['', ''], diagnostics()
            retained = json.loads((run / 'result.json').read_text())
            assert source_decode_refusal_result(retained, run, observed), retained
            limits = {'flipped-ffv1-level1-payload': 'refused as VERIFICATION_FAILED: the fresh decode of the corrupted source '
                      'differed from the retained decode (sourceDecodedSHA256) with no decoder diagnostics; '
                      'this is not corruption detection, and a consistent decode is accepted'}
        else:
            assert error.fault.code == 'INVALID_RESOURCE', observed
            limits = {'flipped-ffv1-level1-payload': 'rejected as INVALID_RESOURCE'}
    for source in [*generated.values(), edited]:
        source.unlink()
    for label, *_ in cases:
        assert adaptor.verify(root / label)['verified'], 'fresh trusted verification of captured sources'
    receipt = {'version': 'schemaxis.ffmpeg.video-qualification/1', 'verified': True,
               'runtime': native([executable, '-version']).decode().splitlines()[0],
               'checks': checks, 'probes': probes, 'limits': limits,
               'scope': 'Every RGB channel in two72-frame128x72 clip workflows plus six known six/four-frame source workflows and all selected output frames; '
                        'FFV1 baseline, range/rate/source variants, H264 input and MP4 presentation edit list; '
                        'default B-frame H.264 and adaptor-published H.264 as sources; 600-frame acceptance and 601-frame rejection for H.264 and FFV1; malformed, mislabelled and damaged (truncated or byte-corrupted) containers; retention/reuse/binding/dishonest receipt/selection/multi-stream/offset/timeout/cancellation probes. No audio, scaling, general codecs or timeline editor.'}
    atomic_json(root / 'qualification.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
