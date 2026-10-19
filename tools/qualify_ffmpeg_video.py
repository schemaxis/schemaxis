#!/usr/bin/env python3
"""Native existing-video frame selection with independent per-frame checks."""
import argparse
import copy
import json
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    executable = str(Path(args.executable).absolute())
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
    for source in [*generated.values(), edited]:
        source.unlink()
    for label, *_ in cases:
        assert adaptor.verify(root / label)['verified'], 'offline captured-source verification'
    receipt = {'version': 'schemaxis.ffmpeg.video-qualification/1', 'verified': True,
               'runtime': native([executable, '-version']).decode().splitlines()[0],
               'checks': checks, 'probes': probes,
               'scope': 'Every RGB channel in two72-frame128x72 clip workflows plus six known six/four-frame source workflows and all selected output frames; '
                        'FFV1 baseline, range/rate/source variants, H264 input and MP4 presentation edit list; '
                        'retention/reuse/binding/dishonest receipt/selection/multi-stream/offset/timeout/cancellation probes. No audio, scaling, general codecs or timeline editor.'}
    atomic_json(root / 'qualification.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
