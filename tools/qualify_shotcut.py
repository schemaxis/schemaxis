#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Independent literal-colour acceptance for native Shotcut timeline cuts/reloads."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import zipfile
from schemaxis.adaptors.shotcut.adaptor import run, verify, _native_verify
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]
COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    directory = args.output_directory.absolute()
    directory.mkdir(parents=True, exist_ok=False)
    ffmpeg = args.executable.absolute().with_name('ffmpeg')
    document = json.loads((ROOT / 'examples/schemaxis/shotcut-timeline.json').read_text())
    document['nodes'][0]['options']['assets'][0]['file'] = str(ROOT / 'examples/schemaxis/shotcut-colours.mkv')
    results = []
    for identity, cuts, order, width, height in [
        ('trim-reorder', [{'asset': 'colours', 'startFrame': 3, 'frameCount': 3}, {'asset': 'colours', 'startFrame': 0, 'frameCount': 2}], [3, 4, 5, 0, 1], 32, 24),
        ('repeat-range', [{'asset': 'colours', 'startFrame': 1, 'frameCount': 2}, {'asset': 'colours', 'startFrame': 1, 'frameCount': 2}], [1, 2, 1, 2], 32, 24),
        ('large-trim-reorder', [{'asset': 'colours', 'startFrame': 3, 'frameCount': 3}, {'asset': 'colours', 'startFrame': 0, 'frameCount': 2}], [3, 4, 5, 0, 1], 400, 200),
    ]:
        case = copy.deepcopy(document)
        case['nodes'][0]['options'].update(clips=cuts, width=width, height=height)
        if width == 400:
            case['nodes'][0]['options']['assets'][0]['file'] = str(ROOT / 'examples/schemaxis/shotcut-colours-large.mkv')
        target = directory / identity
        run(case, target, executable=str(args.executable.absolute()), timeout=120)
        checked = verify(target)
        # This acceptance derives expected colours from reviewed literals, not
        # from adaptor RGB, project XML, receipts or source decode measurements.
        command = [str(ffmpeg), '-nostdin', '-v', 'error', '-i', str(target / 'video.mkv'), '-map', '0:v:0', '-an', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
        result = subprocess.run(command, capture_output=True, timeout=30, check=True)
        expected = b''.join(bytes(COLOURS[index]) * width * height for index in order)
        if result.stdout != expected: raise AssertionError('independent literal source colours/order differ')
        if checked['frames'] != len(order) or checked['duration'] != len(order) / 25: raise AssertionError('independent timeline count/duration differ')
        # Relocate only the native project and captured companion media; it must
        # render without the original input path or the other evidence files.
        relocated = directory / (identity + '-relocated')
        relocated.mkdir()
        with zipfile.ZipFile(target / 'project-bundle.zip') as archive:
            if archive.namelist() != ['project.mlt', 'asset-00.media']:
                raise AssertionError('independent bundle member set differs')
            for filename in archive.namelist():
                data = archive.read(filename)
                if data != (target / filename).read_bytes(): raise AssertionError('independent bundle member bytes differ')
                (relocated / filename).write_bytes(data)
        render = subprocess.run([str(args.executable.absolute()), str(relocated / 'project.mlt'), '-consumer',
            'avformat:' + str(relocated / 'video.mkv'), 'vcodec=ffv1', 'pix_fmt=bgr0', 'level=1',
            'an=1', 'threads=1', 'real_time=-1', 'terminate_on_pause=1'], capture_output=True, timeout=30, check=True)
        (relocated / 'render.stdout').write_bytes(render.stdout)
        (relocated / 'render.stderr').write_bytes(render.stderr)
        command[command.index('-i') + 1] = str(relocated / 'video.mkv')
        if subprocess.run(command, capture_output=True, timeout=30, check=True).stdout != expected:
            raise AssertionError('relocated project/media render differs')
        mutations = []
        for filename in ('video.mkv', 'project.mlt', 'project-bundle.zip', 'asset-00.media', 'video.rgb', 'reopened.mlt', 'reopened-video.rgb', 'render.stderr'):
            path = target / filename
            original = path.read_bytes()
            try:
                path.write_bytes(original + b'tamper')
                try: verify(target)
                except SchemaxisError as error: mutations.append({'file': filename, 'fault': error.fault.code})
                else: raise AssertionError('changed evidence passed verification: ' + filename)
            finally: path.write_bytes(original)
        verify(target)
        # Ordinary artifact manifest refresh must not reuse native readback that
        # consumed different bytes. This does not simulate wholesale forgery.
        for filename, index in (('video.mkv', 0), ('project-bundle.zip', 2)):
            path, receipt_path = target / filename, target / 'verification.json'
            original, receipt_original = path.read_bytes(), receipt_path.read_bytes()
            try:
                path.write_bytes(original + b'changed publication')
                receipt = json.loads(receipt_original)
                receipt['artifacts'][index]['sha256'] = file_digest(path)
                atomic_json(receipt_path, receipt)
                try: _native_verify(target)
                except SchemaxisError as error: mutations.append({'file': filename, 'check': 'ordinary artifact hash refresh at native verifier boundary', 'fault': error.fault.code})
                else: raise AssertionError('changed publication with refreshed artifact hash passed')
            finally:
                path.write_bytes(original)
                receipt_path.write_bytes(receipt_original)
        verify(target)
        results.append({'case': identity, 'verified': True, 'frames': len(order), 'duration': len(order) / 25, 'literalColourOrder': order,
                        'runtime': checked['runtime'], 'relocatedProjectVerified': True, 'mutations': mutations})
    # Bounds are native observations: a host-valid request beyond the actual
    # six-frame source must fail rather than silently hold/repeat its last frame.
    invalid = copy.deepcopy(document)
    invalid['nodes'][0]['options']['clips'] = [{'asset': 'colours', 'startFrame': 5, 'frameCount': 2}]
    try: run(invalid, directory / 'invalid-source-range', executable=str(args.executable.absolute()), timeout=120)
    except SchemaxisError as error:
        if error.fault.code != 'INVALID_RANGE': raise
    else: raise AssertionError('out-of-source range was accepted')
    report = {'verified': True, 'provider': 'shotcut', 'scope': 'Three literal-colour timelines at32x24/400x200, native MLT reload/rerender, changed evidence and source-range rejection; no GUI editing or general media qualification.', 'cases': results}
    atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
